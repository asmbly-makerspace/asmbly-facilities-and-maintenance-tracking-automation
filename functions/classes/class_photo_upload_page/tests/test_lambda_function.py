import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from functions.classes.class_photo_upload_api import lambda_function as api
from functions.classes.class_photo_upload_api import photo_checks
from functions.classes.class_photo_upload_page import lambda_function

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_HTML = (Path(lambda_function.__file__).parent / "page.html").read_text(encoding="utf-8")

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

STYLE_BLOCK = re.compile(r'<style nonce="__CSP_NONCE__">(.*?)</style>', re.S)
SCRIPT_BLOCKS = re.compile(r"<script\b.*?</script>", re.S)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
TOKEN = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
VAR_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])")
PURE_WHITE_OR_BLACK = re.compile(r"(?<![\w-])(white|black)(?![\w-])", re.I)
# Outside :root a declaration's value may hold only var() references, 0, 100% and these
# words: CSS keywords that are not colours, and the header's grid-area names. Anything
# else (a named colour such as whitesmoke, a system colour such as Highlight, a length)
# fails test_styles_use_tokens_only. Add a keyword here only if it can't carry a value.
ALLOWED_VALUE_WORDS = {
    "absolute", "auto", "block", "border-box", "break-word", "center", "currentColor", "dashed", "grid",
    "hidden", "important", "inherit", "inline-block", "none", "not-allowed", "nowrap", "pointer", "pre-wrap",
    "rect", "solid", "transparent",
}
GRID_AREAS = {"logo", "title", "sign-out"}
# Token values: a #rrggbb colour, a reference to another token, a length or unitless
# number, or (for --font-* stacks only) a list of family names.
TOKEN_VALUE = re.compile(r"#[0-9a-fA-F]{6}|var\(--[\w-]+\)|\d*\.?\d+(?:rem|px|fr)?")
FONT_STACK = re.compile(r'(?:"[\w ]+"|[\w-]+)(?:, (?:"[\w ]+"|[\w-]+))*')
# Tokens defined for later phases or used outside var(): see the phase 1 hand-off.
RESERVED_TOKENS = {
    "--asmbly-purple-80": "the guide's 80% tint, for phase 2's hover state",
    "--tap-target": "phase 2's control height",
    "--breakpoint-wide": "the @media literal repeats it (test_breakpoint_matches_token)",
}
# Literal values two tokens of different kinds may share (plan Design rule 3): a new
# shared literal fails test_tokens_are_defined_once until it is listed here with a reason.
SHARED_LITERALS = {
    "1px": {"--border-width", "--visually-hidden-size"},  # a hairline border; the clip box of hidden text
    "2px": {"--border-width-strong", "--focus-offset"},  # a strong border; the gap before the focus ring
    "1rem": {"--font-size-body", "--space-4"},  # body text size; a spacing step
}
# The only attributes the inline SVGs may carry; fill only as a same-page paint server.
SVG_ATTRIBUTES = {
    "aria-hidden", "aria-label", "class", "d", "fill", "focusable", "height", "id", "patternUnits",
    "preserveAspectRatio", "role", "viewBox", "width",
}
MEDIA_RULE = re.compile(r"@media\s*\(min-width:\s*([^)]+)\)")
ROOT_FONT_PX = 16

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
]


def _style() -> str:
    """The text of the page's one <style> block."""
    match = STYLE_BLOCK.search(PAGE_HTML)
    assert match is not None
    return match.group(1)


def _css() -> str:
    """The stylesheet without comments."""
    return CSS_COMMENT.sub("", _style())


def _root_block() -> str:
    """The body of the :root rule, which must be the stylesheet's only :root and its first rule."""
    css = _css().strip()
    assert css.startswith(":root {"), "the token block must be the first rule"
    assert css.count(":root") == 1, "there must be one token block"
    return css[len(":root {") : css.index("}")]


def _rules_after_root() -> str:
    """Every rule after the token block."""
    css = _css().strip()
    return css[css.index("}") + 1 :]


def _tokens() -> dict[str, str]:
    """The custom properties the token block defines, by name."""
    return {name: value.strip() for name, value in TOKEN.findall(_root_block())}


def _colour(name: str) -> str:
    """A token's colour as lower-case #rrggbb, following var() references."""
    value = _tokens()[name]
    reference = VAR_REFERENCE.fullmatch(value)
    if reference:
        return _colour(reference.group(1))
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), f"{name} is not a #rrggbb colour: {value}"
    return value.lower()


def _channels(colour: str) -> list[int]:
    return [int(colour[index : index + 2], 16) for index in (1, 3, 5)]


