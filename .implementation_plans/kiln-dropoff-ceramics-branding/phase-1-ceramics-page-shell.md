---
phase_id: 1
title: Ceramics-branded page shell, tokens and tests
epic: 132
implements: [133, 134]
depends_on: []
domain: [lambda, docs]
estimated_size: M
---

# Phase 1: Ceramics-branded page shell, tokens and tests

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's README, especially **Design rule**, **Security** and
  **Decisions** (accent, band contrast, fonts, inline SVGs, hash-based CSP, formula).
- Stories #133 and #134 and their acceptance criteria; epic #132.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py`:
  `RESPONSE_HEADERS` (line 21), `_render_page` (32–138, the shell and the f-string CSS
  this phase replaces), `generate_html_page` (141–183), `generate_error_page` (186–192),
  `html_response` and `lambda_handler` (195 on, **not changed**).
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`:
  every test. The #74 and #85 tests stay; only `EXPECTED_CSP` (line 263),
  `test_page_external_urls_are_covered_by_csp` (315) and the `'@font-face {'` assertion in
  `test_pages_have_no_unformatted_braces` (324) change, as listed below.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md`, "Errors and security
  headers" and "Testing".
- The reference: `functions/classes/class_photo_upload_page/page.html` (the `:root`
  token block, lines 8–113; the base rules after it; the inline logo `<svg class="logo"
  …>` at line 258) and
  `functions/classes/class_photo_upload_page/tests/test_lambda_function.py` lines
  330–760 (the regexes, `_style`, `_css`, `_root_block`, `_tokens`, `_colour`, `_mix`,
  `_luminance`, `_contrast`, `_rules`, `_rule`, `_markup`, `_rem_to_px`, and the token,
  contrast, focus, tap-target and overflow tests). **Read-only: don't edit either file**
  (shared with #114).
- The ceramics icon: `https://asmbly.org/wp-content/uploads/2025/02/ceramics-white.svg`
  (`viewBox="0 0 38.4 38.4"`, one `<path class="st0" d="M0,0v38.4h38.4V0H0ZM24.1,17.2…"/>`
  inside `<g id="Ceramics">`, coloured by an embedded `<style>`). Fetch it with
  `curl -s` into the scratchpad; copy only the `d` attribute.

## Goal

The list page, the empty list and the error page share one shell, `page.html`: a
full-width `--ceramics` header band with the ceramics icon and the title in Asmbly White,
content on Asmbly White in Midnight Black, ceramics-shade drop-off IDs and Refresh button,
a ceramics-tint table header, a brand-palette error box, and the Asmbly logo in Asmbly
Purple at the foot. Every colour and size is a token defined once; every
text/background pair meets WCAG AA by test; the page fits a 320px screen; nothing is
loaded from another site and the CSP is tighter. The handler's data flow is unchanged.

## Files to create

- `functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html`: the page shell
  (doctype, head, one `<style>` block, header band, `__MAIN_CONTENT__`, the reload
  section with `__RELOAD_TEXT__`, the footer logo). About 9 KB.

## Files to modify

- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py`: load
  `page.html` at import, build the CSP with the style hash, render by placeholder
  replacement; delete the f-string shell. `generate_html_page`'s rows and texts,
  `generate_error_page`'s texts, `html_response` and `lambda_handler` keep their
  behaviour.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`:
  update the three pinned assertions; add the token, contrast, layout, CSP-hash and
  shell tests below.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md`: new "Look and brand
  tokens" section; updated CSP and Testing text.

## Implementation details

### lambda: `lambda_function.py`

Module level, after the environment variables:

```python
PAGE_PATH = pathlib.Path(__file__).with_name("page.html")
PAGE_TEMPLATE: str = PAGE_PATH.read_text(encoding="utf-8")
_STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)

def _style_hash(page: str) -> str:
    """The CSP source for the page's one inline <style> block: 'sha256-<base64 digest>'."""
