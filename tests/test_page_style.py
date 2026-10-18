"""Tests of the shared page style checks in tests/page_style.py.

Each check gets an input it passes and one it reports, so no test passes on a check that
never reports anything.
"""
import pathlib
import re

import pytest

from tests import page_style

ROOT = pathlib.Path(__file__).resolve().parent.parent
KILN_PAGE = ROOT / "functions" / "ceramics" / "kiln_dropoff_recent_entries_viewer" / "page.html"
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
TOKEN_VALUE = re.compile(r"#[0-9a-fA-F]{6}|var\(--[\w-]+\)|\d*\.?\d+(?:rem|px)?")
WORDS = {"solid", "none"}


def _sheet(css: str) -> page_style.Stylesheet:
    return page_style.Stylesheet(css)


def _kiln_logo() -> str:
    return page_style.find_logo(KILN_PAGE.read_text(encoding="utf-8"))


def test_from_page_reads_the_one_style_block() -> None:
    sheet = page_style.Stylesheet.from_page("<html><style>:root { --a: 0; }</style></html>", STYLE_BLOCK)
    assert sheet.style == ":root { --a: 0; }"

    with pytest.raises(ValueError, match="found 0"):
        page_style.Stylesheet.from_page("<html></html>", STYLE_BLOCK)
    with pytest.raises(ValueError, match="found 2"):
        page_style.Stylesheet.from_page("<style>a { }</style><style>b { }</style>", STYLE_BLOCK)


def test_root_block_must_be_first_and_only() -> None:
    assert _sheet("/* tokens */ :root { --a: 0; } a { b: var(--a); }").root_block() == " --a: 0; "

    with pytest.raises(ValueError, match="first rule"):
        _sheet("a { color: var(--a); } :root { --a: 0; }").root_block()
    with pytest.raises(ValueError, match="one token block"):
        _sheet(":root { --a: 0; } :root { --b: 0; }").root_block()
    with pytest.raises(ValueError, match="first rule"):
        _sheet("no rules at all").rules_after_root()


def test_colour_follows_references_and_rejects_non_colours() -> None:
    sheet = _sheet(":root { --a: #ABCDEF; --b: var(--a); --c: 1rem; }")

    assert sheet.colour("--a") == "#abcdef"
    assert sheet.colour("--b") == "#abcdef"
    with pytest.raises(ValueError, match="--c is not a #rrggbb colour: 1rem"):
        sheet.colour("--c")
    with pytest.raises(KeyError):
        sheet.colour("--missing")


def test_rules_carry_their_media_condition() -> None:
    sheet = _sheet(
        ":root { --a: 0; }"
        " a, b { margin: var(--a); }"
        " @media (hover: hover) { a:hover { padding: var(--a); } }"
        " a { border: none; }"
    )

    assert ("(hover: hover)", ["a:hover"], " padding: var(--a); ") in sheet.rules()
    assert sheet.rule("a:hover", page_style.HOVER_MEDIA) == "padding: var(--a);"
    joined = sheet.rule("a")
    assert "margin: var(--a);" in joined and "border: none;" in joined
    assert joined.index("margin") < joined.index("border")
    assert sheet.used_tokens() == {"--a"}
    with pytest.raises(LookupError, match=r"no rule for a:hover$"):
        sheet.rule("a:hover")
    with pytest.raises(LookupError, match=r"no rule for i \(hover: hover\)"):
        sheet.rule("i", page_style.HOVER_MEDIA)


def test_contrast_matches_wcag() -> None:
    assert page_style.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert page_style.contrast("#ffffff", "#000000") == pytest.approx(21.0)
    assert page_style.contrast("#767676", "#ffffff") >= 4.5
    assert page_style.mix("#ffffff", "#000000", 0.5) == "#808080"
    assert page_style.channels("#0a0b0c") == [10, 11, 12]
    assert page_style.rem_to_px("1.5rem") == 24
    with pytest.raises(ValueError):
        page_style.rem_to_px("24px")


def test_contrast_below_4_5_is_reported() -> None:
    """Story #137 criterion 4: a pair below 4.5:1 is a failure; a pair at 4.5:1 or above is not."""
    low = _sheet(":root { --fg: #777777; --bg: #ffffff; }")
    ok = _sheet(":root { --fg: #767676; --bg: var(--white); --white: #ffffff; }")

    problems = page_style.contrast_problems(low, [("--fg", "--bg", 4.5)])
    assert problems == ["--fg on --bg is 4.48:1, below 4.5:1"]
    assert page_style.contrast_problems(ok, [("--fg", "--bg", 4.5)]) == []


