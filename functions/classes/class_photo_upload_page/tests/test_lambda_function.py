import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from common import brand
from functions.classes.class_photo_upload_api import lambda_function as api
from functions.classes.class_photo_upload_api import photo_checks
from functions.classes.class_photo_upload_page import lambda_function
from tests import capture_page_pins, page_csp, page_style

FIXTURES = Path(__file__).parent / "fixtures"
# The served shell before the nonce and config go in: page.html with the shared brand tokens
# and logo filled in, so the style and logo checks below run on what visitors get.
PAGE_HTML = lambda_function._template()

AUTH_DOMAIN = "asmbly-staff.auth.us-east-2.amazoncognito.com"
CLIENT_ID = "fakeappclientid123"
ENV = {
    "STAFF_AUTH_DOMAIN": AUTH_DOMAIN,
    "CLASS_PHOTO_APP_CLIENT_ID": CLIENT_ID,
    "CLASS_PHOTO_DRY_RUN": "false",
}
CONFIG_BLOCK = re.compile(r'<script type="application/json" id="page-config">(.*?)</script>', re.S)


def _event(domain: str | None = None, path: str | None = None) -> dict[str, Any]:
    event = json.loads((FIXTURES / "api_event_page.json").read_text())
    if domain is not None:
        event["requestContext"]["domainName"] = domain
    if path is not None:
        event["requestContext"]["path"] = path
    return event