```

- `_style_hash` finds exactly one `<style>` block (raise `ValueError` at import if there
  are zero or several, so a broken `page.html` fails the deploy's first request loudly
  rather than serving an unstyled page), takes its text exactly as written (no
  stripping: the browser hashes the element's text content byte for byte), and returns
  `"'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"`.
- `RESPONSE_HEADERS` keeps `Content-Type`, `X-Content-Type-Options` and `Cache-Control`
  unchanged; `Content-Security-Policy` becomes
  `f"default-src 'none'; style-src {_style_hash(PAGE_TEMPLATE)}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"`.
  No `font-src`, no `img-src`, no `'unsafe-inline'`. Update the comment above it.
- `_render_page(main_content: str, reload_text: str) -> str` keeps its signature and
  docstring contract (both arguments trusted HTML) and returns
  `PAGE_TEMPLATE.replace("__RELOAD_TEXT__", reload_text).replace("__MAIN_CONTENT__", main_content)`:
  **main content last**, so escaped text from ClickUp is never searched for a
  placeholder. Each placeholder appears exactly once in `page.html` (a test checks).
- `generate_html_page`: same rows, same `html.escape` calls, same `custom_id or id`
  fallback, same date format, same texts, same `class="task-id"` and
  `class="no-tasks"`. Markup changes allowed: the subtitle and instructions keep their
  texts and classes; the table gets a wrapper only if needed for layout (no
  `overflow: hidden`, no horizontal scroller). Keep `<td class="task-id">{display_id}</td>`
  byte for byte (pinned by `test_generate_html_page_null_custom_id_shows_task_id`).
- `generate_error_page`: same `<h2>An Error Occurred</h2>`, same
  `<p>Could not retrieve the list of submissions.</p>`, same reload text, class
  `error-box` kept; it gets the error styling from tokens (below).
- New imports: `base64`, `hashlib`, `pathlib`, `re`. Lazy logging and handler flow are
  untouched; nothing new is logged.
- `lambda_handler`: **no change** (environment checks, SSM, secret, ClickUp call, sort,
  status codes).

### `page.html`

Structure (no `<script>`, no `<link>`, no `style=`, no `http://` or `https://` anywhere):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Recent Kiln Drop-Offs</title>
<style>
  :root { …tokens… }
  …rules…
</style>
</head>
<body>
<header class="brand-band">
  <div class="brand-inner">
    <svg class="ceramics-icon" role="img" aria-label="Ceramics" viewBox="0 0 38.4 38.4" focusable="false"><path d="M0,0v38.4h38.4V0H0Z…"/></svg>
    <h1>Recent Kiln Drop-Offs</h1>
  </div>
</header>
<main class="container">
__MAIN_CONTENT__
  <div class="reload-section">
    <p class="reload-text">__RELOAD_TEXT__</p>
    <a class="reload-button" href="">Refresh</a>
  </div>
</main>
<footer class="site-footer">
  <svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">…paths copied from the photo page…</svg>
</footer>
</body>
</html>
```

- `<h1>Recent Kiln Drop-Offs</h1>` exactly (pinned by tests). Exactly one
  `class="container"` (pinned by `test_generate_error_page_shows_no_list_or_empty_message`).
- `<a class="reload-button" href="">Refresh</a>` exactly (pinned on every path).
- The `<style>` element has no attributes (the hash covers its text; no nonce).
- Neither SVG has a `fill`, `stroke`, `style`, `<style>`, `xmlns`, `href` or `<image>`;
  the icon keeps its single path (the square with the pot cut out, so the band colour
  shows through the pot).
- Body text must not contain `401`, `123456789`, `None`, `boom` or `Error details`
  (asserted by the #74 tests on the error page); the copied SVG paths don't, check again
  after copying.

### Tokens (`:root`, defined once)

Brand (values from the brand guide, as in the photo page):
`--asmbly-purple: #292D6A; --asmbly-white: #F2F4EF; --midnight-black: #171d1a;
--ceramics: #b34a9a; --lasers: #D33E43;`

Derived (comment the formula above them, README Decision 6):
`--ceramics-shade: #944180;` (0.8, Midnight Black) ·
`--ceramics-shade-60: #753867;` (0.6, Midnight Black) ·
`--ceramics-40: #d9b0cd; --ceramics-20: #e5d2de; --ceramics-10: #ece3e6;` (tints on Asmbly White) ·
`--lasers-shade: #ad373b;` (0.8) · `--lasers-20: #ecd0cd;`

Semantic (all `var()`):
`--page-bg` → asmbly-white · `--text` → midnight-black · `--accent` → ceramics ·
`--on-accent` → asmbly-white · `--accent-strong` → ceramics-shade (IDs, button) ·
`--accent-hover` → ceramics-shade-60 · `--table-head-bg` → ceramics-20 ·
`--row-hover-bg` → ceramics-10 · `--line` → ceramics-40 · `--focus` → ceramics-shade-60 ·
`--logo-colour` → asmbly-purple · `--error-bg` → lasers-20 · `--error-edge` → lasers-shade ·
`--glyph-error: "✕" / "";`

