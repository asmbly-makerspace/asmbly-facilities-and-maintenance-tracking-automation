"""Tests of common.brand: the brand tokens and logo the HTML pages share, and fill_brand.

Pytest and the standard library only, so the layer's tests stand alone. The tests that
compare the module with what the pages serve are in tests/test_shared_brand.py.
"""
import ast
import os
import re
import subprocess
import sys

import pytest

# Add the python directory to the path to allow common module imports
LAYER_PYTHON = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python'))
sys.path.insert(0, LAYER_PYTHON)

from common import brand

PAGE = "<style>:root {\n    /* __BRAND_TOKENS__ */\n    --own: 0;\n}</style>\n<header>\n    <!-- __ASMBLY_LOGO__ -->\n</header>"
LOGO_START = '<svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">'
# The words tests/page_style.LOGO_FORBIDDEN lists, repeated here so these tests don't import it.
LOGO_FORBIDDEN = ("fill", "stroke", "style", "xmlns", "href", "<image")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def test_fill_brand_replaces_both_markers() -> None:
    filled = brand.fill_brand(PAGE)

    assert brand.BRAND_TOKENS_MARKER not in filled
    assert brand.ASMBLY_LOGO_MARKER not in filled
    assert filled == PAGE.replace(brand.BRAND_TOKENS_MARKER, brand.BRAND_TOKENS).replace(
        brand.ASMBLY_LOGO_MARKER, brand.ASMBLY_LOGO
    )
    assert filled.count(brand.BRAND_TOKENS) == 1
    assert filled.count(brand.ASMBLY_LOGO) == 1


def test_fill_brand_needs_exactly_one_token_marker() -> None:
    with pytest.raises(ValueError, match="found 0"):
        brand.fill_brand(PAGE.replace(brand.BRAND_TOKENS_MARKER, ""))
    with pytest.raises(ValueError, match="found 2"):
        brand.fill_brand(PAGE + brand.BRAND_TOKENS_MARKER)


def test_fill_brand_allows_no_logo_but_not_two() -> None:
    filled = brand.fill_brand(PAGE.replace(brand.ASMBLY_LOGO_MARKER, ""))

    assert brand.BRAND_TOKENS in filled
    assert "<svg" not in filled
    with pytest.raises(ValueError, match="found 2"):
        brand.fill_brand(PAGE + brand.ASMBLY_LOGO_MARKER)


def test_fill_brand_reads_the_current_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed value reaches the next page filled, which the both-pages test relies on."""
    monkeypatch.setattr(brand, "BRAND_TOKENS", "--x: 1px;")
    monkeypatch.setattr(brand, "ASMBLY_LOGO", "<svg></svg>")

    filled = brand.fill_brand(PAGE)

    assert "/* __BRAND_TOKENS__ */" not in filled
    assert "    --x: 1px;\n" in filled
    assert "    <svg></svg>\n" in filled


def test_brand_tokens_are_declarations() -> None:
    parts = [part.strip() for part in CSS_COMMENT.sub("", brand.BRAND_TOKENS).split(";")]
    assert parts[-1] == ""  # the text ends with a declaration's semicolon
    declarations = parts[:-1]

    assert len(declarations) == 32
    names = []
    for declaration in declarations:
        assert re.fullmatch(r"--[a-z0-9-]+: \S.*", declaration), declaration
        names.append(declaration.split(":", 1)[0])
    assert len(set(names)) == len(names)


def test_shared_text_cannot_leave_its_place() -> None:
    """The tokens can't close the :root rule or the <style> element, and neither constant holds a page's marker."""
    assert not set("{}<>") & set(brand.BRAND_TOKENS)
    assert "__" not in brand.BRAND_TOKENS
    assert "__" not in brand.ASMBLY_LOGO


def test_logo_is_the_17_path_svg() -> None:
    logo = brand.ASMBLY_LOGO

    assert logo.startswith(LOGO_START)
    assert logo.endswith("</svg>")
    assert logo.count("<svg") == 1
    assert logo.count("<path ") == 17
    assert [word for word in LOGO_FORBIDDEN if word in logo] == []


def test_brand_imports_only_the_standard_library() -> None:
    """Story #138 criterion 6: the shared module imports only the Python standard library."""
    with open(brand.__file__, encoding="utf-8") as source:
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


def test_importing_brand_loads_no_third_party_module() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {LAYER_PYTHON!r})\n"
        "import common.brand\n"
        "print(any(name in sys.modules for name in ('boto3', 'botocore', 'requests')))\n"
    )

    result = subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True)

    assert result.stdout.strip() == "False"
