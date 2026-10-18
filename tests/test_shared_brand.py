"""Tests that span both HTML pages and common.brand, the brand tokens and logo they share (story #138).

The module's own tests are in layers/common/tests/test_brand.py; each page's pins are in its
own test file.
"""
import base64
import hashlib
import importlib
import json
import pathlib
import re
import subprocess
import sys
from unittest.mock import patch

import pytest

from common import brand
from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as kiln
from functions.classes.class_photo_upload_page import lambda_function as photo
from tests import capture_page_pins, page_style

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = {name: ROOT / folder / "tests" / "fixtures" for name, (folder, _) in capture_page_pins.PAGES.items()}
PINNED: dict[str, dict[str, str]] = {
    name: json.loads((folder / "pinned_tokens.json").read_text(encoding="utf-8")) for name, folder in FIXTURES.items()
}
# The same name and value on both pages, but what a page uses a colour for and which glyph
# its error shows, so each page keeps them as its own (the plan's README, Decision 4).
PAGE_ROLE_TOKENS = {"--page-bg", "--text", "--glyph-error"}


def _served_sheets() -> dict[str, page_style.Stylesheet]:
    """Each page's served shell's stylesheet, keyed "kiln" and "photo"."""
    return capture_page_pins.served_sheets()


def _served_shells() -> dict[str, str]:
    return {"kiln": kiln.PAGE_TEMPLATE, "photo": photo._template()}


def _brand_tokens() -> dict[str, str]:
    return page_style.Stylesheet(":root { " + brand.BRAND_TOKENS + " }").tokens()


def _raw_pages() -> dict[str, str]:
    """Each page's page.html as committed, before the shared tokens and logo are filled in."""
    return {
        name: (ROOT / folder / "page.html").read_text(encoding="utf-8")
        for name, (folder, _) in capture_page_pins.PAGES.items()
    }


def _raw_sheets() -> dict[str, page_style.Stylesheet]:
    """Each raw page.html's stylesheet. It parses because the token marker is a CSS comment."""
    return {
        name: page_style.Stylesheet.from_page(raw, capture_page_pins.PAGES[name][1])
        for name, raw in _raw_pages().items()
    }


def _sha256_source(text: str) -> str:
    """The CSP hash source for this text, computed here rather than taken from the kiln module."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def test_shared_tokens_match_both_pages() -> None:
    """Every shared token is served by both pages with the module's value."""
    for page, sheet in _served_sheets().items():
        served = sheet.tokens()
        for name, value in _brand_tokens().items():
            assert served.get(name) == value, (page, name)


def test_shared_tokens_are_the_story_list() -> None:
    """The shared set is the story's list: every token both pages hold alike is shared or a page-role token."""
    shared = _brand_tokens()
    alike = {name for name, value in PINNED["kiln"].items() if PINNED["photo"].get(name) == value}

    assert len(shared) == 32
    assert len(page_style.TOKEN.findall(page_style.CSS_COMMENT.sub("", brand.BRAND_TOKENS))) == 32  # none twice
    assert not set(shared) & PAGE_ROLE_TOKENS
    assert alike == set(shared) | PAGE_ROLE_TOKENS


def test_logo_matches_both_pages() -> None:
    """The module's logo is the official one, and each page serves it (whitespace aside)."""
    logo = page_style.find_logo(brand.ASMBLY_LOGO)
    assert page_style.logo_problems(logo) == []
    for page, shell in _served_shells().items():
        assert " ".join(page_style.find_logo(shell).split()) == " ".join(logo.split()), page


def test_capture_script_reproduces_the_fixtures() -> None:
    """tests/capture_page_pins.py writes the committed pins byte for byte, so a hand-edited pin fails."""
    for page, sheet in _served_sheets().items():
        tokens = (FIXTURES[page] / "pinned_tokens.json").read_text(encoding="utf-8")
        rules = (FIXTURES[page] / "pinned_rules.css").read_text(encoding="utf-8")
        assert capture_page_pins.pinned_tokens_text(sheet) == tokens, page
        assert capture_page_pins.pinned_rules_text(sheet) == rules, page


