"""Style checks shared by the tests of the repository's HTML pages.

The kiln drop-off viewer and the class photo upload page each keep one inline <style>
block whose first rule is a :root block of design tokens. Their tests read the page with
`Stylesheet.from_page` and pass the page's own data (brand colours, contrast pairs,
allowed words, reserved tokens) to the checks here.

Each `*_problems` check returns a list of messages; an empty list is a pass, so a test
writes `assert page_style.contrast_problems(SHEET, PAIRS) == []` and pytest prints the
list when it fails. Parsing helpers raise `ValueError` or `LookupError` on input they
can't read (no style block, a token that isn't a colour, no rule for a selector).

A page's test file usually builds its `Stylesheet` at import. A malformed style block then
fails the collection of that test file, not only its style tests.

Test code only: nothing outside the tests imports this module, and no template packages
this folder (`tests/test_page_style.py` checks that).
"""
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
TOKEN = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
VAR_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])")
PURE_WHITE_OR_BLACK = re.compile(r"(?<![\w-])(white|black)(?![\w-])", re.I)
# A font stack: two or more families separated by ", ", the last a CSS generic family in
# lower case (so the browser always has a fallback). A family is a double-quoted name or
# an unquoted ASCII name: a letter or `_`, optionally after one `-`, then letters, digits,
# `_` or `-` (so not a digit, `--` or a non-ASCII letter first). House style quotes every
# multi-word name, so an unquoted one such as Times New Roman is rejected on purpose, as
# are single quotes and a lone generic family.
_FONT_STACK_FAMILY = r'(?:"[\w ]+"|-?[A-Za-z_][\w-]*)'
GENERIC_FONT_FAMILY = (
    r"(?:serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-serif|ui-sans-serif"
    r"|ui-monospace|ui-rounded|emoji|math|fangsong)"
)
FONT_STACK = re.compile(rf"(?:{_FONT_STACK_FAMILY}, )+{GENERIC_FONT_FAMILY}")
# A --glyph-* token: one visible character and an empty alternative text, so screen
# readers skip it (CSS Generated Content, "content: <string> / <string>").
GLYPH_TOKEN = re.compile(r'"[^"\s]" / ""')
MEDIA_BLOCK = re.compile(r"@media([^{]*)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
HOVER_MEDIA = "(hover: hover)"
ROOT_FONT_PX = 16

# The official Asmbly logo, inline: its opening tag, its paths, and the start of the icon
# path. Its colour comes from CSS (fill: currentColor), so it carries none of
# LOGO_FORBIDDEN.
LOGO_START = '<svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">'
LOGO_PATH_COUNT = 17
LOGO_ICON_PATH = 'd="m122.16,77.71V0H0v44.44h20.85'
LOGO_FORBIDDEN = ("fill", "stroke", "style", "xmlns", "href", "<image")

_HEX_RRGGBB = re.compile(r"#[0-9a-fA-F]{6}")
_RGB_OR_HSL = re.compile(r"\b(rgba?|hsla?)\(")
_NUMBER = re.compile(r"\d*\.?\d+(?:[a-z%]+)?")
_WORD = re.compile(r"[A-Za-z][\w-]*")
_QUOTED = re.compile(r'"([^"]*)"')
_FONT_FAMILY = re.compile(r"font-family:\s*([^;}]+)")
_FONT_FAMILY_TOKEN = re.compile(r"var\(--font-[\w-]+\)")
_FONT_SHORTHAND = re.compile(r"(?<![\w-])font:\s*([^;}]+)")
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)
_ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')


