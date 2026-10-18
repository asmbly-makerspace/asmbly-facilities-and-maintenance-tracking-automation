"""Writes the style pins of the repository's two HTML pages from what each page serves.

Each page's tests compare its served `:root` tokens and the CSS rules after them with two
fixtures in its `tests/fixtures/` folder: `pinned_tokens.json` (the tokens by name, sorted)
and `pinned_rules.css` (the rules, comments and blank lines removed). The pins first held
`stage` 6fd11c9, from before story #138 moved the shared tokens and logo into
`common/brand.py`, so they show that the move changed nothing a visitor sees.

After a deliberate change to a page's look, regenerate both pages' pins from the
repository root and commit them with the change:

    .venv/bin/python -m tests.capture_page_pins

The script reads the served page shell (the kiln function's `PAGE_TEMPLATE` and the photo
page function's `_template()`), so the shared tokens are included. It doesn't call `git`.
"""
import json
import logging
import pathlib
import re
import sys

from tests import page_style

logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Each page: its function's folder, relative to the repository root, and its served shell's style block.
PAGES: dict[str, tuple[str, re.Pattern[str]]] = {
    "kiln": ("functions/ceramics/kiln_dropoff_recent_entries_viewer", re.compile(r"<style>(.*?)</style>", re.S)),
    "photo": (
        "functions/classes/class_photo_upload_page",
        re.compile(r'<style nonce="__CSP_NONCE__">(.*?)</style>', re.S),
    ),
}


def pinned_tokens_text(sheet: page_style.Stylesheet) -> str:
    """The `pinned_tokens.json` text: the `:root` tokens by name, sorted, so their order in `:root` doesn't matter."""
    return json.dumps(sheet.tokens(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def pinned_rules_text(sheet: page_style.Stylesheet) -> str:
    """The `pinned_rules.css` text: every rule after `:root`, lines right-stripped, blank lines dropped."""
    lines = [line.rstrip() for line in sheet.rules_after_root().splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def served_sheets() -> dict[str, page_style.Stylesheet]:
    """Each page's stylesheet as its function serves it."""
    # Imported here so that importing this module doesn't import both pages' functions.
    from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as kiln
    from functions.classes.class_photo_upload_page import lambda_function as photo

    shells = {"kiln": kiln.PAGE_TEMPLATE, "photo": photo._template()}
    return {name: page_style.Stylesheet.from_page(shells[name], block) for name, (_, block) in PAGES.items()}


def main() -> None:
    """Write both pages' pins into their `tests/fixtures/` folders."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # The kiln function imports common.aws, which the tests find through pytest.ini.
    sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))
    for name, sheet in served_sheets().items():
        fixtures = ROOT / PAGES[name][0] / "tests" / "fixtures"
        (fixtures / "pinned_tokens.json").write_text(pinned_tokens_text(sheet), encoding="utf-8")
        rules = pinned_rules_text(sheet)
        (fixtures / "pinned_rules.css").write_text(rules, encoding="utf-8")
        logger.info("%s: %s tokens, %s rule lines", name, len(sheet.tokens()), rules.count("\n"))


if __name__ == "__main__":
    main()
