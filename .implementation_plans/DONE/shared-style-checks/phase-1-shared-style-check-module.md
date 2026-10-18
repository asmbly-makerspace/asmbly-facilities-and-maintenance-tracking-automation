---
phase_id: 1
title: Shared style-check module
epic: 136
implements: [137]
depends_on: []
domain: [lambda, docs]
estimated_size: L
---

# Phase 1: Shared style-check module

> **Status:** [x] Complete — 2026-10-17 on branch feature/shared-style-checks

## Required reading

- `CLAUDE.md` ("Rules", "Done means verified") and this plan's README, especially
  "Decisions" 3 to 9.
- Story #137 and its acceptance criteria (`gh issue view 137`).
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`:
  the style section from the comment `# ---- Brand tokens, contrast and layout` (line 681)
  to the end, plus `STYLE_BLOCK` (line 360, also used by the CSP hash tests at lines 392
  and 557), `test_footer_shows_asmbly_logo` (line 621) and
  `test_long_name_is_in_a_wrapping_cell` (line 672, uses `_rule`).
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: the
  sections from `# ---- Brand and design tokens` (line 262) to line 750, and the later
  tests that call `_markup`, `_rule`, `_css` (lines 773 to 840).
- `pytest.ini` (`pythonpath = . layers/common/python`; no `testpaths`, so pytest collects
  from the repository root and skips dot folders such as `.venv`, `.aws-sam`,
  `.claude`).
- `template.yaml` (`CommonLayer`, `ContentUri: layers/common/`) and the `CodeUri` lines in
  `templates/*.yaml`: what `sam build` packages.
- The function READMEs' style sections:
  `functions/classes/class_photo_upload_page/README.md` ("These tests enforce the rule",
  around line 325) and `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md`
  ("Look and brand tokens", "Contrast", around lines 136 to 215).
- The closest style example for new code: `functions/networking/dynamic_dns_update/`
  (type hints, small typed helpers).

## Goal

`tests/page_style.py` holds the token-parsing, colour, contrast, CSS-rule and logo-check
helpers, with tests of its own in `tests/test_page_style.py`. Both page test files import
it and keep only their own data and page-specific tests. Every test ID collected from the
two page files before the change is still collected after it, none skipped, and they
all pass. No file under `functions/` changes except the two test files and the two
READMEs, and nothing in `.aws-sam/build` contains the module.

## Files to create

- `tests/__init__.py`: empty. Makes the repository's `tests/` a regular package so that
  `from tests import page_style` resolves to it and not to the namespace package that
  `layers/common/python/tests/` would join (README Decision 3).
- `tests/page_style.py`: the shared helpers (below). Not a test module: its name doesn't
  match `test_*.py`, so pytest doesn't collect it, and it defines no `test_*` functions.
- `tests/test_page_style.py`: the helper's own tests (below).

## Files to modify