def test_unused_token_is_reported() -> None:
    """Story #137 criterion 4: a token no var() reads is a failure unless it is reserved."""
    sheet = _sheet(":root { --a: 0; --b: 0; } p { margin: var(--a); }")

    assert page_style.unused_token_problems(sheet, {}) == ["--b is defined but no var() reads it"]
    assert page_style.unused_token_problems(sheet, {"--b": "a reason"}) == []
    assert page_style.unused_token_problems(sheet, {"--a": "a reason"}) == [
        "--b is defined but no var() reads it",
        "--a is reserved but a var() reads it",
    ]
    assert page_style.unused_token_problems(sheet, {"--b": "a reason", "--gone": "a reason"}) == [
        "--gone is reserved but not defined"
    ]


def test_undefined_token_is_reported() -> None:
    assert page_style.undefined_token_problems(_sheet(":root { --a: 0; } p { margin: var(--a); }")) == []
    assert page_style.undefined_token_problems(_sheet(":root { --a: 0; } p { margin: var(--missing); }")) == [
        "--missing is read but not defined"
    ]
    assert page_style.undefined_token_problems(_sheet(":root { --a: 0; } p { margin: 0; }")) == [
        "the stylesheet reads no token through var()"
    ]


def test_logo_with_a_missing_path_is_reported() -> None:
    """Story #137 criterion 4: the official logo passes; the logo with a path missing doesn't."""
    logo = _kiln_logo()
    assert page_style.logo_problems(logo) == []

    paths = re.findall(r"<path [^>]*/>", logo)
    assert len(paths) == page_style.LOGO_PATH_COUNT
    other = next(path for path in paths if page_style.LOGO_ICON_PATH not in path)
    assert page_style.logo_problems(logo.replace(other, "", 1)) == ["the logo has 16 paths, the official logo has 17"]

    icon = next(path for path in paths if page_style.LOGO_ICON_PATH in path)
    problems = page_style.logo_problems(logo.replace(icon, "", 1))
    assert any("no icon path" in problem for problem in problems), problems

    assert page_style.logo_problems("") == ["no Asmbly logo found"]
    assert page_style.find_logo("<p>no logo</p>") == ""
    assert page_style.find_logo('<p><svg class="logo" role="img">') == '<svg class="logo" role="img">'
    renamed = logo.replace('aria-label="Asmbly Makerspace"', 'aria-label="Asmbly"', 1)
    assert any("doesn't start with" in problem for problem in page_style.logo_problems(renamed))


def test_logo_with_a_forbidden_attribute_is_reported() -> None:
    logo = _kiln_logo()

    assert page_style.logo_problems(logo.replace("<path ", '<path fill="#000" ', 1)) == ["fill in the logo"]
    assert page_style.logo_problems(logo.replace("<path ", '<path style="x" ', 1)) == ["style in the logo"]


def test_tokens_only_reports_literals() -> None:
    def problems(rules: str, **options: object) -> list[str]:
        sheet = _sheet(":root { --a: 0; --font-body: serif; } " + rules)
        arguments: dict[str, object] = {"allowed_words": WORDS, "min_declarations": 1, **options}
        return page_style.tokens_only_problems(sheet, **arguments)

    assert problems("p { margin: var(--a); border: none; width: 100%; padding: 0; }") == []
    assert "hex colour #fff outside the token block" in problems("p { color: #fff; }")
    assert "rgb() outside the token block" in problems("p { color: rgb(1 2 3); }")
    assert "magic value in: 12px" in problems("p { margin: 12px; }")
    assert problems("p { color: whitesmoke; }") == ["literal ['whitesmoke'] in: whitesmoke"]
    assert 'string in: "x"' in problems('p { content: "x"; }')
    assert problems('p { content: "; }') == ['string in: "']
    assert "font-family: serif" in problems("p { font-family: serif; }", allowed_words=WORDS | {"serif"})
    assert problems("p { font-family: var(--font-body); }") == []
    assert problems("p { font: var(--a); }") == ["font: var(--a)"]
    assert problems("p { font: var(--a); }", font_shorthand={"var(--a)"}) == []
    assert problems("p { margin: 0; }", min_declarations=2) == [
        "the declaration parser found 1 declarations, fewer than 2"
    ]
    # Quoted words pass when string_words lists them, and fail when it doesn't.
    areas = {"logo", "title"}
    grid = 'p { grid-template-areas: "logo title"; }'
    assert problems(grid, allowed_words=WORDS | areas, string_words=areas) == []
    assert problems('p { grid-template-areas: "logo other"; }', allowed_words=WORDS | areas, string_words=areas) == [
        'unexpected string in: "logo other"'
    ]