def split_selectors(selectors: str) -> list[str]:
    """A selector list's selectors, stripped, split only on commas at the top level.

    A comma inside parentheses (`:is(a, b)`, `:not(.x, .y)`) or inside a quoted string
    (`[title="a, b"]`) doesn't split. A string ends only at the quote character that opened
    it, and parentheses inside a string don't count. Unbalanced input doesn't raise: a
    stray `)` never takes the depth below 0, and an unclosed `(` or quote keeps the rest of
    the list in one selector. Backslash escapes are not handled (neither page uses one).
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for character in selectors:
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth = max(depth - 1, 0)
        elif character == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    parts.append("".join(current).strip())
    return parts


@dataclass(frozen=True)
class Stylesheet:
    """A page's one inline stylesheet."""

    style: str  # the text inside the page's one <style> block

    @classmethod
    def from_page(cls, page_html: str, style_block: re.Pattern[str]) -> "Stylesheet":
        """The page's stylesheet; `style_block` must match once, with the CSS as its group."""
        blocks = style_block.findall(page_html)
        if len(blocks) != 1:
            raise ValueError(f"expected one <style> block, found {len(blocks)}")
        return cls(blocks[0])

    @property
    def css(self) -> str:
        """The stylesheet without comments."""
        return CSS_COMMENT.sub("", self.style)

    def root_block(self) -> str:
        """The body of the :root rule, which must be the stylesheet's only :root and its first rule."""
        css = self.css.strip()
        if not css.startswith(":root {"):
            raise ValueError("the token block must be the first rule")
        if css.count(":root") != 1:
            raise ValueError("there must be one token block")
        return css[len(":root {") : css.index("}")]

    def rules_after_root(self) -> str:
        """Every rule after the token block."""
        self.root_block()  # raises a readable ValueError when the token block isn't first
        css = self.css.strip()
        return css[css.index("}") + 1 :]

    def tokens(self) -> dict[str, str]:
        """The custom properties the token block defines, by name."""
        return {name: value.strip() for name, value in TOKEN.findall(self.root_block())}

    def colour(self, name: str) -> str:
        """A token's colour as lower-case #rrggbb, following var() references."""
        value = self.tokens()[name]
        reference = VAR_REFERENCE.fullmatch(value)
        if reference:
            return self.colour(reference.group(1))
        if not _HEX_RRGGBB.fullmatch(value):
            raise ValueError(f"{name} is not a #rrggbb colour: {value}")
        return value.lower()

    def used_tokens(self) -> set[str]:
        """Every token name a var() in the stylesheet reads."""
        return set(VAR_REFERENCE.findall(self.css))

    def rules(self) -> list[tuple[str, list[str], str]]:
        """Every rule after the token block as (media condition or "", selectors, declarations).

        The selector list is split with `split_selectors`, so `:is(a, b)` stays one selector.
        """
        css = self.rules_after_root()
        found = []
        for media in MEDIA_BLOCK.finditer(css):
            for selectors, body in RULE.findall(media.group(2)):
                found.append((media.group(1).strip(), split_selectors(selectors), body))
        for selectors, body in RULE.findall(MEDIA_BLOCK.sub("", css)):
            found.append(("", split_selectors(selectors), body))
        return found

    def rule(self, selector: str, media: str = "") -> str:
        """The declarations of every rule whose selector list holds exactly `selector`, joined."""
        bodies = [
            " ".join(body.split())
            for condition, selectors, body in self.rules()
            if condition == media and selector in selectors
        ]
        if not bodies:
            raise LookupError(f"no rule for {selector} {media}".strip())
        return "; ".join(bodies)


def channels(colour: str) -> list[int]:
    """The red, green and blue channels of a #rrggbb colour."""
    return [int(colour[index : index + 2], 16) for index in (1, 3, 5)]


def mix(a: str, b: str, p: float) -> str:
    """p × a + (1 − p) × b per sRGB channel, rounded, as #rrggbb."""
    mixed = [round(p * x + (1 - p) * y) for x, y in zip(channels(a), channels(b))]
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def luminance(colour: str) -> float:
    """The WCAG 2.1 relative luminance of a #rrggbb colour."""

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: str, background: str) -> float:
    """The WCAG 2.1 contrast ratio of two #rrggbb colours."""
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def rem_to_px(value: str) -> float:
    """A rem length in pixels, at the browser's default root font size."""
    if not value.endswith("rem"):
        raise ValueError(f"not a rem length: {value}")
    return float(value.removesuffix("rem")) * ROOT_FONT_PX


def declaration_values(css: str) -> list[str]:
    """The value of every declaration in every rule body (not selectors, not @media conditions)."""
    values = []
    for body in re.findall(r"\{([^{}]*)\}", css):
        for declaration in body.split(";"):
            if ":" in declaration:
                values.append(declaration.split(":", 1)[1].strip())
    return values


def markup(page_html: str, *blocks: re.Pattern[str]) -> str:
    """The page with every match of each pattern (its <style> and <script> blocks) removed."""
    for block in blocks:
        page_html = block.sub("", page_html)
    return page_html


def find_logo(html: str) -> str:
    """The text from the first <svg class="logo" to the next </svg>, or "" when there is none."""
    start = html.find('<svg class="logo"')
    if start == -1:
        return ""
    end = html.find("</svg>", start)
    return html[start:] if end == -1 else html[start:end]