def _call(event: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    with patch.dict("os.environ", env if env is not None else ENV, clear=True):
        return lambda_function.lambda_handler(event, None)


def _config(body: str) -> dict[str, Any]:
    match = CONFIG_BLOCK.search(body)
    assert match is not None
    return json.loads(match.group(1))


def _csp(response: dict[str, Any]) -> dict[str, str]:
    directives = [part.strip() for part in response["headers"]["Content-Security-Policy"].split(";")]
    return {directive.split(" ", 1)[0]: directive.split(" ", 1)[1] if " " in directive else "" for directive in directives}


def test_serves_page_with_config_and_nonce() -> None:
    response = _call(_event())

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "text/html; charset=utf-8"
    body = response["body"]
    assert _config(body) == {
        "authDomain": AUTH_DOMAIN,
        "clientId": CLIENT_ID,
        "pageUrl": "https://facilities.asmbly.org/class-photo-upload",
        "dryRun": False,
    }
    nonce = _csp(response)["script-src"].removeprefix("'nonce-").removesuffix("'")
    assert nonce and _csp(response)["style-src"] == f"'nonce-{nonce}'"
    assert f'<script nonce="{nonce}">' in body
    assert f'<style nonce="{nonce}">' in body
    assert "__CSP_NONCE__" not in body and "__PAGE_CONFIG__" not in body


def test_stage_page_url_includes_stage() -> None:
    domain = "abc123.execute-api.us-east-2.amazonaws.com"
    env = {**ENV, "CLASS_PHOTO_DRY_RUN": "true"}

    response = _call(_event(domain=domain, path="/stage/class-photo-upload"), env)

    config = _config(response["body"])
    assert config["pageUrl"] == f"https://{domain}/stage/class-photo-upload"
    assert config["dryRun"] is True


@pytest.mark.parametrize("value", [None, "", "TRUE", "no"])
def test_dry_run_is_default(value: str | None) -> None:
    env = {key: item for key, item in ENV.items() if key != "CLASS_PHOTO_DRY_RUN"}
    if value is not None:
        env["CLASS_PHOTO_DRY_RUN"] = value

    assert _config(_call(_event(), env)["body"])["dryRun"] is True


def test_config_json_cannot_close_the_script() -> None:
    client_id = "x</script><script>alert(1)</script>&"

    body = _call(_event(), {**ENV, "CLASS_PHOTO_APP_CLIENT_ID": client_id})["body"]

    assert "alert(1)</script>" not in body
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e\\u0026" in body
    assert body.count("</script>") == 2  # the JSON block and the program
    assert _config(body)["clientId"] == client_id


def test_csp_header() -> None:
    response = _call(_event())

    directives = _csp(response)
    nonce = directives["script-src"]
    assert re.fullmatch(r"'nonce-[A-Za-z0-9_-]{20,}'", nonce)
    assert directives == {
        "default-src": "'none'",
        "script-src": nonce,
        "style-src": nonce,
        "img-src": "blob:",
        "connect-src": f"'self' https://{AUTH_DOMAIN}",
        "base-uri": "'none'",
        "form-action": "'none'",
        "frame-ancestors": "'none'",
    }
    assert "unsafe-inline" not in response["headers"]["Content-Security-Policy"]
    assert response["headers"]["X-Content-Type-Options"] == "nosniff"
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["Referrer-Policy"] == "no-referrer"


def test_nonce_changes_per_request() -> None:
    first = _csp(_call(_event()))["script-src"]
    second = _csp(_call(_event()))["script-src"]

    assert first != second


# The CSP strings this function sent on stage 07b9b79, before story #139 moved the CSP into
# common/csp.py. They must stay byte-identical: same directives, same order, same bytes.
PINNED_CSP = (
    "default-src 'none'; script-src 'nonce-n0nce'; style-src 'nonce-n0nce'; img-src blob:; "
    f"connect-src 'self' https://{AUTH_DOMAIN}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
PINNED_ERROR_CSP = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def test_csp_header_is_byte_for_byte_unchanged() -> None:
    """Story #139 criterion 2, for the header built for a known nonce and the one actually served."""
    assert lambda_function.response_headers(AUTH_DOMAIN, "n0nce")["Content-Security-Policy"] == PINNED_CSP

    served = _call(_event())["headers"]["Content-Security-Policy"]
    assert served.replace(page_csp.nonce(served), "n0nce") == PINNED_CSP


def test_error_page_csp_is_unchanged() -> None:
    """The 400 and 500 pages send the same headers as before, CSP included."""
    expected = {
        "Content-Type": "text/html; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": PINNED_ERROR_CSP,
    }
    bad_request = _call(_event(path="/other"))
    server_error = _call(_event(), {key: value for key, value in ENV.items() if key != "STAFF_AUTH_DOMAIN"})

    assert bad_request["statusCode"] == 400
    assert server_error["statusCode"] == 500
    assert bad_request["headers"] == expected
    assert server_error["headers"] == expected


def test_two_requests_get_different_nonces_on_header_style_and_script() -> None:
    """Story #139 criterion 4: a fresh nonce per request, the same on the header, the <style> and the <script>."""
    first, second = _call(_event()), _call(_event())
    nonces = []
    for response in (first, second):
        policy, body = response["headers"]["Content-Security-Policy"], response["body"]
        assert page_csp.nonce_problems(policy, body) == []
        nonce = page_csp.nonce(policy)
        assert f'<style nonce="{nonce}">' in body
        assert f'<script nonce="{nonce}">' in body
        nonces.append(nonce)

    assert nonces[0] != nonces[1]
    assert nonces[0] not in second["body"]


@pytest.mark.parametrize("missing", lambda_function.REQUIRED_ENV)
def test_missing_env_returns_500_without_details(missing: str, caplog: pytest.LogCaptureFixture) -> None:
    env = {key: value for key, value in ENV.items() if key != missing}

    with caplog.at_level(logging.ERROR):
        response = _call(_event(), env)

    assert response["statusCode"] == 500
    assert "Something went wrong on our side. Try again later." in response["body"]
    assert missing not in response["body"]
    for value in env.values():
        assert value not in response["body"]
    assert missing in caplog.text


def test_invalid_auth_domain_returns_500() -> None:
    response = _call(_event(), {**ENV, "STAFF_AUTH_DOMAIN": "https://evil.example/x"})

    assert response["statusCode"] == 500
    assert "evil" not in response["body"]
    assert "Content-Security-Policy" in response["headers"]


@pytest.mark.parametrize("auth_domain", ["host.example\n", "host.example\r\n", "host.example\nx"])
def test_auth_domain_with_a_line_break_returns_500(auth_domain: str, caplog: pytest.LogCaptureFixture) -> None:
    """A line break in STAFF_AUTH_DOMAIN is refused as not a host name: the logged plain 500,
    never an exception from building the CSP (which would be a 502 with a traceback)."""
    with caplog.at_level(logging.ERROR):
        response = _call(_event(), {**ENV, "STAFF_AUTH_DOMAIN": auth_domain})

    assert response["statusCode"] == 500
    assert response["headers"] == lambda_function.ERROR_HEADERS
    assert "Something went wrong on our side. Try again later." in response["body"]
    assert "host.example" not in response["body"]
    assert "STAFF_AUTH_DOMAIN is not a host name" in caplog.text


@pytest.mark.parametrize(
    "where, value",
    [("domainName", "facilities.asmbly.org\n"), ("path", "/class-photo-upload\n")],
    ids=["domain", "path"],
)
def test_domain_or_path_with_a_trailing_newline_returns_400(where: str, value: str) -> None:
    event = _event()
    event["requestContext"][where] = value

    response = _call(event)

    assert response["statusCode"] == 400
    assert "page-config" not in response["body"]


@pytest.mark.parametrize(
    "path",
    ["/class-photo-upload/classes", "/other", "/a/b/class-photo-upload", "/x\"y/class-photo-upload", "", None],
)
def test_unexpected_path_returns_400(path: str | None) -> None:
    event = _event()
    event["requestContext"]["path"] = path

    response = _call(event)

    assert response["statusCode"] == 400
    assert "page-config" not in response["body"]


@pytest.mark.parametrize("domain", ["evil.example/x", "a b", "", None, "facilities.asmbly.org:443"])
def test_bad_domain_returns_400(domain: str | None) -> None:
    event = _event()
    event["requestContext"]["domainName"] = domain

    assert _call(event)["statusCode"] == 400


def test_event_without_request_context_returns_400() -> None:
    event = _event()
    del event["requestContext"]

    assert _call(event)["statusCode"] == 400
    assert _call([])["statusCode"] == 400  # type: ignore[arg-type]


def test_page_has_public_warning_above_submit() -> None:
    warning = (
        "When you submit, this photo becomes public on GitHub right away, before anyone reviews it. "
        "It stays visible in the pull request even if the pull request is never merged."
    )
    body = _call(_event())["body"]

    warning_at = body.index(warning)
    submit_at = body.index('<button type="button" id="submit"')
    assert warning_at < submit_at
    # Nothing but the warning's closing tag between it and the button.
    assert body[warning_at + len(warning) : submit_at].strip() == "</p>"


def test_page_shows_stage_banner_text() -> None:
    assert (
        "Stage: dry run. Submitting checks the photo and shows what would happen; nothing is opened on GitHub."
        in PAGE_HTML
    )


@pytest.mark.parametrize(
    "message",
    [
        photo_checks.TOO_BIG_MESSAGE.replace("{size:.1f}", "{size}"),
        photo_checks.NOT_JPEG_MESSAGE,
        photo_checks.UNREADABLE_JPEG_MESSAGE,
        photo_checks.WRONG_RATIO_MESSAGE,
        photo_checks.NOT_LANDSCAPE_MESSAGE,
        photo_checks.LOCATION_MESSAGE,
        photo_checks.EXAMPLE_SIZE,
        # The API's messages the page shows itself when an answer carries none.
        api.GENERIC_ERROR,
        api.NEON_ERROR,
        api.FORBIDDEN_ERROR,
    ],
)
def test_page_messages_match_server_messages(message: str) -> None:
    assert f'"{message}"' in PAGE_HTML


def test_page_check_limits_match_the_server() -> None:
    assert f"const MAX_HEADER_SEGMENTS = {photo_checks.MAX_HEADER_SEGMENTS};" in PAGE_HTML
    assert f"const MAX_EMBEDDED_IMAGES = {photo_checks.MAX_EMBEDDED_IMAGES};" in PAGE_HTML
    assert f"const RATIO_TERM_LIMIT = {photo_checks.RATIO_TERM_LIMIT};" in PAGE_HTML
    assert f"const RATIO_TOLERANCE_PERCENT = {photo_checks.RATIO_TOLERANCE_PERCENT};" in PAGE_HTML
    assert photo_checks.MAX_PHOTO_BYTES == 4 * 1024 * 1024
    assert "const MAX_PHOTO_BYTES = 4 * 1024 * 1024;" in PAGE_HTML
    assert f"/{photo_checks.XMP_GPS_PATTERN.pattern.decode('ascii')}/" in PAGE_HTML


def test_page_uses_text_content_not_inner_html() -> None:
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in PAGE_HTML
    # Style attributes would need 'unsafe-inline' under the page's CSP.
    assert "style=" not in PAGE_HTML


def test_template_is_page_html_with_the_brand_filled() -> None:
    """The served shell is page.html with the shared brand tokens and logo filled in, before the nonce and config."""
    raw = lambda_function.PAGE_PATH.read_text(encoding="utf-8")
    assert lambda_function._template() == brand.fill_brand(raw)
    assert raw.count(brand.BRAND_TOKENS_MARKER) == 1
    assert raw.count(brand.ASMBLY_LOGO_MARKER) == 1
    assert lambda_function.NONCE_MARKER in lambda_function._template()
    assert lambda_function._template().count(lambda_function.CONFIG_MARKER) == 1


def test_page_has_one_inline_script_and_style() -> None:
    assert PAGE_HTML.count("<script nonce=") == 1
    assert PAGE_HTML.count("<style nonce=") == 1
    assert PAGE_HTML.count("<script") == 2  # the program and the JSON config


def test_logs_hold_no_query_string(caplog: pytest.LogCaptureFixture) -> None:
    event = _event()
    event["queryStringParameters"] = {"code": "SECRETCODE", "state": "SECRETSTATE"}
    event["multiValueQueryStringParameters"] = {"code": ["SECRETCODE"], "state": ["SECRETSTATE"]}

    with caplog.at_level(logging.DEBUG):
        response = _call(event)

    assert response["statusCode"] == 200
    assert "SECRETCODE" not in caplog.text and "SECRETSTATE" not in caplog.text
    assert "SECRETCODE" not in response["body"]
    assert "Served class photo page (dry_run=False)" in caplog.text


# ---- Brand and design tokens (plan photo-upload-branding, "Design rule") ----
# The checks' logic is in tests/page_style.py (shared with the kiln drop-off viewer);
# this file holds this page's data and its own tests.

STYLE_BLOCK = re.compile(r'<style nonce="__CSP_NONCE__">(.*?)</style>', re.S)
SCRIPT_BLOCKS = re.compile(r"<script\b.*?</script>", re.S)
# Outside :root a declaration's value may hold only var() references, 0, 100% and these
# words: CSS keywords that are not colours, and the header's grid-area names. Anything
# else (a named colour such as whitesmoke, a system colour such as Highlight, a length)
# fails test_styles_use_tokens_only. Add a keyword here only if it can't carry a value.
ALLOWED_VALUE_WORDS = {
    "absolute", "anywhere", "auto", "block", "border-box", "center", "currentColor", "dashed", "ellipsis",
    "grid", "hidden", "important", "inherit", "inline-block", "none", "not-allowed", "nowrap", "pointer",
    "pre-wrap", "rect", "solid", "start", "transparent", "underline",
}
GRID_AREAS = {"logo", "title", "sign-out"}
# Token values: a #rrggbb colour, a reference to another token, a length or unitless
# number, or (for --font-* stacks only) a list of family names.
TOKEN_VALUE = re.compile(r"#[0-9a-fA-F]{6}|var\(--[\w-]+\)|\d*\.?\d+(?:rem|px|fr)?")
# Tokens defined for later phases or used outside var(): see the phase 1 hand-off.
RESERVED_TOKENS = {
    "--breakpoint-wide": "the @media literal repeats it (test_breakpoint_matches_token)",
}
# Literal values two tokens of different kinds may share (plan Design rule 3): a new
# shared literal fails test_tokens_are_defined_once until it is listed here with a reason.
SHARED_LITERALS = {
    "1px": {"--border-width", "--visually-hidden-size"},  # a hairline border; the clip box of hidden text
    "2px": {"--border-width-strong", "--focus-offset"},  # a strong border; the gap before the focus ring
    "1rem": {"--font-size-body", "--space-4"},  # body text size; a spacing step
    "1.25rem": {"--font-size-h2", "--glyph-size"},  # the h2 size; the box a message glyph sits in
}
# The only attributes the inline SVGs may carry; fill only as a same-page paint server.
SVG_ATTRIBUTES = {
    "aria-hidden", "aria-label", "class", "d", "fill", "focusable", "height", "id", "patternUnits",
    "preserveAspectRatio", "role", "viewBox", "width",
}
MEDIA_RULE = re.compile(r"@media\s*\(min-width:\s*([^)]+)\)")

BRAND_COLOURS = {
    "--asmbly-purple": "#292D6A",
    "--asmbly-white": "#F2F4EF",
    "--midnight-black": "#171d1a",
    "--woodwork": "#F3B61B",
    "--metalwork": "#578BC9",
    "--lasers": "#D33E43",
    "--textiles": "#79CCC4",
    "--electronics": "#00916E",
    "--printing-3d": "#EE6E23",
    "--ceramics": "#b34a9a",
}
# (token, first colour, second colour, share of the first): the derivation formula.
DERIVED_COLOURS = [
    ("--asmbly-purple-80", "--asmbly-purple", "--asmbly-white", 0.8),
    ("--asmbly-purple-60", "--asmbly-purple", "--asmbly-white", 0.6),
    ("--asmbly-purple-40", "--asmbly-purple", "--asmbly-white", 0.4),
    ("--asmbly-purple-20", "--asmbly-purple", "--asmbly-white", 0.2),
    ("--lasers-shade", "--lasers", "--midnight-black", 0.8),
    ("--electronics-shade", "--electronics", "--midnight-black", 0.8),
    ("--lasers-20", "--lasers", "--asmbly-white", 0.2),
    ("--woodwork-20", "--woodwork", "--asmbly-white", 0.2),
]
# (foreground, background, minimum WCAG 2.1 contrast ratio).
CONTRAST_PAIRS = [
    ("--text", "--page-bg", 4.5),
    ("--on-dark", "--brand", 4.5),
    ("--brand", "--page-bg", 4.5),
    ("--error", "--page-bg", 4.5),
    ("--ok", "--page-bg", 4.5),
    ("--focus", "--page-bg", 3.0),
    ("--focus-on-dark", "--brand", 3.0),
    ("--text", "--disabled-bg", 4.5),
    ("--control-border", "--page-bg", 3.0),
    ("--text", "--tint-bg", 4.5),
    ("--text", "--warning-bg", 4.5),
    ("--text", "--banner-bg", 4.5),
    ("--text", "--drag-bg", 4.5),
    ("--text", "--code-bg", 4.5),
    ("--on-dark", "--hover-bg", 4.5),
    # The message glyphs: Asmbly White on each kind's edge colour.
    ("--on-dark", "--error", 4.5),
    ("--on-dark", "--ok", 4.5),
    ("--on-dark", "--banner-edge", 4.5),
    # Edges (non-text, 3:1) against the background they sit on.
    ("--error", "--warning-bg", 3.0),
    ("--banner-edge", "--banner-bg", 3.0),
    ("--banner-edge", "--page-bg", 3.0),
]
# The four message kinds: (selector, glyph token).
MESSAGE_KINDS = [
    (".message.error", "--glyph-error"),
    (".message.ok", "--glyph-ok"),
    (".warning", "--glyph-warning"),
    (".banner", "--glyph-banner"),
]
# The page's stylesheet and its markup without its <style> and <script> blocks.
SHEET = page_style.Stylesheet.from_page(PAGE_HTML, STYLE_BLOCK)
MARKUP = page_style.markup(PAGE_HTML, STYLE_BLOCK, SCRIPT_BLOCKS)


def test_page_shows_official_logo_in_header() -> None:
    logo = '<svg class="logo" role="img" aria-label="Asmbly Makerspace"'

    assert PAGE_HTML.count(logo) == 1
    logo_at = PAGE_HTML.index(logo)
    assert logo_at < PAGE_HTML.index('id="dry-run-banner"')
    assert logo_at < PAGE_HTML.index('id="signing-in"')
    header = PAGE_HTML[PAGE_HTML.index('<header class="brand-band">') : PAGE_HTML.index("</header>")]
    assert logo in header and "<h1>Class photo upload</h1>" in header and 'id="sign-out"' in header
    assert page_style.logo_problems(page_style.find_logo(PAGE_HTML)) == []


def test_logo_meets_brand_minimum() -> None:
    assert page_style.rem_to_px(SHEET.tokens()["--logo-height"]) >= 50
    logo_rule = re.search(r"\.logo \{([^}]*)\}", SHEET.css)
    assert logo_rule is not None
    assert "height: var(--logo-height)" in logo_rule.group(1)
    assert "fill: currentColor" in logo_rule.group(1)


def test_pattern_is_decorative() -> None:
    start = '<svg class="pattern" aria-hidden="true" focusable="false"'

    assert PAGE_HTML.count('<svg class="pattern"') == 1
    assert PAGE_HTML.count(start) == 1
    pattern_at = PAGE_HTML.index(start)
    svg = PAGE_HTML[pattern_at : PAGE_HTML.index("</svg>", pattern_at)]
    assert pattern_at < PAGE_HTML.index("</header>") < PAGE_HTML.index('id="dry-run-banner"')
    for forbidden in ("<text", "<image", "href", "<script", 'fill="#', "stroke="):
        assert forbidden not in svg
    assert not re.search(r"<(?:path|rect|circle|ellipse|polygon)\b(?![^>]*\bclass=)(?![^>]*\bfill=\"url)", svg)
    shape_classes = set(re.findall(r'<(?:path|rect|circle|ellipse|polygon) class="([\w-]+)"', svg))
    fills = dict(re.findall(r"\.pattern \.([\w-]+) \{ fill: var\(--([\w-]+)\); \}", SHEET.css))
    assert shape_classes and shape_classes <= set(fills)
    # Each colour class is filled with the token of the same name (.pattern .lasers -> --lasers).
    assert all(fills[name] == name for name in shape_classes), fills


def test_brand_tokens_match_the_guide() -> None:
    assert page_style.brand_colour_problems(SHEET, BRAND_COLOURS) == []


@pytest.mark.parametrize("name,first,second,share", DERIVED_COLOURS)
def test_derived_tokens_follow_the_formula(name: str, first: str, second: str, share: float) -> None:
    assert page_style.derived_colour_problems(SHEET, [(name, first, second, share)]) == []


def test_styles_use_tokens_only() -> None:
    problems = page_style.tokens_only_problems(
        SHEET,
        allowed_words=ALLOWED_VALUE_WORDS | GRID_AREAS,
        string_words=GRID_AREAS,
        font_shorthand={"inherit"},
        min_declarations=101,
    )
    assert problems == []
    for forbidden in ('fill="#', 'stroke="#', "style=", "color="):
        assert forbidden not in MARKUP
    assert page_style.svg_attribute_problems(MARKUP, SVG_ATTRIBUTES, fill=re.compile(r"url\(#[\w-]+\)")) == []


def test_token_block_holds_only_tokens() -> None:
    problems = page_style.token_block_problems(SHEET, token_value=TOKEN_VALUE, glyph_exempt=("--glyph-size", "--glyph-offset"))
    assert problems == []


def test_every_token_is_used() -> None:
    assert page_style.unused_token_problems(SHEET, RESERVED_TOKENS) == []


def test_breakpoint_matches_token() -> None:
    conditions = MEDIA_RULE.findall(SHEET.css)

    assert conditions == [SHEET.tokens()["--breakpoint-wide"]]
    # Any other media query (prefers-reduced-motion, say) carries no number of its own.
    for query in re.findall(r"@media([^{]*)\{", SHEET.css):
        assert MEDIA_RULE.fullmatch("@media" + query.rstrip()) or not re.search(r"\d", query), query


def test_tokens_are_defined_once() -> None:
    # Names, colours and font stacks are written once; any other literal (a length, a
    # number) is written once too, apart from SHARED_LITERALS.
    assert page_style.defined_once_problems(SHEET, SHARED_LITERALS) == []
    definitions = page_style.TOKEN.findall(SHEET.root_block())
    steps = [value.strip() for name, value in definitions if re.fullmatch(r"--space-\d+", name)]
    assert len(steps) == len(set(steps)) and len(steps) >= 6


def test_every_token_used_is_defined() -> None:
    assert page_style.undefined_token_problems(SHEET) == []


# The pins: the tokens and rules the page serves, as on stage 6fd11c9 before story #138. The
# served <style> carries the request's nonce.
SERVED_STYLE_BLOCK = re.compile(r'<style nonce="[A-Za-z0-9_-]+">(.*?)</style>', re.S)


def _served_sheet() -> page_style.Stylesheet:
    response = _call(_event())
    assert response["statusCode"] == 200
    return page_style.Stylesheet.from_page(response["body"], SERVED_STYLE_BLOCK)


def test_served_tokens_are_the_stage_tokens() -> None:
    """Story #138 criterion 3: the served page has stage 6fd11c9's :root tokens, by name and value.

    After a deliberate change to the page's look, regenerate the pins with
    `.venv/bin/python -m tests.capture_page_pins` and commit them with the change.
    """
    sheet = _served_sheet()

    assert sheet.tokens() == json.loads((FIXTURES / "pinned_tokens.json").read_text(encoding="utf-8"))
    assert "color-scheme: light;" in sheet.root_block()


def test_served_rules_are_the_stage_rules() -> None:
    """Story #138 criterion 3: the served page has stage 6fd11c9's CSS rules after :root.

    After a deliberate change to the page's look, regenerate the pins with
    `.venv/bin/python -m tests.capture_page_pins` and commit them with the change.
    """
    pinned = (FIXTURES / "pinned_rules.css").read_text(encoding="utf-8")

    assert capture_page_pins.pinned_rules_text(_served_sheet()) == pinned


def test_page_has_no_pure_white_or_black() -> None:
    for colour in ("#fff", "#000"):
        assert colour not in PAGE_HTML.lower()
    assert not page_style.PURE_WHITE_OR_BLACK.search(SHEET.css)
    ceramics = re.findall(r"[^{}]+\{[^}]*var\(--ceramics\)[^}]*\}", SHEET.rules_after_root())
    assert ceramics and all(rule.strip().startswith(".pattern ") for rule in ceramics)
    assert [name for name, value in SHEET.tokens().items() if value == "var(--ceramics)"] == []


@pytest.mark.parametrize("foreground,background,minimum", CONTRAST_PAIRS)
def test_brand_colour_pairs_meet_contrast(foreground: str, background: str, minimum: float) -> None:
    assert page_style.contrast_problems(SHEET, [(foreground, background, minimum)]) == []


def test_page_loads_no_fonts_or_outside_assets() -> None:
    style = SHEET.style
    assert "@font-face" not in style and "url(" not in style
    assert "<link" not in PAGE_HTML
    assert re.findall(r"<img\b[^>]*>", PAGE_HTML) == ['<img id="preview" class="preview" alt="Preview of the chosen photo" hidden>']
    markup = MARKUP
    assert "http://" not in markup and "https://" not in markup


def test_headings_are_bold_and_larger_than_body() -> None:
    tokens = SHEET.tokens()
    body = page_style.rem_to_px(tokens["--font-size-body"])
    assert page_style.rem_to_px(tokens["--font-size-h2"]) >= 1.25 * body
    assert page_style.rem_to_px(tokens["--font-size-h1"]) >= 1.25 * body
    assert int(tokens["--weight-heading"]) >= 700
    heading_rule = re.search(r"h1, h2 \{([^}]*)\}", SHEET.css)
    assert heading_rule is not None
    assert "font-weight: var(--weight-heading)" in heading_rule.group(1)
    assert "font-family: var(--font-heading)" in heading_rule.group(1)


def test_served_page_is_small() -> None:
    assert len(_call(_event())["body"].encode("utf-8")) < 100 * 1024


# ---- Controls, messages and result (plan photo-upload-branding, phase 2) ----


def test_light_tints_carry_dark_text() -> None:
    tints = {SHEET.colour(name) for name in SHEET.tokens() if re.search(r"-(20|40)$", name)}
    checked = 0
    for media, selectors, body in SHEET.rules():
        for token in re.findall(r"background(?:-color)?:\s*var\((--[\w-]+)\)", body):
            if SHEET.colour(token) in tints:
                checked += 1
                assert re.search(r"(?<![\w-])color:\s*var\(--text\)", body), f"{selectors} {media}"
                assert "--on-dark" not in body, f"{selectors} {media}"
    assert checked >= 6


def test_message_kinds_differ_beyond_colour() -> None:
    tokens = SHEET.tokens()
    glyphs = []
    for selector, glyph in MESSAGE_KINDS:
        assert re.search(r"border-left: var\(--border-width-accent\) solid var\(--[\w-]+\)", SHEET.rule(selector)), selector
        assert f"content: var({glyph})" in SHEET.rule(selector + "::before"), selector
        assert page_style.GLYPH_TOKEN.fullmatch(tokens[glyph]), glyph
        glyphs.append(tokens[glyph])
    assert len(set(glyphs)) == len(glyphs)
    # Plain status text ("Signing in…", "Loading classes…", "Sending the photo…") has no edge or glyph.
    assert "border" not in SHEET.rule(".message") and "content" not in SHEET.rule(".message")
    # Error and warning text is heavier than success and banner text.
    for selector in (".message.error", ".warning"):
        assert "font-weight: var(--weight-strong)" in SHEET.rule(selector)
    for selector in (".message.ok", ".banner"):
        assert "font-weight" not in SHEET.rule(selector)


def test_focus_is_visible() -> None:
    ring = "outline: var(--focus-width) solid var(--focus)"
    for selector in ("button:focus-visible", "select:focus-visible", "a:focus-visible", ".drop-zone input:focus-visible + label"):
        assert ring in SHEET.rule(selector), selector
    assert "outline-color: var(--focus-on-dark)" in SHEET.rule(".brand-band button:focus-visible")
    assert float(SHEET.tokens()["--focus-width"].removesuffix("px")) >= 2
    assert not re.search(r"outline:\s*(none|0)\b", SHEET.css)


def test_tap_targets_are_44px() -> None:
    for selector in ("button", ".button", "select"):
        assert "min-height: var(--tap-target)" in SHEET.rule(selector), selector
    assert page_style.rem_to_px(SHEET.tokens()["--tap-target"]) >= 44
    # font: inherit resets font-weight, so the weight must come after it.
    buttons = SHEET.rule("button")
    assert buttons.index("font: inherit") < buttons.index("font-weight: var(--weight-strong)")


def test_controls_have_hover() -> None:
    assert "background: var(--hover-bg)" in SHEET.rule("button:hover:not(:disabled)", page_style.HOVER_MEDIA)
    assert "background: var(--hover-bg)" in SHEET.rule(".button:hover", page_style.HOVER_MEDIA)
    assert "background: var(--on-dark)" in SHEET.rule(".brand-band button.secondary:hover", page_style.HOVER_MEDIA)
    assert "color: var(--brand)" in SHEET.rule(".brand-band button.secondary:hover", page_style.HOVER_MEDIA)
    for selector in ("select:hover:not(:disabled)", ".drop-zone:hover"):
        assert "border-color: var(--brand)" in SHEET.rule(selector, page_style.HOVER_MEDIA), selector
    # No hover look outside (hover: hover), where a tap would leave it on.
    assert not [selectors for media, selectors, _ in SHEET.rules() if media != page_style.HOVER_MEDIA and any(":hover" in s for s in selectors)]


def test_disabled_controls_differ_beyond_colour() -> None:
    for selector in ("button:disabled", "select:disabled"):
        rule = SHEET.rule(selector)
        assert "border-style: dashed" in rule and "cursor: not-allowed" in rule, selector
        assert "color: var(--text)" in rule
    assert "opacity" not in SHEET.css
    assert "background: var(--drag-bg)" in SHEET.rule(".drop-zone.dragging")
    assert "border-style: solid" in SHEET.rule(".drop-zone.dragging")


def test_result_text_wraps() -> None:
    for selector in (".result p", ".result li", ".result pre"):
        assert "overflow-wrap: anywhere" in SHEET.rule(selector), selector
    assert "white-space: pre-wrap" in SHEET.rule(".result pre")
    assert "text-decoration: underline" in SHEET.rule(".result a")
    # The opened/updated link is the only child of a grid message: it must not stretch.
    assert "justify-self: start" in SHEET.rule(".message > a")
    assert "border: var(--border-width) solid var(--line)" in SHEET.rule(".result")


def test_no_hidden_horizontal_overflow() -> None:
    for selector in ("html", "body", "main"):
        for media, selectors, body in SHEET.rules():
            if selector in selectors:
                assert not re.search(r"overflow(-x)?:\s*hidden", body), selector
    assert "tabindex" not in PAGE_HTML
    assert "max-width: 100%" in SHEET.rule("select") and "max-width: 100%" in SHEET.rule(".preview")


# ---- Loading, progress and retry (plan class-photo-loading, phase 3) ----

LOADING_MESSAGES = [
    "Loading classes…",
    "Still loading classes from Neon…",
    "Class list from Neon at {time}.",
    "Neon didn't answer the last refresh, so this list may be out of date.",
    "Refreshing the class list from Neon…",
    "Class list refreshed from Neon.",
    "The class list was refreshed less than a minute ago, so this is that list. Try again in a minute.",
    "Neon didn't answer, so the class list wasn't refreshed. The list shown is the last one read.",
    "Preparing the photo…",
    "Sending the photo…",
    "Waiting for the server to check it and open the pull request…",
    "Waiting for the server to check it and plan the pull request…",
    "{seconds} s",
    "The server didn't confirm the result in time. A pull request may or may not have been opened on GitHub. "
    "Submitting the same class again is safe: it updates the same pull request instead of opening a second one.",
    "The server didn't answer in time. This is a dry run, so nothing was opened on GitHub. Try again.",
]


def _tag(element_id: str) -> str:
    """The opening tag of the element with this id."""
    match = re.search(rf'<[a-z]+\b[^>]*\bid="{element_id}"[^>]*>', MARKUP)
    assert match is not None, element_id
    return match.group(0)


def _script() -> str:
    match = re.search(r'<script nonce="__CSP_NONCE__">(.*?)</script>', PAGE_HTML, re.S)
    assert match is not None
    return match.group(1)


def test_class_field_has_busy_indicator_and_retry() -> None:
    progress = _tag("class-progress")
    assert progress.startswith("<progress ") and 'aria-label="Loading classes"' in progress and " hidden" in progress
    assert "value=" not in progress  # no value: the browser's indeterminate bar
    assert '<button type="button" id="class-retry" hidden>Try again</button>' in MARKUP
    freshness = _tag("class-freshness")
    assert "role=" not in freshness and "aria-live" not in freshness
    assert 'aria-describedby="class-status class-freshness"' in _tag("class-select")
    assert 'role="status" aria-live="polite"' in _tag("class-status")


def test_submit_has_progress_and_silent_elapsed() -> None:
    progress = _tag("submit-progress")
    assert progress.startswith("<progress ") and 'aria-label="Submitting"' in progress and " hidden" in progress
    elapsed = _tag("submit-elapsed")
    assert 'aria-hidden="true"' in elapsed and "role=" not in elapsed and "aria-live" not in elapsed
    assert 'role="status" aria-live="polite"' in _tag("submit-status")


@pytest.mark.parametrize("message", LOADING_MESSAGES)
def test_loading_and_progress_messages_are_in_the_page(message: str) -> None:
    assert f'"{message}"' in _script()


def test_class_field_has_refresh_button() -> None:
    assert '<button type="button" id="class-refresh" hidden>Refresh class list</button>' in MARKUP
    assert "aria-label" not in _tag("class-refresh")  # its name is its text
    assert '"/classes?refresh=1"' in _script()


def test_busy_indicator_uses_tokens() -> None:
    busy = SHEET.rule(".busy")
    assert "height: var(--progress-height)" in busy
    assert "accent-color: var(--progress-fill)" in busy
    assert "width: 100%" in busy
    # .busy's display: block can't show a hidden bar: the global rule wins.
    assert "display: none !important" in SHEET.rule("[hidden]")
    assert "@keyframes" not in SHEET.css and "animation" not in SHEET.css


def test_disabled_photo_button_differs_beyond_colour() -> None:
    rule = SHEET.rule(".drop-zone input:disabled + label")
    assert "border-style: dashed" in rule and "cursor: not-allowed" in rule
    assert "background: var(--disabled-bg)" in rule and "color: var(--text)" in rule


def test_busy_buttons_keep_the_disabled_look() -> None:
    # Busy buttons use aria-disabled so they keep focus; they look like disabled ones.
    assert SHEET.rule('button[aria-disabled="true"]') == SHEET.rule("button:disabled")
    hover = SHEET.rule('button[aria-disabled="true"]:hover', page_style.HOVER_MEDIA)
    assert "background: var(--disabled-bg)" in hover and "border-color: var(--control-border)" in hover
    assert "margin-top: var(--space-3)" in SHEET.rule("#class-retry") and "margin-top: var(--space-3)" in SHEET.rule("#class-refresh")


def test_page_sends_submission_to_its_own_origin() -> None:
    script = _script()
    assert script.count("new XMLHttpRequest()") == 1
    assert re.findall(r"\.open\(([^)]*)\)", script) == ['"POST", config.pageUrl + path']
    assert "xhr.withCredentials = false;" in script
    # The only other request the page makes is the sign-in's token exchange.
    assert re.findall(r"\bfetch\(([^,]*),", script) == ['"https://" + config.authDomain + "/oauth2/token"', "config.pageUrl + path"]
