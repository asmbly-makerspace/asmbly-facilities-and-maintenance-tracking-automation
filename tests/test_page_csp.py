"""Tests of tests/page_csp.py, the CSP checks shared by the HTML pages' tests (story #139).

Each fault is shown on a small page built here, so these tests don't depend on either
page.
"""
import ast
import pathlib

import pytest

from tests import page_csp

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
    ],
    ids=["style-without-nonce", "script-other-nonce", "style-src-other-nonce", "marker-left", "unsafe-inline", "no-script", "no-script-src", "style-attribute"],
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