def brand_colour_problems(sheet: Stylesheet, expected: Mapping[str, str]) -> list[str]:
    """Each brand token that is missing or has a value other than the guide's (ignoring case)."""
    tokens = sheet.tokens()
    problems = []
    for name, value in expected.items():
        if name not in tokens:
            problems.append(f"{name} is not defined")
        elif tokens[name].lower() != value.lower():
            problems.append(f"{name} is {tokens[name]}, the guide says {value}")
    return problems


def derived_colour_problems(sheet: Stylesheet, derived: Iterable[tuple[str, str, str, float]]) -> list[str]:
    """Each (token, first, second, share) whose colour isn't mix(first, second, share)."""
    problems = []
    for name, first, second, share in derived:
        expected = mix(sheet.colour(first), sheet.colour(second), share)
        actual = sheet.colour(name)
        if actual != expected:
            problems.append(f"{name} is {actual}, expected {expected} ({share:g} of {first} with {second})")
    return problems


def contrast_problems(sheet: Stylesheet, pairs: Iterable[tuple[str, str, float]]) -> list[str]:
    """Each (foreground, background, minimum) whose WCAG 2.1 contrast ratio is below the minimum."""
    problems = []
    for foreground, background, minimum in pairs:
        ratio = contrast(sheet.colour(foreground), sheet.colour(background))
        if ratio < minimum:
            problems.append(f"{foreground} on {background} is {ratio:.2f}:1, below {minimum:g}:1")
    return problems


def unused_token_problems(sheet: Stylesheet, reserved: Mapping[str, str]) -> list[str]:
    """Each token no var() reads that isn't reserved, and each reserved token that is read or not defined."""
    defined = set(sheet.tokens())
    used = sheet.used_tokens()
    problems = [f"{name} is defined but no var() reads it" for name in sorted(defined - used - set(reserved))]
    problems += [f"{name} is reserved but a var() reads it" for name in sorted(set(reserved) & used)]
    problems += [f"{name} is reserved but not defined" for name in sorted(set(reserved) - defined)]
    return problems


def undefined_token_problems(sheet: Stylesheet) -> list[str]:
    """No var() in the stylesheet at all, or a var() naming a token the block doesn't define."""
    used = sheet.used_tokens()
    if not used:
        return ["the stylesheet reads no token through var()"]
    return [f"{name} is read but not defined" for name in sorted(used - set(sheet.tokens()))]


def token_block_problems(
    sheet: Stylesheet, *, token_value: re.Pattern[str], glyph_exempt: tuple[str, ...] = ()
) -> list[str]:
    """Anything in the :root block that isn't a token of the expected form.

    `--font-*` tokens (other than `--font-size*`) must be font stacks (`FONT_STACK`: two or
    more families separated by ", ", each a double-quoted name or an unquoted ASCII name,
    the last a lower-case generic family such as `sans-serif`), `--glyph-*` tokens glyphs, and every
    other token must fully match `token_value`. `glyph_exempt` holds name
    prefixes of `--glyph-*` tokens that are lengths, not glyphs (matched with startswith).
    The only declaration that isn't a token is `color-scheme: light`.
    """
    block = sheet.root_block()
    problems = []
    if not block.strip().endswith(";"):
        problems.append("the last token doesn't end with a semicolon")
    for declaration in block.split(";"):
        if not declaration.strip():
            continue
        if ":" not in declaration:
            problems.append(f"{declaration.strip()} is not a declaration")
            continue
        name, value = (part.strip() for part in declaration.split(":", 1))
        if name == "color-scheme":
            if value != "light":
                problems.append(f"color-scheme: {value}")
            continue
        if not name.startswith("--"):
            problems.append(f"{name} in the token block")
        elif name.startswith("--font-") and not name.startswith("--font-size"):
            if not FONT_STACK.fullmatch(value):
                problems.append(f"{name}: {value}")
        elif name.startswith("--glyph-") and not name.startswith(glyph_exempt):
            if not GLYPH_TOKEN.fullmatch(value):
                problems.append(f"{name}: {value}")
        elif not token_value.fullmatch(value):
            problems.append(f"{name}: {value}")
    return problems