Type and sizes (same names and stacks as the photo page where they mean the same):
`--font-body`, `--font-heading`, `--font-mono` (the photo page's stacks verbatim),
`--font-size-body: 1rem; --font-size-h1: 1.75rem; --font-size-h2: 1.25rem;
--font-size-id: 1.25rem; --line-height; --line-height-heading; --weight-heading: 700;
--weight-strong: 600;` spacing `--space-1 … --space-6` (0.25, 0.5, 0.75, 1, 1.5, 2rem),
`--gutter`, `--radius`, `--content-max-width: 50rem; --icon-height: 3rem;
--logo-height: 2.5rem; --border-width: 1px; --border-width-accent: 4px;
--focus-width: 3px; --focus-offset: 2px; --tap-target: 2.75rem;`
Add a token only when a rule uses it (a test checks every token is used).

### Rules (tokens only)

- `body`: `--page-bg`, `--text`, `--font-body`, `--font-size-body`, `--line-height`,
  margin 0. `* { box-sizing: border-box; }`.
- `.brand-band`: background `--accent`, colour `--on-accent`. `.brand-inner`: max width
  `--content-max-width`, centred, padding `--space-4 --gutter`, flex, gap `--space-4`,
  `align-items: center`, `flex-wrap: wrap`. `.ceramics-icon`: height `--icon-height`,
  `width: auto`, `fill: currentColor`, `flex: none`. `.brand-band h1`: `--font-heading`,
  `--weight-heading`, `--font-size-h1`, colour `--on-accent`, margin 0. **The band holds
  only the icon and the h1** (Decision 4), and `--font-size-h1` is at least 1.5rem at
  every width (no media query shrinks it).
- `.container` (main): max width `--content-max-width`, margin `0 auto`, padding
  `--space-5 --gutter`; no box shadow, no pure-white card (the page is Asmbly White).
- `.subtitle`, `.instructions`: colour `--text`; instructions weight `--weight-strong`,
  centred.
- `table`: `width: 100%`, `border-collapse: collapse`. `th, td`: padding
  `--space-3 --space-2`, `text-align: left`, bottom border
  `--border-width solid --line`, `overflow-wrap: anywhere`, no `white-space: nowrap`.
  `th`: background `--table-head-bg`, colour `--text`, `--font-heading`,
  `--weight-heading`. `.task-id`: `--font-mono`, `--font-size-id`, `--weight-heading`,
  colour `--accent-strong`. `.no-tasks`: centred, colour `--text`.
- `@media (hover: hover) { tbody tr:hover { background: var(--row-hover-bg); } … }`:
  hover looks only where hover exists.
- `.reload-section`: centred. `.reload-button`: `display: inline-flex`,
  `align-items: center`, `min-height: --tap-target`, `min-width: --tap-target`, padding
  `--space-3 --space-6`, background `--accent-strong`, colour `--on-accent`, radius
  `--radius`, `--font-heading`, `--weight-heading`, no underline. Hover (inside
  `(hover: hover)`): background `--accent-hover`. `.reload-button:focus-visible`:
  `outline: var(--focus-width) solid var(--focus); outline-offset: var(--focus-offset)`.
  No `outline: none` anywhere.
- `.error-box`: background `--error-bg`, colour `--text`,
  `border-left: var(--border-width-accent) solid var(--error-edge)`, radius `--radius`,
  padding `--space-4`; `.error-box h2`: `--font-size-h2`, `--weight-heading`, colour
  `--text`, margin; `.error-box h2::before { content: var(--glyph-error); … }` so the
  error differs by more than colour.
- `.site-footer`: centred, padding `--space-6 --gutter`. `.logo`: height
  `--logo-height`, `width: auto`, `max-width: 100%`, `fill: currentColor`, colour
  `--logo-colour`.
- No `overflow: hidden` / `overflow-x: hidden` on `html`, `body`, `main` or the table.
- The single `@media` condition used is `(hover: hover)` (no numeric breakpoint).

### Contrast pairs (each one a test case and a README row)

| Foreground | Background | Where | Minimum | Ratio |
| --- | --- | --- | --- | --- |
| `--on-accent` | `--accent` | h1 and icon in the band | 3.0 (large text, non-text) | 4.35 |
| `--text` | `--page-bg` | body text | 4.5 | 15.45 |
| `--accent-strong` | `--page-bg` | drop-off IDs | 4.5 | 5.70 |
| `--accent-strong` | `--row-hover-bg` | IDs on a hovered row | 4.5 | 5.02 |
| `--text` | `--row-hover-bg` | text on a hovered row | 4.5 | 13.61 |
| `--text` | `--table-head-bg` | table header | 4.5 | 11.90 |
| `--on-accent` | `--accent-strong` | Refresh button | 4.5 | 5.70 |
| `--on-accent` | `--accent-hover` | Refresh button, hover | 4.5 | 7.53 |
| `--text` | `--error-bg` | error box text | 4.5 | 11.79 |
| `--error-edge` | `--page-bg` | error box edge | 3.0 | 5.60 |
| `--focus` | `--page-bg` | focus outline | 3.0 | 7.53 |
| `--logo-colour` | `--page-bg` | Asmbly logo | 3.0 | 11.30 |

## Tests

In `test_kiln_dropoff_viewer_lambda_function.py`. Add type hints to new tests and
helpers. Copy (don't import) the helpers listed in Required reading, adapted to read the
**rendered** pages (`generate_html_page([])`, a page with tasks, `generate_error_page()`)
and `page.html`.

Changed (the tightening requires it; say so in the PR):

- `EXPECTED_CSP` / `EXPECTED_HEADERS`: the new policy, with the hash recomputed in the
  test from `page.html`'s `<style>` text (not copied from the module).
- `test_page_external_urls_are_covered_by_csp` → `test_pages_load_nothing_from_outside`:
  no `http://`, `https://`, `<img`, `<link`, `@font-face`, `url(` or `<script` in any of
  the three pages.
- `test_pages_have_no_unformatted_braces`: keep the `{{`/`}}` checks; replace the
  `'@font-face {'` assertion with "the page has its `:root {` token block" and "no
  `__MAIN_CONTENT__` or `__RELOAD_TEXT__` is left in any page".

New:

- `test_csp_style_hash_matches_served_style`: for every path in
  `test_lambda_handler_sets_csp_header`'s set, the `style-src` hash in the header equals
  the SHA-256 of the one `<style>` element's text in that body; the CSP has no
  `'unsafe-inline'`, `font-src`, `img-src`, `script-src`, `data:` or host.
- `test_csp_is_no_looser_than_before`: every directive in the new policy is
  `'none'` or the style hash, and the policy still has `default-src 'none'`,
  `base-uri 'none'`, `form-action 'none'`, `frame-ancestors 'none'`.
- `test_style_hash_rejects_zero_or_two_style_blocks`: `_style_hash` raises `ValueError`
  for a page without `<style>` and with two.
- `test_placeholder_in_task_name_is_shown_as_text`: a task named `__RELOAD_TEXT__` and
  one named `__MAIN_CONTENT__` appear literally in the row, and the reload text appears
  once.
- `test_page_template_has_each_placeholder_once`.
- `test_header_band_shows_ceramics_icon_and_title`: the band contains, in order, the
  `<svg class="ceramics-icon" role="img" aria-label="Ceramics"` element and
  `<h1>Recent Kiln Drop-Offs</h1>`, and no other text; the icon's path `d` starts
  `M0,0v38.4h38.4V0H0Z`.
- `test_footer_shows_asmbly_logo`: `<svg class="logo" role="img" aria-label="Asmbly Makerspace"`
  is present in every page, with the same `viewBox` and path count as the photo page's
  logo; `.logo` is coloured by `--logo-colour`.
- `test_error_page_shares_the_shell`: the error page contains the same band, icon, logo
  and reload button markup as the list page (compare the text before `__MAIN_CONTENT__`
  and after it in the template with both rendered pages).
- `test_brand_tokens_match_the_guide`; `test_derived_tokens_follow_the_formula`
  (parametrized: each derived token, its two parents and its share).
- `test_styles_use_tokens_only`; `test_token_block_holds_only_tokens`;
  `test_tokens_are_defined_once`; `test_every_token_is_used`;
  `test_every_token_used_is_defined` (as the photo page, adapted: allowed value words and
  SVG attributes for this page).
- `test_page_has_no_pure_white_black_or_old_colours`: no `#fff`, `#ffffff`, `#000`,
  `#000000`, `white`, `black`, `#27ae60`, `#229954`, `#2980b9`, `#e8ecef`, `#c0392b`,
  `#e74c3c`, `#fbeae5`, `#333`, `#555` in any page; `--asmbly-purple` is used only by
  `--logo-colour`.
- `test_ceramics_is_the_accent`: `--accent` resolves to `--ceramics`; `.brand-band`,
  `.reload-button`, `th` and `.task-id` use `--accent`, `--accent-strong` or
  `--table-head-bg`.
- `test_colour_pairs_meet_contrast` (parametrized from the table above).
- `test_band_text_is_large`: `--font-size-h1` ≥ 1.5rem (24px) and `--weight-heading` ≥
  700, and no rule inside an `@media` changes the h1's size.
- `test_headings_are_bold_and_larger_than_body`.
- `test_reload_button_is_a_44px_target_with_visible_focus`: `min-height` and `min-width`
  `var(--tap-target)` ≥ 44px; the `:focus-visible` outline rule; no `outline: none|0`.
- `test_hover_only_where_hover_exists`: every `:hover` selector is inside
  `@media (hover: hover)`.
- `test_table_text_wraps_and_page_does_not_scroll_sideways`: `th, td` have
  `overflow-wrap: anywhere`; no `white-space: nowrap`, no fixed `width` other than
  `100%`, no `overflow(-x): hidden` on `html`, `body`, `main`, `table`.
- `test_error_box_differs_beyond_colour`: the edge rule, the glyph rule and the
  `--glyph-error` token.
- `test_page_with_50_dropoffs_is_under_60kb`.
- `test_page_html_is_packaged_next_to_the_handler`: `PAGE_PATH` exists in the function
  folder (the template's `CodeUri`).

Unchanged and still passing: every other existing test (escaping, null `custom_id`,
error page hides exception text, empty token, missing environment variables, the error
page shows no list, `Refresh` link on every path, `test_lambda_handler_success`'s calls).

## Acceptance criteria

1. The list, empty and error pages render the band (`--ceramics`, icon, h1), the
   Asmbly logo in Asmbly Purple, and the token-styled table, button and error box
   (#133 AC1, AC2; #134 AC1).
2. Every pair in the contrast table meets its minimum by test (#133 AC3; #134 AC2).
3. The layout tests pass: wrapping cells, no sideways overflow, 44px Refresh target,
   visible focus, hover only under `(hover: hover)` (#133 AC4; #134 AC5).
4. Rows, order, texts, escaping and the handler's calls are unchanged; every #74 and #85
   test passes unchanged (#133 AC5; #134 AC3).
5. The CSP is the hashed policy with no outside source; the page has no script, no
   `style=`, no outside URL; both 500 and 200 responses carry the same headers; the
   50-row page is under 60 KB (#133 AC6; #134 AC4).
6. The token tests pass and the README documents the tokens, formula, sources of the
   icon and logo, the contrast table and the policy as served (#133 AC7).

## Verification

```bash
.venv/bin/python -m pytest functions/ceramics/kiln_dropoff_recent_entries_viewer
.venv/bin/python -m pytest
sam build   # then confirm .aws-sam/build/KilnDropoffRecentEntriesViewerFunction/page.html exists
```

No template change, so `cfn-lint` and `sam validate` are not required (run them anyway
if cheap). Locally, render the three pages to files in the scratchpad
(`generate_html_page([...fixture...])`, `generate_html_page([])`,
`generate_error_page()`) and open them in a browser at 320px, 375px, 768px and desktop
width and at 200% zoom: no sideways scroll, wrapped names, sharp icon and logo. A local
file has no CSP header, so CSP is checked on stage.

After the stage deploy, open `<FacilitiesApiUrl of AsmblyFacilitiesMaintTrackingStack-stage>/KilnOpsDropoffRecentEntriesViewer`
on a phone (or DevTools at 320px): the band, icon, table and Refresh button look as
described; Refresh reloads; DevTools shows the CSP header as planned, **no CSP
violation** in the console, and the network panel shows only the page request (a
`/favicon.ico` request blocked or 403 is pre-existing and not caused by this change).
The stage page lists real members' names: don't screenshot the rows (crop them, or use
an empty or error state). Prod changes only after `/promote`.

## Admin actions

None.

## Hand-off

Fill in when done: the final token list, the CSP as served, any deviation from this
document and why.
