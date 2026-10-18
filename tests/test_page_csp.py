"""Tests of tests/page_csp.py, the CSP checks shared by the HTML pages' tests (story #139),
and the registry of public pages that runs those checks on every page.

Each fault is shown on a small page built here, so the tests of the checks don't depend
on either page. The registry tests at the end run the checks on what each page serves.
"""
import ast
import pathlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as kiln
from functions.classes.class_photo_upload_page import lambda_function as photo
from tests import capture_page_pins, page_csp

ROOT = pathlib.Path(__file__).resolve().parent.parent

AUTH_DOMAIN = "asmbly-staff.auth.us-east-2.amazoncognito.com"
# The class photo upload page's policy for the nonce "n0nce", as sent on stage 07b9b79.
PHOTO_POLICY = (
    "default-src 'none'; script-src 'nonce-n0nce'; style-src 'nonce-n0nce'; img-src blob:; "
    f"connect-src 'self' https://{AUTH_DOMAIN}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

HASH_STYLE = "\n  a { color: red; }\n"
HASH_BODY = f"<html><head><style>{HASH_STYLE}</style></head><body><p>Hi</p></body></html>"


def _hash_policy(style_src: str, extra: str = "") -> str:
    return f"default-src 'none'; {extra}style-src {style_src}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


HASH_POLICY = _hash_policy(page_csp.sha256_source(HASH_STYLE))

NONCE_BODY = (
    '<html><head><style nonce="n0nce">a { }</style></head><body>'
    '<script type="application/json" id="c">{}</script>'
    '<script nonce="n0nce">for (let i = 0; i < n; i++) { x.onload = f; }</script>'
    "</body></html>"
)


def test_sha256_source_matches_a_known_digest() -> None:
    assert page_csp.sha256_source("") == "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='"


def test_directives_reads_each_directive_once() -> None:
    parsed = page_csp.directives(PHOTO_POLICY)

    assert len(parsed) == 8
    assert parsed["img-src"] == "blob:"
    assert parsed["connect-src"] == f"'self' https://{AUTH_DOMAIN}"
    with pytest.raises(ValueError):
        page_csp.directives("default-src 'none'; style-src 'self'; style-src *")


def test_nonce_reads_the_script_nonce() -> None:
    assert page_csp.nonce(PHOTO_POLICY) == "n0nce"
    with pytest.raises(ValueError):
        page_csp.nonce("default-src 'none'; style-src 'nonce-n0nce'")
    with pytest.raises(ValueError):
        page_csp.nonce("default-src 'none'; script-src 'nonce-a' 'nonce-b'")


def test_style_hash_problems_passes_a_matching_page() -> None:
    assert page_csp.style_hash_problems(HASH_POLICY, HASH_BODY) == []


@pytest.mark.parametrize(
    "policy, body, fault",
    [
        (_hash_policy(page_csp.sha256_source("other")), HASH_BODY, "not the hash"),
        (HASH_POLICY, HASH_BODY.replace("<p>Hi</p>", "<style>b { }</style>"), "found 2 <style> tags"),
        (HASH_POLICY, "<html><body></body></html>", "found 0 <style> tags"),
        (HASH_POLICY, HASH_BODY.replace("<style>", '<style media="print">'), "found 1 <style> tags and 0 blocks"),
        (HASH_POLICY, HASH_BODY.replace("<p>Hi</p>", "<script>run()</script>"), "has a <script>"),
        (HASH_POLICY, HASH_BODY.replace("<p>Hi</p>", '<p style="color: red">Hi</p>'), "inline style="),
        (HASH_POLICY, HASH_BODY.replace("<p>Hi</p>", '<p onclick="run()">Hi</p>'), "inline onclick="),
        (_hash_policy(page_csp.sha256_source(HASH_STYLE), "img-src 'unsafe-inline'; "), HASH_BODY, "'unsafe-inline'"),
        (_hash_policy(page_csp.sha256_source(HASH_STYLE), "script-src 'self'; "), HASH_BODY, "script-src"),
        (HASH_POLICY.replace("default-src 'none'", "default-src *"), HASH_BODY, "default-src"),
    ],
    ids=["wrong-hash", "two-styles", "no-style", "style-with-attribute", "script", "style-attribute", "onclick", "unsafe-inline", "script-src", "default-src"],
)
def test_style_hash_problems_reports_each_fault(policy: str, body: str, fault: str) -> None:
    problems = page_csp.style_hash_problems(policy, body)

    assert len(problems) == 1, problems
    assert fault in problems[0]


def test_style_hash_problems_reports_a_repeated_directive() -> None:
    problems = page_csp.style_hash_problems(HASH_POLICY + "; style-src *", HASH_BODY)

    assert problems == ["the policy can't be read: style-src is repeated"]


def test_style_hash_problems_ignores_escaped_text() -> None:
    """Text from outside is escaped, so a task name that reads like a tag is not one."""
    body = HASH_BODY.replace("<p>Hi</p>", "<p>&lt;script&gt; &lt;p style=&quot;x&quot;&gt; style= onclick=</p>")

    assert page_csp.style_hash_problems(HASH_POLICY, body) == []


def test_nonce_problems_passes_a_matching_page() -> None:
    assert page_csp.nonce_problems(PHOTO_POLICY, NONCE_BODY) == []


@pytest.mark.parametrize(
    "policy, body, fault",
    [
        (PHOTO_POLICY, NONCE_BODY.replace('<style nonce="n0nce">', "<style>"), "<style> tag has no nonce"),
        (PHOTO_POLICY, NONCE_BODY.replace('<script nonce="n0nce">', '<script nonce="other">'), "<script> tag has no nonce"),
        (PHOTO_POLICY.replace("style-src 'nonce-n0nce'", "style-src 'nonce-other'"), NONCE_BODY, "style-src"),
        (PHOTO_POLICY, NONCE_BODY + "<!-- __CSP_NONCE__ -->", "__CSP_NONCE__"),
        (PHOTO_POLICY.replace("img-src blob:", "img-src blob: 'unsafe-inline'"), NONCE_BODY, "'unsafe-inline'"),
        (PHOTO_POLICY, NONCE_BODY.replace('<script nonce="n0nce">', '<script type="application/json">'), "no executable <script>"),
        (PHOTO_POLICY.replace("script-src 'nonce-n0nce'; ", ""), NONCE_BODY, "script-src must be exactly one nonce"),
        (PHOTO_POLICY, NONCE_BODY.replace("</body>", '<div style="color: red"></div></body>'), "inline style="),
        (PHOTO_POLICY, NONCE_BODY.replace("</body>", '<script nonce="n0nce" src="https://cdn.example/x.js"></script></body>'), "src="),
    ],
    ids=["style-without-nonce", "script-other-nonce", "style-src-other-nonce", "marker-left", "unsafe-inline", "no-script", "no-script-src", "style-attribute", "script-src-attribute"],
)
def test_nonce_problems_reports_each_fault(policy: str, body: str, fault: str) -> None:
    problems = page_csp.nonce_problems(policy, body)

    assert problems, "no problem reported"
    assert any(fault in problem for problem in problems), problems


def test_page_csp_does_not_import_the_helper() -> None:
    """The checks stay independent of common.csp, so a bug there can't hide in its own check."""
    tree = ast.parse(pathlib.Path(page_csp.__file__).read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] != "common", name


# --- The public pages ---------------------------------------------------------------


@dataclass(frozen=True)
class PublicPage:
    """One HTML page a visitor's browser opens."""

    folder: str  # the function's folder, from the repository root
    policy: str  # "hash" (no script) or "nonce" (a script)
    responses: Callable[[], list[dict[str, Any]]]  # served responses that carry the page


A_TASK = {"id": "abc123", "custom_id": "KO-1", "name": "Customer Z", "date_created": "1704067200000"}


def _kiln_responses() -> list[dict[str, Any]]:
    """What the handler sends for the empty list, a list with a drop-off, and the error page.

    lambda_handler returns exactly these through html_response, so ClickUp needn't be
    mocked; the kiln tests' test_csp_style_hash_matches_served_style covers the handler.
    """
    return [
        kiln.html_response(200, kiln.generate_html_page([])),
        kiln.html_response(200, kiln.generate_html_page([dict(A_TASK)])),
        kiln.html_response(500, kiln.generate_error_page()),
    ]


def _photo_responses() -> list[dict[str, Any]]:
    """Two handler responses for the same request, with the page's environment set."""
    env = {
        "STAFF_AUTH_DOMAIN": "asmbly-staff.auth.us-east-2.amazoncognito.com",
        "CLASS_PHOTO_APP_CLIENT_ID": "fakeappclientid123",
        "CLASS_PHOTO_DRY_RUN": "false",
    }
    event = {"requestContext": {"domainName": "facilities.asmbly.org", "path": "/class-photo-upload"}}
    with patch.dict("os.environ", env, clear=True):
        responses = [photo.lambda_handler(event, None), photo.lambda_handler(event, None)]
    for response in responses:
        assert response["statusCode"] == 200
    return responses


# Every public HTML page. A new page adds itself here; test_every_html_page_is_registered
# fails until it does. A page's plain error pages (csp.strict_policy) aren't checked here:
# pin their policy in the page's own tests.
PUBLIC_PAGES: dict[str, PublicPage] = {
    "kiln": PublicPage("functions/ceramics/kiln_dropoff_recent_entries_viewer", "hash", _kiln_responses),
    "photo": PublicPage("functions/classes/class_photo_upload_page", "nonce", _photo_responses),
}
HASH_PAGES = [name for name, page in PUBLIC_PAGES.items() if page.policy == "hash"]
NONCE_PAGES = [name for name, page in PUBLIC_PAGES.items() if page.policy == "nonce"]

# A CSP directive name at the start of a string or after a ';' or a space, then a space:
# how a policy written by hand looks. A (directive, sources) pair for csp.py has no space.
HAND_BUILT_CSP = re.compile(
    r"(?:^|[;\s])(default-src|script-src|style-src|img-src|connect-src|base-uri|form-action|frame-ancestors)\s"
)


def _folder(path: pathlib.Path) -> str:
    return path.parent.relative_to(ROOT).as_posix()


def test_every_html_page_is_registered() -> None:
    """Story #139 criterion 3: every function that serves HTML is in PUBLIC_PAGES and in
    capture_page_pins.PAGES, so a new page can't skip the shared checks.

    A page is found by its page.html, or by the text text/html in its lambda_function.py.
    A page whose Content-Type comes from elsewhere (a helper constant, a sibling module)
    and has no page.html isn't found: register it by hand.
    """
    registered = {page.folder for page in PUBLIC_PAGES.values()}
    with_page_html = {_folder(path) for path in ROOT.glob("functions/*/*/page.html")}
    serving_html = {
        _folder(path)
        for path in ROOT.glob("functions/*/*/lambda_function.py")
        if "text/html" in path.read_text(encoding="utf-8")
    }

    assert with_page_html == registered
    assert serving_html == registered
    assert set(PUBLIC_PAGES) == set(capture_page_pins.PAGES)
    for name, page in PUBLIC_PAGES.items():
        assert page.folder == capture_page_pins.PAGES[name][0], name
        assert page.policy in {"hash", "nonce"}, name


@pytest.mark.parametrize("name", HASH_PAGES)
def test_hash_pages_allow_only_their_served_style(name: str) -> None:
    """Story #139 criterion 3: each hash page's style-src is the hash of the <style> it serves."""
    responses = PUBLIC_PAGES[name].responses()

    assert responses
    for response in responses:
        policy = response["headers"]["Content-Security-Policy"]
        assert page_csp.style_hash_problems(policy, response["body"]) == []


@pytest.mark.parametrize("name", NONCE_PAGES)
def test_nonce_pages_put_a_fresh_nonce_on_style_and_script(name: str) -> None:
    """Story #139 criterion 4: each response's nonce is on its header, <style> and <script>,
    and no two responses share a nonce."""
    responses = PUBLIC_PAGES[name].responses()

    assert len(responses) >= 2
    nonces = []
    for response in responses:
        policy = response["headers"]["Content-Security-Policy"]
        assert page_csp.nonce_problems(policy, response["body"]) == []
        nonces.append(page_csp.nonce(policy))
    assert len(set(nonces)) == len(nonces)


def _hand_built_csp_strings(source: str) -> list[str]:
    """Every string constant in the source, f-string parts included, that reads like a
    policy written by hand. Docstrings (expression statements) are skipped."""
    tree = ast.parse(source)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and HAND_BUILT_CSP.search(node.value)
    ]