def defined_once_problems(sheet: Stylesheet, shared_literals: Mapping[str, set[str]]) -> list[str]:
    """A token name, colour or font stack defined twice, and a literal shared other than as listed.

    `shared_literals` maps each literal value that two or more tokens may share to the set
    of tokens that share it; a literal shared by any other set is a problem.
    """
    definitions = [(name, value.strip()) for name, value in TOKEN.findall(sheet.root_block())]
    literals = [value for _, value in definitions if not VAR_REFERENCE.fullmatch(value)]
    colours = [value.lower() for value in literals if HEX_COLOUR.fullmatch(value)]
    stacks = [value for value in literals if "," in value]
    problems = [f"token {name} is defined {count} times" for name, count in Counter(n for n, _ in definitions).items() if count > 1]
    problems += [f"colour {value} is defined {count} times" for value, count in Counter(colours).items() if count > 1]
    problems += [f"font stack {value} is defined {count} times" for value, count in Counter(stacks).items() if count > 1]
    by_value: dict[str, set[str]] = {}
    for name, value in definitions:
        if not VAR_REFERENCE.fullmatch(value):
            by_value.setdefault(value, set()).add(name)
    shared = {value: names for value, names in by_value.items() if len(names) > 1}
    for value in sorted(set(shared) | set(shared_literals)):
        if shared.get(value) != shared_literals.get(value):
            problems.append(
                f"literal {value} is shared by {sorted(shared.get(value, set()))}, "
                f"listed as {sorted(shared_literals.get(value, set()))}"
            )
    return problems


def tokens_only_problems(
    sheet: Stylesheet,
    *,
    allowed_words: set[str],
    string_words: set[str] | frozenset[str] = frozenset(),
    font_shorthand: set[str] | frozenset[str] = frozenset(),
    min_declarations: int,
) -> list[str]:
    """A literal value in a rule after the token block, where only var() should be.

    Reported: a hex colour; rgb(), rgba(), hsl() or hsla(); a number other than 0 or 100%;
    a word outside `allowed_words`; a double quote, unless it is part of a "…" string
    whose words are all in `string_words` (so with no `string_words`, any quote); a
    font-family other than one var(--font-…); a `font:` shorthand whose value isn't in
    `font_shorthand`; and fewer than `min_declarations` declarations, which means the
    parser missed rules.
    """
    rules = sheet.rules_after_root()
    problems = [f"hex colour {match.group(0)} outside the token block" for match in HEX_COLOUR.finditer(rules)]
    problems += [f"{match.group(1)}() outside the token block" for match in _RGB_OR_HSL.finditer(rules)]
    values = declaration_values(rules)
    if len(values) < min_declarations:
        problems.append(f"the declaration parser found {len(values)} declarations, fewer than {min_declarations}")
    for value in values:
        literal = VAR_REFERENCE.sub("", value)
        if string_words:
            for string in _QUOTED.findall(literal):
                if not set(string.split()) <= string_words:
                    problems.append(f"unexpected string in: {value}")
            literal = _QUOTED.sub("", literal)
        if '"' in literal:
            problems.append(f"string in: {value}")
        if not all(number in ("0", "100%") for number in _NUMBER.findall(literal)):
            problems.append(f"magic value in: {value}")
        words = set(_WORD.findall(literal))
        if not words <= allowed_words:
            problems.append(f"literal {sorted(words - allowed_words)} in: {value}")
    for match in _FONT_FAMILY.finditer(rules):
        if not _FONT_FAMILY_TOKEN.fullmatch(match.group(1).strip()):
            problems.append(match.group(0))
    for match in _FONT_SHORTHAND.finditer(rules):
        if match.group(1).strip() not in font_shorthand:
            problems.append(match.group(0))
    return problems


def svg_attribute_problems(markup: str, allowed: set[str], *, fill: re.Pattern[str] | None = None) -> list[str]:
    """An attribute on an inline <svg> or its children outside `allowed`, and a <style> inside one.

    With `fill`, a fill attribute (which `allowed` must also list) must fully match it.
    """
    problems = []
    for svg in _SVG.findall(markup):
        if "<style" in svg:
            problems.append("<style> inside an SVG")
        for name, value in _ATTRIBUTE.findall(svg):
            if name not in allowed:
                problems.append(f"SVG attribute {name}")
            elif name == "fill" and fill is not None and not fill.fullmatch(value):
                problems.append(f'fill="{value}"')
    return problems


def logo_problems(svg: str) -> list[str]:
    """How `svg` (from find_logo) differs from the official Asmbly logo."""
    if not svg:
        return ["no Asmbly logo found"]
    problems = []
    if not svg.startswith(LOGO_START):
        problems.append(f"the logo doesn't start with {LOGO_START}")
    paths = svg.count("<path ")
    if paths != LOGO_PATH_COUNT:
        problems.append(f"the logo has {paths} paths, the official logo has {LOGO_PATH_COUNT}")
    if LOGO_ICON_PATH not in svg:
        problems.append(f"the logo has no icon path ({LOGO_ICON_PATH}…)")
    problems += [f"{forbidden} in the logo" for forbidden in LOGO_FORBIDDEN if forbidden in svg]
    return problems