def _mix(a: str, b: str, p: float) -> str:
    """p × a + (1 − p) × b per sRGB channel, rounded, as #rrggbb."""
    mixed = [round(p * x + (1 - p) * y) for x, y in zip(_channels(a), _channels(b))]
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _luminance(colour: str) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _channels(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    """The WCAG 2.1 contrast ratio of two #rrggbb colours."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _declaration_values(css: str) -> list[str]:
    """The value of every declaration in every rule body (not selectors, not @media conditions)."""
    values = []
    for body in re.findall(r"\{([^{}]*)\}", css):
        for declaration in body.split(";"):
            if ":" in declaration:
                values.append(declaration.split(":", 1)[1].strip())
    return values


def _markup() -> str:
    """The page without its <style> and <script> blocks."""
    return SCRIPT_BLOCKS.sub("", STYLE_BLOCK.sub("", PAGE_HTML))


def _rem_to_px(value: str) -> float:
    assert value.endswith("rem"), value
    return float(value.removesuffix("rem")) * ROOT_FONT_PX


def test_page_shows_official_logo_in_header() -> None:
    logo = '<svg class="logo" role="img" aria-label="Asmbly Makerspace"'

    assert PAGE_HTML.count(logo) == 1
    logo_at = PAGE_HTML.index(logo)
    assert logo_at < PAGE_HTML.index('id="dry-run-banner"')
    assert logo_at < PAGE_HTML.index('id="signing-in"')
    header = PAGE_HTML[PAGE_HTML.index('<header class="brand-band">') : PAGE_HTML.index("</header>")]
    assert logo in header and "<h1>Class photo upload</h1>" in header and 'id="sign-out"' in header
    svg = PAGE_HTML[logo_at : PAGE_HTML.index("</svg>", logo_at)]
    assert 'viewBox="0 0 443.61 122.16"' in svg
    assert 'd="m122.16,77.71V0H0v44.44h20.85' in svg  # the official icon path
    assert svg.count("<path ") == 17
    assert "fill=" not in svg and "xmlns" not in svg


def test_logo_meets_brand_minimum() -> None:
    assert _rem_to_px(_tokens()["--logo-height"]) >= 50
    logo_rule = re.search(r"\.logo \{([^}]*)\}", _css())
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
    fills = dict(re.findall(r"\.pattern \.([\w-]+) \{ fill: var\(--([\w-]+)\); \}", _css()))
    assert shape_classes and shape_classes <= set(fills)
    # Each colour class is filled with the token of the same name (.pattern .lasers -> --lasers).
    assert all(fills[name] == name for name in shape_classes), fills


def test_brand_tokens_match_the_guide() -> None:
    tokens = _tokens()
    for name, value in BRAND_COLOURS.items():
        assert tokens[name].lower() == value.lower(), name


@pytest.mark.parametrize("name,first,second,share", DERIVED_COLOURS)
def test_derived_tokens_follow_the_formula(name: str, first: str, second: str, share: float) -> None:
    assert _colour(name) == _mix(_colour(first), _colour(second), share)


def test_styles_use_tokens_only() -> None:
    rules = _rules_after_root()

    assert not HEX_COLOUR.search(rules)
    assert not re.search(r"\b(rgba?|hsla?)\(", rules)
    values = _declaration_values(rules)
    assert len(values) > 100, "the declaration parser found too few declarations"
    for value in values:
        literal = VAR_REFERENCE.sub("", value)
        for area_names in re.findall(r'"([^"]*)"', literal):
            assert set(area_names.split()) <= GRID_AREAS, f"unexpected string in: {value}"
        literal = re.sub(r'"[^"]*"', "", literal)
        numbers = re.findall(r"\d*\.?\d+(?:[a-z%]+)?", literal)
        assert all(number in ("0", "100%") for number in numbers), f"magic value in: {value}"
        words = set(re.findall(r"[A-Za-z][\w-]*", literal))
        assert words <= ALLOWED_VALUE_WORDS | GRID_AREAS, f"literal {sorted(words - ALLOWED_VALUE_WORDS - GRID_AREAS)} in: {value}"
    for match in re.finditer(r"font(-family)?:\s*([^;}]+)", rules):
        if match.group(1):
            assert re.fullmatch(r"var\(--font-[\w-]+\)", match.group(2).strip()), match.group(0)
        else:
            assert match.group(2).strip() == "inherit", match.group(0)
    markup = _markup()
    for forbidden in ('fill="#', 'stroke="#', "style=", "color="):
        assert forbidden not in markup
    for svg in re.findall(r"<svg\b.*?</svg>", markup, re.S):
        assert "<style" not in svg
        for name, value in re.findall(r'([\w:-]+)="([^"]*)"', svg):
            assert name in SVG_ATTRIBUTES, f"SVG attribute {name}"
            if name == "fill":
                assert re.fullmatch(r"url\(#[\w-]+\)", value), f'fill="{value}"'


def test_token_block_holds_only_tokens() -> None:
    assert _root_block().strip().endswith(";"), "every token ends with a semicolon"
    for declaration in _root_block().split(";"):
        if not declaration.strip():
            continue
        name, value = (part.strip() for part in declaration.split(":", 1))
        if name == "color-scheme":
            assert value == "light"
            continue
        assert name.startswith("--"), f"{name} in the token block"
        if name.startswith("--font-") and not name.startswith("--font-size"):
            assert FONT_STACK.fullmatch(value), f"{name}: {value}"
        else:
            assert TOKEN_VALUE.fullmatch(value), f"{name}: {value}"


def test_every_token_is_used() -> None:
    used = set(VAR_REFERENCE.findall(_css()))

    unused = set(_tokens()) - used
    assert unused == set(RESERVED_TOKENS), f"unused tokens: {sorted(unused - set(RESERVED_TOKENS))}"


def test_breakpoint_matches_token() -> None:
    conditions = MEDIA_RULE.findall(_css())

    assert conditions == [_tokens()["--breakpoint-wide"]]
    # Any other media query (prefers-reduced-motion, say) carries no number of its own.
    for query in re.findall(r"@media([^{]*)\{", _css()):
        assert MEDIA_RULE.fullmatch("@media" + query.rstrip()) or not re.search(r"\d", query), query


def test_tokens_are_defined_once() -> None:
    definitions = TOKEN.findall(_root_block())
    names = [name for name, _ in definitions]
    assert len(names) == len(set(names))

    literals = [value.strip() for _, value in definitions if not VAR_REFERENCE.fullmatch(value.strip())]
    colours = [value.lower() for value in literals if HEX_COLOUR.fullmatch(value)]
    assert len(colours) == len(set(colours))
    stacks = [value for value in literals if "," in value]
    assert len(stacks) == len(set(stacks))
    # Every other literal (a length, a number) is written once, apart from SHARED_LITERALS.
    by_value: dict[str, set[str]] = {}
    for name, value in definitions:
        if not VAR_REFERENCE.fullmatch(value.strip()):
            by_value.setdefault(value.strip(), set()).add(name)
    shared = {value: names for value, names in by_value.items() if len(names) > 1}
    assert shared == SHARED_LITERALS, shared
    steps = [value.strip() for name, value in definitions if re.fullmatch(r"--space-\d+", name)]
    assert len(steps) == len(set(steps)) and len(steps) >= 6


def test_every_token_used_is_defined() -> None:
    used = set(VAR_REFERENCE.findall(_css()))

    assert used
    assert used <= set(_tokens())


def test_page_has_no_pure_white_or_black() -> None:
    for colour in ("#fff", "#000"):
        assert colour not in PAGE_HTML.lower()
    assert not PURE_WHITE_OR_BLACK.search(_css())
    ceramics = re.findall(r"[^{}]+\{[^}]*var\(--ceramics\)[^}]*\}", _rules_after_root())
    assert ceramics and all(rule.strip().startswith(".pattern ") for rule in ceramics)
    assert [name for name, value in _tokens().items() if value == "var(--ceramics)"] == []


@pytest.mark.parametrize("foreground,background,minimum", CONTRAST_PAIRS)
def test_brand_colour_pairs_meet_contrast(foreground: str, background: str, minimum: float) -> None:
    assert _contrast(_colour(foreground), _colour(background)) >= minimum


def test_page_loads_no_fonts_or_outside_assets() -> None:
    style = _style()
    assert "@font-face" not in style and "url(" not in style
    assert "<link" not in PAGE_HTML
    assert re.findall(r"<img\b[^>]*>", PAGE_HTML) == ['<img id="preview" class="preview" alt="Preview of the chosen photo" hidden>']
    markup = _markup()
    assert "http://" not in markup and "https://" not in markup


def test_headings_are_bold_and_larger_than_body() -> None:
    tokens = _tokens()
    body = _rem_to_px(tokens["--font-size-body"])
    assert _rem_to_px(tokens["--font-size-h2"]) >= 1.25 * body
    assert _rem_to_px(tokens["--font-size-h1"]) >= 1.25 * body
    assert int(tokens["--weight-heading"]) >= 700
    heading_rule = re.search(r"h1, h2 \{([^}]*)\}", _css())
    assert heading_rule is not None
    assert "font-weight: var(--weight-heading)" in heading_rule.group(1)
    assert "font-family: var(--font-heading)" in heading_rule.group(1)


def test_served_page_is_small() -> None:
    assert len(_call(_event())["body"].encode("utf-8")) < 100 * 1024
