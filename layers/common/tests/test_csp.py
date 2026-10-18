"""Tests of common.csp: the Content-Security-Policy headers the HTML pages send (story #139).

Pytest and the standard library only, so the layer's tests stand alone. Each expected hash
is computed here with hashlib, not taken from the module. The tests that compare the
module with what the pages send are next to each page's function.
"""
import ast
import base64
import hashlib
import os
import re
import subprocess
import sys

import pytest

# Add the python directory to the path to allow common module imports
LAYER_PYTHON = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python'))
sys.path.insert(0, LAYER_PYTHON)

from common import csp

# The three policies the pages sent on stage 07b9b79, before story #139.
ERROR_PAGE_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
AUTH_DOMAIN = "asmbly-staff.auth.us-east-2.amazoncognito.com"
PHOTO_ALLOW = [("img-src", "blob:"), ("connect-src", f"'self' https://{AUTH_DOMAIN}")]
PHOTO_POLICY = (
    "default-src 'none'; script-src 'nonce-n0nce'; style-src 'nonce-n0nce'; img-src blob:; "
    f"connect-src 'self' https://{AUTH_DOMAIN}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def test_strict_policy_alone_is_the_error_page_policy() -> None:
    assert csp.strict_policy() == ERROR_PAGE_POLICY


def test_hash_policy_is_the_kiln_shape() -> None:
    page = "<html><style>\n  a { }\n</style></html>"
    style_hash = _sha256("\n  a { }\n")

    assert csp.hash_policy(page) == (
        f"default-src 'none'; style-src {style_hash}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def test_nonce_policy_is_the_photo_shape() -> None:
    assert csp.nonce_policy("n0nce", PHOTO_ALLOW) == PHOTO_POLICY


@pytest.mark.parametrize(
    "page",
    [
        "<html><body></body></html>",
        "<style>a { }</style><style>b { }</style>",
        '<style nonce="x">a { }</style>',
    ],
)
def test_style_hash_source_needs_exactly_one_style_block(page: str) -> None:
    with pytest.raises(ValueError, match="exactly one <style> block"):
        csp.style_hash_source(page)


def test_style_hash_covers_the_text_exactly() -> None:
    assert csp.style_hash_source("<style>a{}</style>") == _sha256("a{}")
    assert csp.style_hash_source("<style> a{}</style>") == _sha256(" a{}")
    assert csp.style_hash_source("<style>a{}</style>") != csp.style_hash_source("<style> a{}</style>")
    assert csp.sha256_source("a{}") == _sha256("a{}")


def test_strict_policy_keeps_the_order_given() -> None:
    forward = csp.strict_policy([("style-src", "x"), ("img-src", "y")])
    reverse = csp.strict_policy([("img-src", "y"), ("style-src", "x")])

    assert forward == "default-src 'none'; style-src x; img-src y; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    assert reverse == "default-src 'none'; img-src y; style-src x; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


@pytest.mark.parametrize(
    "allow",
    [
        [("default-src", "*")],
        [("base-uri", "*")],
        [("form-action", "*")],
        [("frame-ancestors", "*")],
        [("Style-Src", "x")],
        [("", "x")],
        [("img src", "x")],
        [("img-src\n", "x")],
        [("img-src", "x"), ("img-src", "y")],
    ],
)
def test_strict_policy_refuses_fixed_repeated_or_bad_names(allow: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError):
        csp.strict_policy(allow)


@pytest.mark.parametrize("sources", ["", "  ", "'self'; script-src *", "a, b", "a\r\nX-Injected: 1", "a\nb"])
def test_strict_policy_refuses_sources_that_could_break_the_header(sources: str) -> None:
    with pytest.raises(ValueError) as raised:
        csp.strict_policy([("img-src", sources)])

    if sources.strip():
        assert sources not in str(raised.value)


@pytest.mark.parametrize("nonce", ["", "a b", "abc'", "a;b", "a\nb", "abc\n"])
def test_nonce_policy_refuses_a_nonce_that_is_not_base64(nonce: str) -> None:
    with pytest.raises(ValueError):
        csp.nonce_policy(nonce)


def test_new_nonce_is_fresh_and_url_safe() -> None:
    first, second = csp.new_nonce(), csp.new_nonce()

    assert first != second
    for nonce in (first, second):
        assert re.fullmatch(r"[A-Za-z0-9_-]{22}", nonce), nonce


def test_csp_imports_only_the_standard_library() -> None:
    """Story #139: the shared module imports only the Python standard library, like brand.py."""
    with open(csp.__file__, encoding="utf-8") as source:
        tree = ast.parse(source.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, name


def test_importing_csp_loads_no_third_party_module() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {LAYER_PYTHON!r})\n"
        "import common.csp\n"
        "print(any(name in sys.modules for name in ('boto3', 'botocore', 'requests')))\n"
    )

    result = subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True)

    assert result.stdout.strip() == "False"