def test_page_html_has_no_copy_of_the_shared_tokens_or_logo() -> None:
    """The shared tokens and the logo are defined only in common/brand.py; each page.html holds the markers."""
    shared = set(_brand_tokens())
    logo_paths = re.findall(r'd="([^"]+)"', brand.ASMBLY_LOGO)
    assert len(logo_paths) == 17
    sheets = _raw_sheets()
    for page, raw in _raw_pages().items():
        assert not shared & set(sheets[page].tokens()), page
        assert '<svg class="logo"' not in raw, page
        for path in logo_paths:
            assert path not in raw, (page, path[:20])
        assert raw.count(brand.BRAND_TOKENS_MARKER) == 1, page
        assert raw.count(brand.ASMBLY_LOGO_MARKER) == 1, page


def test_each_page_keeps_its_own_tokens() -> None:
    """Each raw page.html defines exactly its pinned tokens minus the shared ones, with the pinned values."""
    shared = set(_brand_tokens())
    own = {page: sheet.tokens() for page, sheet in _raw_sheets().items()}
    for page, tokens in own.items():
        assert set(tokens) == set(PINNED[page]) - shared, page
        assert tokens == {name: PINNED[page][name] for name in tokens}, page

    kiln_own = own["kiln"]
    assert kiln_own["--accent"] == "var(--ceramics)"
    assert kiln_own["--content-max-width"] == "50rem"
    assert {"--error-bg", "--error-edge", "--table-head-bg"} <= set(kiln_own)

    photo_own = own["photo"]
    assert photo_own["--brand"] == "var(--asmbly-purple)"
    assert photo_own["--content-max-width"] == "47.5rem"
    assert {"--woodwork", "--metalwork", "--textiles", "--electronics", "--printing-3d"} <= set(photo_own)
    assert {"--progress-height", "--progress-fill", "--control-border"} <= set(photo_own)


def test_changing_a_shared_token_changes_both_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new value for one shared token in brand.py reaches both served pages, and the kiln CSP hash follows."""
    changed = brand.BRAND_TOKENS.replace("--asmbly-purple: #292D6A;", "--asmbly-purple: #123456;")
    assert changed != brand.BRAND_TOKENS
    kiln_style = capture_page_pins.PAGES["kiln"][1]
    task = {"id": "abc123", "custom_id": "KO-1", "name": "Customer Z", "date_created": "1704067200000"}
    event = json.loads((FIXTURES["photo"] / "api_event_page.json").read_text(encoding="utf-8"))
    env = {"STAFF_AUTH_DOMAIN": "asmbly-staff.auth.us-east-2.amazoncognito.com", "CLASS_PHOTO_APP_CLIENT_ID": "client123"}
    try:
        monkeypatch.setattr(brand, "BRAND_TOKENS", changed)

        importlib.reload(kiln)
        style_src = re.search(r"style-src ([^;]+);", kiln.RESPONSE_HEADERS["Content-Security-Policy"])
        assert style_src
        pages = {
            "empty": kiln.generate_html_page([]),
            "tasks": kiln.generate_html_page([dict(task)]),
            "error": kiln.generate_error_page(),
        }
        for name, page in pages.items():
            style = kiln_style.findall(page)
            assert len(style) == 1, name
            assert "--asmbly-purple: #123456;" in style[0], name
            assert "#292D6A" not in style[0], name
            assert style_src.group(1) == _sha256_source(style[0]), name

        monkeypatch.setattr(photo, "_page_template", None)
        with patch.dict("os.environ", env, clear=True):
            response = photo.lambda_handler(event, None)
        assert response["statusCode"] == 200
        style = re.findall(r'<style nonce="[A-Za-z0-9_-]+">(.*?)</style>', response["body"], re.S)
        assert len(style) == 1
        assert "--asmbly-purple: #123456;" in style[0]
        assert "#292D6A" not in style[0]
    finally:
        # Undo first, then reload, so the kiln module is filled with the real value again.
        monkeypatch.undo()
        importlib.reload(kiln)
    assert "--asmbly-purple: #292D6A;" in kiln.PAGE_TEMPLATE
    assert "--asmbly-purple: #292D6A;" in photo._template()


def test_photo_page_imports_no_third_party_module() -> None:
    """The photo page function, with only the repository and the common layer on its path, loads no boto3 or requests."""
    code = (
        "import json, sys\n"
        f"sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'layers' / 'common' / 'python')!r}]\n"
        "import functions.classes.class_photo_upload_page.lambda_function\n"
        "import common.brand\n"
        "print(json.dumps({'brand': common.brand.__file__,"
        " 'loaded': [name for name in ('boto3', 'botocore', 'requests') if name in sys.modules]}))\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["loaded"] == []
    assert pathlib.Path(report["brand"]).resolve().is_relative_to(ROOT / "layers" / "common" / "python")