def test_token_block_reports_non_tokens() -> None:
    def problems(block: str, **options: object) -> list[str]:
        return page_style.token_block_problems(_sheet(f":root {{{block}}}"), token_value=TOKEN_VALUE, **options)

    clean = ' color-scheme: light; --a: #123456; --b: var(--a); --c: 1rem; --font-body: "A B", serif; --glyph-x: "!" / ""; '
    assert problems(clean) == []
    assert problems(" color: red; --a: 0; ") == ["color in the token block"]
    assert problems(" --a: 0; --b: 1") == ["the last token doesn't end with a semicolon"]
    assert problems(" --font-body: 'A', serif; ") == ["--font-body: 'A', serif"]
    assert problems(' --glyph-x: "!!" / ""; ') == ['--glyph-x: "!!" / ""']
    assert problems(" --a: 1em; ") == ["--a: 1em"]
    assert problems(" color-scheme: dark; ") == ["color-scheme: dark"]
    assert problems(" --a: 0; stray; ") == ["stray is not a declaration"]
    # A glyph-named length is exempt by prefix.
    assert problems(" --glyph-size: 1rem; ") == ["--glyph-size: 1rem"]
    assert problems(" --glyph-size: 1rem; ", glyph_exempt=("--glyph-size",)) == []


def test_font_token_must_be_a_font_stack() -> None:
    """Issue #148: a --font-* token is two or more families, the last a generic family."""

    def problems(block: str) -> list[str]:
        return page_style.token_block_problems(_sheet(f":root {{{block}}}"), token_value=TOKEN_VALUE)

    assert problems(" --font-x: red; ") == ["--font-x: red"]
    rejected = ("1rem", "0", "Roboto, Arial", "sans-serif", "Roboto,sans-serif", "a, 1x, serif")
    # The rules FONT_STACK's comment states: no `--` or non-ASCII first letter, a lower-case generic.
    rejected += ("--x, serif", "é, serif", "Roboto, Sans-Serif")
    for value in rejected:
        assert problems(f" --font-x: {value}; ") == [f"--font-x: {value}"], value
    page_stacks = (
        'Roboto, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
        '"Helvetica Neue", "Segoe UI", Roboto, Arial, system-ui, sans-serif',
        "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        '"A B", serif',
    )
    for value in page_stacks:
        assert problems(f" --font-x: {value}; ") == [], value
    # --font-size* tokens are lengths, checked by token_value.
    assert problems(" --font-size-h1: 1.75rem; ") == []
    assert problems(" --font-size-h1: red; ") == ["--font-size-h1: red"]


def test_selector_lists_split_only_on_top_level_commas() -> None:
    """Issue #148: commas inside :is(), :not() and quoted attribute values don't split a selector."""
    sheet = _sheet(
        ":root { --a: 0; }"
        " :is(a, b), c { margin: var(--a); }"
        " p:not(.x, .y) { padding: var(--a); }"
        ' [title="a, b"], e { color: var(--a); }'
        " @media (hover: hover) { :is(:not(a, b), c):hover { color: var(--a); } }"
    )

    rules = sheet.rules()
    assert ("", [":is(a, b)", "c"], " margin: var(--a); ") in rules
    assert ("", ["p:not(.x, .y)"], " padding: var(--a); ") in rules
    assert ("", ['[title="a, b"]', "e"], " color: var(--a); ") in rules
    assert ("(hover: hover)", [":is(:not(a, b), c):hover"], " color: var(--a); ") in rules
    assert sheet.rule(":is(a, b)") == "margin: var(--a);"
    assert sheet.rule("c") == "margin: var(--a);"
    with pytest.raises(LookupError):
        sheet.rule("b)")

    assert page_style.split_selectors("a, b") == ["a", "b"]
    assert page_style.split_selectors("a") == ["a"]
    # Unbalanced input doesn't raise: the depth never goes below 0, and an open
    # parenthesis or quote keeps the rest of the list whole.
    assert page_style.split_selectors("a), b") == ["a)", "b"]
    assert page_style.split_selectors(":is(a, b") == [":is(a, b"]
    assert page_style.split_selectors('[t="a, b') == ['[t="a, b']
    # Parentheses inside quotes don't count, and only the opening quote character closes a string.
    assert page_style.split_selectors('[title="a(b"], c') == ['[title="a(b"]', "c"]
    assert page_style.split_selectors('[title="it\'s, x"], c') == ['[title="it\'s, x"]', "c"]


