"""Tests that span both HTML pages and common.brand, the brand tokens and logo they share (story #138).

The module's own tests are in layers/common/tests/test_brand.py; each page's pins are in its
own test file.
"""
import json
import pathlib

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