- `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`:
  delete the shared regexes and the `_style`, `_css`, `_root_block`, `_rules_after_root`,
  `_tokens`, `_colour`, `_channels`, `_mix`, `_luminance`, `_contrast`,
  `_declaration_values`, `_rules`, `_rule`, `_markup`, `_rem_to_px` definitions; add
  `from tests import page_style` and `SHEET = page_style.Stylesheet.from_page(PAGE_HTML, STYLE_BLOCK)`;
  rewrite each test body to call the module. Keep the page's data constants and every
  test function.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: the same.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md` and
  `functions/classes/class_photo_upload_page/README.md`: one or two sentences in the
  style-test sections saying the checks' logic lives in `tests/page_style.py` and the
  page's test file holds the page's data (the lists the README already names). Test names
  in the READMEs stay correct because no test is renamed.
- `docs/CONTRIBUTING.md`: the **Tests** bullet (around line 198) gains a sentence: an HTML
  page's colour, contrast, token and logo checks come from `tests/page_style.py`; a new
  page's tests call it with the page's own data.
- `CLAUDE.md`: **not edited in this phase** (prep amendment). `CLAUDE.md` is agent
  configuration, and an unattended run doesn't change it on its own say-so. The proposed
  map row, `| Style checks for the HTML pages | tests/page_style.py | Its tests in tests/test_page_style.py |`,
  goes in the pull request description for the person to add or decline.

`.implementation_plans/shared-style-checks/CHECKPOINT.json` is untracked on purpose: never
edit or stage it. Add files by explicit path.

## Implementation details

### lambda (test code only)

Python 3.12, type hints on every signature, only the imports used. No `print`, no
logging (test code). The module imports only `re`, `dataclasses`, `pathlib` (for the
packaging test helper, if placed there; otherwise only in the test file) and
`collections.abc`/`typing` as needed.

#### `tests/page_style.py`: constants

The regexes both pages define identically move here, unchanged: `CSS_COMMENT`, `TOKEN`,
`VAR_REFERENCE`, `HEX_COLOUR`, `PURE_WHITE_OR_BLACK`, `FONT_STACK`, `GLYPH_TOKEN`,
`MEDIA_BLOCK`, `RULE`, and `HOVER_MEDIA = "(hover: hover)"`, `ROOT_FONT_PX = 16`.
Plus the official logo's fixed facts, taken from the two tests:

```python
LOGO_START = '<svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">'
LOGO_PATH_COUNT = 17
LOGO_ICON_PATH = 'd="m122.16,77.71V0H0v44.44h20.85'  # the official icon path's start
LOGO_FORBIDDEN = ("fill", "stroke", "style", "xmlns", "href", "<image")
```

Both pages' logos open with exactly `LOGO_START` today (checked at b96cac3). The photo
page's logo contains none of `LOGO_FORBIDDEN` (README Decision 6).

What stays in each page's file (story criterion 2): `STYLE_BLOCK` (the two differ:
`<style>` and `<style nonce="__CSP_NONCE__">`), `SCRIPT_BLOCKS` (photo),
`BRAND_COLOURS`, `DERIVED_COLOURS`, `CONTRAST_PAIRS`, `ALLOWED_VALUE_WORDS`,
`GRID_AREAS` (photo), `TOKEN_VALUE` (the photo page allows `fr`), `RESERVED_TOKENS`,
`SHARED_LITERALS`, `SVG_ATTRIBUTES`, `MEDIA_RULE` (photo), `MESSAGE_KINDS` (photo),
`LOADING_MESSAGES` (photo).

#### `tests/page_style.py`: parsing

```python
@dataclass(frozen=True)
class Stylesheet:
    style: str  # the text inside the page's one <style> block

    @classmethod
    def from_page(cls, page_html: str, style_block: re.Pattern[str]) -> "Stylesheet": ...
    @property
    def css(self) -> str: ...                  # without comments
    def root_block(self) -> str: ...           # body of the one :root rule, which is the first rule
    def rules_after_root(self) -> str: ...
    def tokens(self) -> dict[str, str]: ...
    def colour(self, name: str) -> str: ...    # lower-case #rrggbb, following var() references
    def used_tokens(self) -> set[str]: ...     # every var(--x) name in the CSS
    def rules(self) -> list[tuple[str, list[str], str]]: ...   # (media condition or "", selectors, body)
    def rule(self, selector: str, media: str = "") -> str: ...  # joined bodies of rules listing exactly `selector`