def test_hand_built_csp_check_finds_a_policy_string() -> None:
    """The check below finds the kind of string the functions used to write, and skips a
    docstring or a (directive, sources) pair."""
    before = (
        '"""default-src \'none\'; style-src in a docstring."""\n'
        'POLICY = f"default-src \'none\'; style-src {source}; base-uri \'none\'"\n'
        'ERROR = "default-src \'none\'; base-uri \'none\'"\n'
        'PAIR = ("img-src", "blob:")\n'
    )

    assert set(_hand_built_csp_strings(before)) == {
        "default-src 'none'; style-src ",  # the f-string's parts
        "; base-uri 'none'",
        "default-src 'none'; base-uri 'none'",
    }


def test_no_function_builds_a_csp_by_hand() -> None:
    """Story #139 criterion 1: no function's code holds a CSP directive string, and every
    registered page imports csp from common."""
    for path in sorted(ROOT.glob("functions/**/*.py")):
        if "tests" in path.relative_to(ROOT).parts:
            continue
        found = _hand_built_csp_strings(path.read_text(encoding="utf-8"))
        assert found == [], (path.relative_to(ROOT).as_posix(), found)

    for name, page in PUBLIC_PAGES.items():
        tree = ast.parse((ROOT / page.folder / "lambda_function.py").read_text(encoding="utf-8"))
        imports_csp = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "common"
            and any(alias.name == "csp" for alias in node.names)
            for node in ast.walk(tree)
        )
        assert imports_csp, name