def test_defined_once_reports_duplicates() -> None:
    def problems(block: str, shared: dict[str, set[str]]) -> list[str]:
        return page_style.defined_once_problems(_sheet(f":root {{{block}}}"), shared)

    assert problems(" --a: #111111; --b: var(--a); --c: 1rem; --d: 2rem; ", {}) == []
    assert problems(" --a: 0; --a: 1rem; ", {}) == ["token --a is defined 2 times"]
    assert problems(" --a: #111111; --b: #111111; ", {}) == [
        "colour #111111 is defined 2 times",
        "literal #111111 is shared by ['--a', '--b'], listed as []",
    ]
    assert problems(" --a: 1rem; --b: 1rem; ", {}) == ["literal 1rem is shared by ['--a', '--b'], listed as []"]
    assert problems(" --a: 1rem; --b: 1rem; ", {"1rem": {"--a", "--b"}}) == []
    assert problems(" --a: 1rem; --b: 2rem; ", {"1rem": {"--a", "--b"}}) == [
        "literal 1rem is shared by [], listed as ['--a', '--b']"
    ]


def test_brand_and_derived_colours_are_checked() -> None:
    sheet = _sheet(":root { --brand: #808080; --white: #ffffff; --brand-50: #c0c0c0; --off: #c0c0c1; }")

    assert page_style.brand_colour_problems(sheet, {"--brand": "#808080", "--white": "#FFFFFF"}) == []
    assert page_style.brand_colour_problems(sheet, {"--brand": "#808081"}) == ["--brand is #808080, the guide says #808081"]
    assert page_style.brand_colour_problems(sheet, {"--gone": "#000001"}) == ["--gone is not defined"]
    assert page_style.derived_colour_problems(sheet, [("--brand-50", "--brand", "--white", 0.5)]) == []
    assert page_style.derived_colour_problems(sheet, [("--off", "--brand", "--white", 0.5)]) == [
        "--off is #c0c0c1, expected #c0c0c0 (0.5 of --brand with --white)"
    ]


def test_svg_attribute_problems() -> None:
    allowed = {"class", "d", "fill"}
    page = '<svg class="x"><path d="M0" fill="url(#p)"/></svg>'

    assert page_style.svg_attribute_problems(page, allowed, fill=re.compile(r"url\(#[\w-]+\)")) == []
    assert page_style.svg_attribute_problems(page, {"class", "d"}) == ["SVG attribute fill"]
    assert page_style.svg_attribute_problems(page.replace("url(#p)", "#000"), allowed, fill=re.compile(r"url\(#[\w-]+\)")) == [
        'fill="#000"'
    ]
    assert page_style.svg_attribute_problems('<svg class="x"><style>a{}</style></svg>', allowed) == ["<style> inside an SVG"]
    assert page_style.markup("<style>a</style><p>b</p><script>c</script>", STYLE_BLOCK, re.compile(r"<script>.*?</script>")) == "<p>b</p>"


def test_page_style_is_outside_every_packaged_folder() -> None:
    """Story #137 criterion 5: no template packages this folder, so sam build leaves the module out."""
    templates = [ROOT / "template.yaml", *sorted((ROOT / "templates").glob("*.yaml"))]
    packaged: list[pathlib.Path] = []
    for template in templates:
        text = template.read_text(encoding="utf-8")
        resources = len(re.findall(r"^\s+Type: AWS::Serverless::(?:Function|LayerVersion)\s*$", text, re.M))
        uris = re.findall(r"^\s+(?:CodeUri|ContentUri):\s*(\S+)\s*$", text, re.M)
        # SAM packages a function with no CodeUri from the template's own folder.
        assert len(uris) == resources, template.name
        packaged += [(template.parent / uri).resolve() for uri in uris]

    assert packaged, "no CodeUri or ContentUri found"
    module = (ROOT / "tests" / "page_style.py").resolve()
    for path in packaged:
        assert path.is_dir(), path
        for test_file in (module, pathlib.Path(__file__).resolve()):
            assert not test_file.is_relative_to(path), (test_file, path)
    assert module.is_file()
    assert not module.is_relative_to(ROOT / "layers" / "common")
    assert not module.is_relative_to(ROOT / "functions")