```

Same algorithms as the two copies today (they are identical apart from the style-block
lookup). Malformed input raises instead of asserting:

| Case | Today | Now |
| --- | --- | --- |
| Zero or two matches of `style_block` | kiln `assert len(blocks) == 1`; photo took the first | `ValueError("expected one <style> block, found N")` on both pages (README Decision 8) |
| Stylesheet doesn't start with `:root {`, or has two `:root` | `assert` | `ValueError` with the old message |
| `colour()` of a token that isn't `#rrggbb` after following `var()` | `assert` | `ValueError(f"{name} is not a #rrggbb colour: {value}")` |
| `colour()` of an undefined token | `KeyError` | `KeyError` (unchanged) |
| `rule()` with no matching rule | `assert bodies, "no rule for …"` | `LookupError(f"no rule for {selector} {media}".strip())` |

Free functions: `channels(colour: str) -> list[int]`, `mix(a: str, b: str, p: float) -> str`,
`luminance(colour: str) -> float`, `contrast(foreground: str, background: str) -> float`
(WCAG 2.1, same formula as today), `rem_to_px(value: str) -> float` (`ValueError` unless
it ends in `rem`), `declaration_values(css: str) -> list[str]`,
`markup(page_html: str, *blocks: re.Pattern[str]) -> str` (the page with each pattern's
matches removed: the kiln page passes `STYLE_BLOCK`, the photo page `STYLE_BLOCK,
SCRIPT_BLOCKS`, matching today's `_markup`), and
`find_logo(html: str) -> str` (the text from the first `<svg class="logo"` to the next
`</svg>`, or `""` when there is none).

#### `tests/page_style.py`: checks

Each returns `list[str]`; an empty list is a pass. Messages name the token, selector or
value at fault, as today's assert messages do.

| Function | What it reports | Replaces, in both files |
| --- | --- | --- |
| `brand_colour_problems(sheet, expected: Mapping[str, str])` | a token missing or with a different value (case-insensitive) | the body of `test_brand_tokens_match_the_guide` |
| `derived_colour_problems(sheet, derived: Sequence[tuple[str, str, str, float]])` | a token that isn't `mix(first, second, share)` | `test_derived_tokens_follow_the_formula` (still parametrized: pass a one-item list) |
| `contrast_problems(sheet, pairs: Sequence[tuple[str, str, float]])` | `"--a on --b is 4.21:1, below 4.5:1"` | `test_colour_pairs_meet_contrast` (kiln) and `test_brand_colour_pairs_meet_contrast` (photo), still parametrized |
| `unused_token_problems(sheet, reserved: Mapping[str, str])` | a defined token no `var()` reads that isn't in `reserved`, and a `reserved` token that is used or not defined | `test_every_token_is_used` (today: `unused == set(RESERVED_TOKENS)`) |
| `undefined_token_problems(sheet)` | no `var()` at all, or a `var()` naming no token | `test_every_token_used_is_defined` |
| `token_block_problems(sheet, *, token_value: re.Pattern[str], glyph_exempt: tuple[str, ...] = ())` | a block not ending in `;`, a non-token declaration other than `color-scheme: light`, a font stack, glyph or other value that doesn't fit its pattern | `test_token_block_holds_only_tokens`; the photo page passes `glyph_exempt=("--glyph-size", "--glyph-offset")` |
| `defined_once_problems(sheet, shared_literals: Mapping[str, set[str]])` | a duplicate token name, colour or font stack, and a shared literal not equal to `shared_literals` | `test_tokens_are_defined_once` minus its last two lines; the `--space-N` step check stays in each page's test (README Decision 7) |
| `tokens_only_problems(sheet, *, allowed_words: set[str], string_words: set[str] = frozenset(), font_shorthand: set[str] = frozenset(), min_declarations: int)` | a hex colour, `rgb()`/`hsl()`, a number other than `0` or `100%`, a word outside `allowed_words`, a quoted string (if `string_words` is empty) or a string word outside `string_words`, a `font-family` that isn't one `var(--font-…)`, a `font:` shorthand whose value isn't in `font_shorthand`, and fewer than `min_declarations` declarations | the CSS half of `test_styles_use_tokens_only`. Kiln: `allowed_words=ALLOWED_VALUE_WORDS`, `min_declarations=61` (today `> 60`). Photo: `allowed_words=ALLOWED_VALUE_WORDS \| GRID_AREAS`, `string_words=GRID_AREAS`, `font_shorthand={"inherit"}`, `min_declarations=101` (today `> 100`) |
| `svg_attribute_problems(markup: str, allowed: set[str], *, fill: re.Pattern[str] \| None = None)` | an attribute on an inline `<svg>` (and its children) outside `allowed`; a `fill` value that doesn't fully match `fill`; a `<style` inside an SVG | the SVG loop of `test_styles_use_tokens_only`. Photo passes `fill=re.compile(r"url\(#[\w-]+\)")` |
| `logo_problems(svg: str)` | `""` (no logo found); not starting with `LOGO_START`; a `<path ` count other than `LOGO_PATH_COUNT`; no `LOGO_ICON_PATH`; any of `LOGO_FORBIDDEN` | the shared part of `test_footer_shows_asmbly_logo` (kiln) and `test_page_shows_official_logo_in_header` (photo) |

Each page test keeps the lines that are its own: the kiln test's footer and band
placement, `page.count('<svg class="logo"') == 1`, and the `.logo` rule checks; the photo
test's `PAGE_HTML.count(logo) == 1` (`logo_problems` doesn't count logos), its header
placement and "logo before the banner and the sign-in" checks; the markup
forbidden-string loops; the `--space-N` step checks; `test_breakpoint_matches_token`,
`test_page_has_no_pure_white_or_black` and every test that isn't in the table.

Rewrite mapping for every line that stays (prep amendment):

| Today | Now |
| --- | --- |
| `_rule(...)` | `SHEET.rule(...)` |
| `_rules()` | `SHEET.rules()` |
| `_tokens()` | `SHEET.tokens()` |
| `_css()` | `SHEET.css` |
| `_style()` (photo `test_page_loads_no_fonts_or_outside_assets`) | `SHEET.style` |
| `_rules_after_root()` (both no-pure-white tests, kiln width check) | `SHEET.rules_after_root()` |
| `_colour(...)` | `SHEET.colour(...)` |
| `_markup()` | `MARKUP` (module constant, `page_style.markup(PAGE_HTML, STYLE_BLOCK[, SCRIPT_BLOCKS])`) |
| `_rem_to_px(...)` | `page_style.rem_to_px(...)` |
| `GLYPH_TOKEN` (kiln `test_error_box_differs_beyond_colour`, photo `test_message_kinds_differ_beyond_colour`) | `page_style.GLYPH_TOKEN` |
| `HOVER_MEDIA` (kiln `test_hover_only_where_hover_exists`, photo `test_controls_have_hover`, `test_busy_buttons_keep_the_disabled_look`) | `page_style.HOVER_MEDIA` |
| `PURE_WHITE_OR_BLACK` (both no-pure-white tests) | `page_style.PURE_WHITE_OR_BLACK` |

Check semantics the builder must keep (prep amendments):

- `contrast_problems` compares the unrounded ratio with `>=` (as today) and rounds only
  in the message, so 4.496 still fails a 4.5 minimum.
- `tokens_only_problems` with an empty `string_words` reports any `"` in a value outside
  `var()` (today's kiln check, which also catches an unbalanced quote); with a non-empty
  `string_words` it checks each `"…"` string's words, then strips them (today's photo
  check).
- `font_shorthand`: match `font:` with the kiln's lookbehind `(?<![\w-])font:` on both
  pages (the photo page's `font(-family)?:` has no lookbehind; no rule today is affected).
- `glyph_exempt` is a prefix match (`name.startswith(glyph_exempt)`), as the photo test
  is today; say so in the docstring.
- `SHEET` is built at import. A malformed style block then fails collection of that page
  file instead of only its style tests. Accepted: the kiln file's `EXPECTED_CSP` already
  indexes `STYLE_BLOCK.findall(PAGE_HTML)[0]` at import. Note it in the module docstring.
- Leave each page file's sections where they are: the style constants stay below the
  tests above them (module globals resolve at call time), so the diff isn't inflated by
  moves.

The kiln file's `STYLE_BLOCK` stays: its CSP tests use it directly. The kiln tests that
loop over `_pages()` (each served page) call `page_style.find_logo` and
`page_style.logo_problems` on each page's footer.

No thin wrappers: neither page file may define `_rule`, `_tokens`, `_colour`, `_contrast`
or any other function from the deleted list, even as a one-line alias (story criterion 1).
A page-specific helper that exists only in one file today (`_pages`, `_directives`,
`_sha256_source`, `_responses_on_every_path`, `_tag`, `_script`, `_event`, `_call`,
`_config`, `_csp`) stays.

Order in each page file: imports, page data constants, `SHEET`, tests. Keep the section
comments, updated to say the helpers come from `tests/page_style.py`.

### How the tests import the module

- `pytest.ini` sets `pythonpath = .` and `layers/common/python`, so the repository root is
  on `sys.path` for every test, including when only one page's tests run
  (`.venv/bin/python -m pytest functions/ceramics/kiln_dropoff_recent_entries_viewer`).
- The page test folders are packages under `functions/` (each level has an
  `__init__.py`), so pytest imports them as `functions.<area>.<name>.tests.<module>`; no
  top-level `tests` module is created by them.
- With `tests/__init__.py`, `tests` is a regular package at the root and is found before
  the `layers/common/python/tests/` folder (README Decision 3). `from tests import
  page_style` then works the same from every test file. The root test modules are
  collected as `tests.test_templates`, `tests.test_workflows`, `tests.test_api_routes`,
  `tests.test_dependabot`, `tests.test_page_style`; the `layers/common/tests/` and
  `layers/common/python/tests/` modules stay top-level (`test_aws`, `test_discourse`, …)
  and their names don't collide.
- The page test files are packaged into their Lambda zips today (each `CodeUri` includes
  its `tests/` folder), so the zip will hold a file that imports `tests.page_style`.
  Nothing imports a test file at runtime, so this changes nothing there.

### docs

The two README sentences and the `docs/CONTRIBUTING.md` sentence listed under "Files to
modify" (the `CLAUDE.md` row is proposed in the pull request, not committed). No change to `docs/README.md`: no service's behavior,
trigger, URL or caller changes.

## Tests

### `tests/test_page_style.py` (new)

Each check gets a passing input and a failing one, so no test passes on a check that
never reports anything. Inputs are small inline CSS strings (a `:root` block and a few
rules) unless stated.

1. `test_from_page_reads_the_one_style_block`: a page with one `<style>` gives its text;
   zero and two blocks raise `ValueError`.
2. `test_root_block_must_be_first_and_only`: a stylesheet starting with a rule, and one
   with two `:root`, raise `ValueError`.
3. `test_colour_follows_references_and_rejects_non_colours`: `--a: #ABCDEF; --b: var(--a);`
   gives `#abcdef` for both; `--c: 1rem;` raises `ValueError`.
4. `test_rules_carry_their_media_condition`: a rule inside `@media (hover: hover)` comes
   back with that condition; `rule()` joins two rules for the same selector; a missing
   selector raises `LookupError`.
5. `test_contrast_matches_wcag`: `#000000` on `#ffffff` is 21.0; `#767676` on `#ffffff`
   is at least 4.5; `mix("#ffffff", "#000000", 0.5)` is `#808080`.
6. `test_contrast_below_4_5_is_reported` (story criterion 4): a sheet with
   `--fg: #777777; --bg: #ffffff;` and the pair `("--fg", "--bg", 4.5)` gives one problem
   naming both tokens; the pair with `#767676` gives none.
7. `test_unused_token_is_reported` (story criterion 4): `--a` defined and read, `--b`
   defined and never read: one problem naming `--b`; with `reserved={"--b": "reason"}`,
   none; a reserved token that is read is reported.
8. `test_undefined_token_is_reported`: `var(--missing)` gives a problem naming it; a sheet
   with no `var()` gives a problem.
9. `test_logo_with_a_missing_path_is_reported` (story criterion 4): the kiln page's logo
   (`find_logo` on its committed `page.html`) gives no problems; the same logo with one
   `<path …/>` other than the icon path removed gives exactly one problem, naming the count; with the icon path removed,
   a problem naming the icon path; `logo_problems("")` gives a problem.
10. `test_logo_with_a_forbidden_attribute_is_reported`: the logo with ` fill="#000"` added
    to a path gives a problem naming `fill`.
11. `test_tokens_only_reports_literals`: a hex colour, `rgb(…)`, a `12px`, an unknown word
    (`whitesmoke`), a quoted string with empty `string_words`, a literal `font-family`,
    and too few declarations are each reported; a clean sheet gives none; a string of
    allowed words passes when `string_words` allows them.
12. `test_token_block_reports_non_tokens`: `color: red` inside `:root`, a missing final
    `;`, a bad font stack and a bad glyph are each reported; `color-scheme: light` is not.
13. `test_defined_once_reports_duplicates`: a duplicate name, a duplicate colour, and an
    unlisted shared literal are each reported; a listed shared literal is not.
14. `test_brand_and_derived_colours_are_checked`: a wrong brand value and a derived token
    off by one channel are each reported.
15. `test_svg_attribute_problems`: an attribute outside the allowed set, and a `fill`
    that isn't `url(#…)` when a pattern is given, are reported.
16. `test_page_style_is_outside_every_packaged_folder` (story criterion 5): read every
    `CodeUri:` and `ContentUri:` value in `template.yaml` and `templates/*.yaml` with a
    regex (they are plain relative paths), resolve each against its template's folder,
    and check that `tests/page_style.py` and `tests/test_page_style.py` are inside none;
    also check that at least one path was found (so a regex that matches nothing fails),
    that the number of `CodeUri:`/`ContentUri:` values equals the number of
    `Type: AWS::Serverless::Function` and `Type: AWS::Serverless::LayerVersion` resources
    (SAM defaults a missing `CodeUri` to the template's folder, which for `template.yaml`
    is the repository root), that each resolved path is an existing directory (a quoted or
    mistyped value would otherwise contain nothing and pass), and that the module is not
    under `layers/common/` or `functions/`. (Prep amendment.)

### The two page test files

No test is added, renamed, deleted, skipped or re-parametrized. Each keeps proving what
it proved, now through the module. Proof of criterion 3: before the first edit, save
`.venv/bin/python -m pytest --collect-only -q <file>` for each file (73 and 113 IDs at
b96cac3); after the change, `comm -23 <(sort before) <(sort after)` prints nothing for
either file and `.venv/bin/python -m pytest -rs` reports no skips.

## Acceptance criteria

1. `tests/page_style.py` defines the token-parsing (`Stylesheet`), colour (`channels`,
   `mix`, `luminance`), contrast (`contrast`, `contrast_problems`), CSS-rule (`rules`,
   `rule`, `declaration_values`) and logo (`find_logo`, `logo_problems`) helpers.
   `grep -nE '^def _(style|css|root_block|rules_after_root|tokens|colour|channels|mix|luminance|contrast|declaration_values|rules|rule|markup|rem_to_px)\b'`
   and `grep -nE '^(CSS_COMMENT|TOKEN|VAR_REFERENCE|HEX_COLOUR|PURE_WHITE_OR_BLACK|FONT_STACK|GLYPH_TOKEN|MEDIA_BLOCK|RULE) ='`
   print nothing for either page test file, and neither do the alias and moved-constant
   greps `grep -nE '^_(style|css|root_block|rules_after_root|tokens|colour|channels|mix|luminance|contrast|declaration_values|rules|rule|markup|rem_to_px) ='`
   and `grep -nE '^(HOVER_MEDIA|ROOT_FONT_PX) ='` (prep amendment). (#137 criterion 1)
2. Each page test file defines only its own data constants and page-specific helpers
   (the lists under "What stays in each page's file" and "stays"). (#137 criterion 2)
3. Every test ID collected from the two page files at b96cac3 (73 and 113) is collected
   after the change, all pass, and none is skipped. (#137 criterion 3)
4. `tests/test_page_style.py` has a test where an unused token, a contrast pair below
   4.5:1 and a logo with a missing path each make the helper report a problem (tests 6,
   7 and 9), and each also shows the passing case. (#137 criterion 4)
5. `tests/page_style.py` is not under `layers/common/` or `functions/`; test 16 passes;
   after `sam build`, `find .aws-sam/build -name 'page_style*'` and
   `grep -rl 'def logo_problems' .aws-sam/build` print nothing. (#137 criterion 5)
6. `git diff --stat origin/stage...HEAD` shows no change to any `page.html`, any
   `lambda_function.py`, `template.yaml`, `templates/*.yaml`, `template-cicd.yaml` or
   `configs/*.json`; the only files changed under `functions/` are the two page test
   files and the two READMEs. (#137 criterion 6)
7. The whole suite passes with more tests than the 1831 at b96cac3 (the new module's
   tests), and no other test's result changes.

## Verification

```bash
# Before the first edit (save the baselines in the scratchpad, not the repo):
.venv/bin/python -m pytest --collect-only -q functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py | grep '::' | sort > "$SCRATCH/kiln-before.txt"
.venv/bin/python -m pytest --collect-only -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py | grep '::' | sort > "$SCRATCH/photo-before.txt"

# After:
.venv/bin/python -m pytest tests/test_page_style.py functions/ceramics/kiln_dropoff_recent_entries_viewer functions/classes/class_photo_upload_page -rs
# (repeat the two collect-only lines into *-after.txt, then:)
comm -23 "$SCRATCH/kiln-before.txt" "$SCRATCH/kiln-after.txt"     # prints nothing
comm -23 "$SCRATCH/photo-before.txt" "$SCRATCH/photo-after.txt"   # prints nothing
.venv/bin/python -m pytest                                        # whole suite, > 1831 passed
sam build; echo "exit $?"                                          # must print exit 0 (no template change, but proves criterion 5)
find .aws-sam/build -name test_kiln_dropoff_viewer_lambda_function.py  # positive control: must print a path (test folders are packaged)
find .aws-sam/build -name 'page_style*'                           # prints nothing
grep -rl 'def logo_problems' .aws-sam/build                       # prints nothing
git diff --stat origin/stage...HEAD                               # criterion 6
```

`cfn-lint` and `sam validate` aren't required (no template changes); run them anyway if
cheap and report the result.

Mutation check (prep amendment: the test-ID comparison proves every test still runs, not
that every check still bites). With a throwaway script in the scratchpad that edits a
`page.html` and restores it (write the mutation, run the one test, write the original
back in a `finally`), make one mutation per replaced check on **each** page
and confirm the named test fails: a brand colour value changed
(`test_brand_tokens_match_the_guide`); a derived token off by one channel
(`test_derived_tokens_follow_the_formula`); a low-contrast `--text`
(`test_colour_pairs_meet_contrast` / `test_brand_colour_pairs_meet_contrast`); an
unread token added to `:root` (`test_every_token_is_used`); a `var(--missing)` in a rule
(`test_every_token_used_is_defined`); `color: red;` added to `:root`
(`test_token_block_holds_only_tokens`); a duplicate colour token
(`test_tokens_are_defined_once`); a hex colour in a rule and a `font: 1rem serif` in a
rule (`test_styles_use_tokens_only`); an extra attribute on an inline `<svg>`
(`test_styles_use_tokens_only`); one non-icon `<path` deleted from the logo
(`test_footer_shows_asmbly_logo` / `test_page_shows_official_logo_in_header`). Afterwards
`git diff -- '*.html'` must be empty. Report the table of mutation, page, test, result.

On the stage stack after deploy: nothing to see. Open the kiln viewer and the class
photo upload page and confirm they look as before; no function code changed, so their
responses are byte-for-byte the same.

## Admin actions

None.

## Hand-off

#138 can rely on: `tests/page_style.py` with the
API above; `from tests import page_style` working from any test file; both page test
files calling `page_style.Stylesheet.from_page(PAGE_HTML, STYLE_BLOCK)` and the `*_problems`
checks with their own data; `logo_problems` checking the official Asmbly logo on both
pages. Note for #138: `test_logo_with_a_missing_path_is_reported` and
`test_logo_with_a_forbidden_attribute_is_reported` in `tests/test_page_style.py` read the
kiln `page.html`'s logo (through `_kiln_logo()`), so moving the logo out of that file
means updating their source too.

What was built (2026-10-17):

- `tests/page_style.py`: `Stylesheet` (`from_page`, `css`, `style`, `root_block()`,
  `rules_after_root()`, `tokens()`, `colour()`, `used_tokens()`, `rules()`, `rule()`);
  `channels`, `mix`, `luminance`, `contrast`, `rem_to_px`, `declaration_values`,
  `markup`, `find_logo`; the checks `brand_colour_problems`, `derived_colour_problems`,
  `contrast_problems`, `unused_token_problems`, `undefined_token_problems`,
  `token_block_problems`, `defined_once_problems`, `tokens_only_problems`,
  `svg_attribute_problems`, `logo_problems`; the constants `CSS_COMMENT`, `TOKEN`,
  `VAR_REFERENCE`, `HEX_COLOUR`, `PURE_WHITE_OR_BLACK`, `FONT_STACK`, `GLYPH_TOKEN`,
  `MEDIA_BLOCK`, `RULE`, `HOVER_MEDIA`, `ROOT_FONT_PX`, `LOGO_START`, `LOGO_PATH_COUNT`,
  `LOGO_ICON_PATH`, `LOGO_FORBIDDEN`.
- `tests/test_page_style.py`: 16 tests, including the packaging guard (test 16).
- Each page file defines `SHEET` and `MARKUP` next to its `STYLE_BLOCK`.
- Test IDs: kiln 73 and photo 113, unchanged; the suite has 1847 (1831 + 16). A mutation
  check of 23 mutations (11 kiln, 12 photo) made each named test fail.
- Deferred: the `CLAUDE.md` map row (proposed in the pull request for the person).
