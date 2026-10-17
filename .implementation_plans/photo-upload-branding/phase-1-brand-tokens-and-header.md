---
phase_id: 1
title: Brand tokens, header, logo and type
epic: 111
implements: [112]
depends_on: []
domain: [lambda, docs]
estimated_size: M
---

# Phase 1: Brand tokens, header, logo and type

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's README, especially **Design rule** and **Decisions** (logo
  source, fonts, CSP, palette, tokens).
- Story #112 and its acceptance criteria; epic #111 (the brand guide screenshots are in
  its body).
- `functions/classes/class_photo_upload_page/page.html`: the `<style>` block (lines
  8–34) and the markup (lines 36–74). The `<script>` blocks are **not changed** in this
  plan.
- `functions/classes/class_photo_upload_page/lambda_function.py`: `render_page`,
  `response_headers` (the CSP this phase leaves exactly as it is).
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: every test
  that pins the page (`test_csp_header`, `test_page_has_public_warning_above_submit`,
  `test_page_shows_stage_banner_text`, `test_page_messages_match_server_messages`,
  `test_page_uses_text_content_not_inner_html`, `test_page_has_one_inline_script_and_style`).
- `functions/classes/class_photo_upload_page/README.md`, "What It Serves".
- The official logo: `asmbly-makerspace/asmbly-classes`, file
  `app/src/lib/components/logo.svelte` at commit
  `9a534a6c538df1e602fead183e30d93d97c247b4`
  (`gh api "repos/asmbly-makerspace/asmbly-classes/contents/app/src/lib/components/logo.svelte?ref=9a534a6c538df1e602fead183e30d93d97c247b4" --jq .content | base64 -d`).
  Its `<svg viewBox="0 0 443.61 122.16">` holds the wordmark paths and the icon path
  (the last `<path>`, starting `m122.16,77.71V0H0v44.44h20.85`).

## Goal

Signed out, signing in, or signed in, the page opens with a full-width Asmbly Purple
header band carrying the official primary horizontal Asmbly logo in Asmbly White, the
title "Class photo upload" and (when signed in) **Sign out**, followed by a decorative
geometric strip in the sub-brand colours. Every colour, tint, font stack, spacing,
radius and size is a design token defined once on `:root` and used everywhere else by
`var()`; a test enforces it. No pure white or black remains; the CSP, the script and
every pinned text are unchanged; the served page stays under 100 KB.

## Files to create

None.

## Files to modify

- `functions/classes/class_photo_upload_page/page.html`:
  - the `<style>` block: the token block on `:root`, then every existing rule rewritten
    to use only tokens, plus new rules for the header band, the logo, the title, the
    pattern strip and the font stacks;
  - the markup above `<p id="dry-run-banner">`: the header band with the inline logo
    SVG, the title and **Sign out**, then the pattern strip SVG. Everything from
    `<p id="dry-run-banner">` down to `</main>` keeps its elements, IDs, classes and
    texts (phase 2 restyles them). The `<script>` blocks are byte-for-byte unchanged.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: the tests
  below.
- `functions/classes/class_photo_upload_page/README.md`: "What It Serves" and "The
  Page" (see Docs below).

## Implementation details

### lambda (page.html; `lambda_function.py` is not changed)

#### The design rule (owner requirement, README "Design rule")

1. The first rule in the stylesheet is `:root { … }`, the **token block**. It is the only
   place a literal colour (`#hex`, `rgb()`, `rgba()`, `hsl()`, a colour keyword), length
   (`px`, `rem`, `em`, `%` other than `0` and `100%`), font stack, line height, duration
   or z-index appears.
2. Every other rule uses tokens through `var(--…)`. Allowed literals outside `:root`:
   `0`, `100%`, `auto`, `none`, `inherit`, `currentColor`, `transparent`, keywords that
   are not colours (`flex`, `solid`, `dashed`, `bold`, …), and the breakpoint in an
   `@media` condition (CSS can't put `var()` there): one breakpoint, `@media (min-width: 40rem)`,
   with a comment saying it must match `--breakpoint-wide` documented in the token block.
3. Each value is defined **once**. A token that means the same thing as another refers
   to it (`--focus-on-dark: var(--woodwork);`, `--radius: var(--space-2);`), so a colour
   literal, a font stack, or a step of the spacing scale is never written twice. (Two
   tokens of different kinds may happen to share a number, such as `--font-size-body: 1rem`
   and `--space-4: 1rem`; they are separate decisions and stay separate tokens.)
4. Brand tokens are named after the brand guide; semantic tokens (what a rule means) are
   built from them. Rules use semantic tokens where one exists.
5. The SVGs carry no colour literals: the logo's paths use `fill="currentColor"` (the band
   sets `color: var(--on-dark)`), and the pattern's shapes carry a class
   (`class="woodwork"`, …) that a rule colours with `fill: var(--woodwork)`. No `style=`
   attribute anywhere (already enforced by `test_page_uses_text_content_not_inner_html`).

#### The token block

Brand colours (from the guide; exact values, upper or lower case as written here):

| Token | Value |
| --- | --- |
| `--asmbly-purple` | `#292D6A` |
| `--asmbly-white` | `#F2F4EF` |
| `--midnight-black` | `#171d1a` |
| `--woodwork` | `#F3B61B` |
| `--metalwork` | `#578BC9` |
| `--lasers` | `#D33E43` |
| `--textiles` | `#79CCC4` |
| `--electronics` | `#00916E` |
| `--printing-3d` | `#EE6E23` |
| `--ceramics` | `#b34a9a` |

Tints and shades, **derived** (README Decision 11): the guide's 20% steps of Asmbly Purple
toward Asmbly White, and the two status shades toward Midnight Black. Each is written as
a hex literal (the value a browser uses; no `color-mix()`), and a comment above the group
gives the formula: `tint(p) = p × purple + (1 − p) × asmbly-white`, per sRGB channel,
rounded; `shade = 0.8 × colour + 0.2 × midnight-black`. The test recomputes each.

| Token | Value | Formula |
| --- | --- | --- |
| `--asmbly-purple-80` | `#515585` | tint 0.8 |
| `--asmbly-purple-60` | `#797d9f` | tint 0.6 |
| `--asmbly-purple-40` | `#a2a4ba` | tint 0.4 |
| `--asmbly-purple-20` | `#caccd4` | tint 0.2 |
| `--lasers-shade` | `#ad373b` | shade of `--lasers` (5.6:1 on Asmbly White) |
| `--electronics-shade` | `#057a5d` | shade of `--electronics` (4.8:1 on Asmbly White) |

(Phase 2 adds the 20% tints of `--lasers` and `--woodwork` for message backgrounds by
the same formula.)

Semantic colour tokens (all `var()` of the above): `--page-bg: var(--asmbly-white)`,
`--text: var(--midnight-black)`, `--brand: var(--asmbly-purple)`,
`--on-dark: var(--asmbly-white)`, `--line: var(--asmbly-purple-40)`,
`--error: var(--lasers-shade)`, `--ok: var(--electronics-shade)`,
`--focus: var(--asmbly-purple)`, `--focus-on-dark: var(--woodwork)`,
`--disabled-bg: var(--asmbly-purple-20)`. `--accent` (ceramics) is removed; its rules
use `--brand`. If a shadow stays, its colour is a token (`--shadow-colour`, an `rgba`
literal of the purple's channels, defined once).

Type: `--font-body: Roboto, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;`
`--font-heading: "Helvetica Neue", "Segoe UI", Roboto, Arial, system-ui, sans-serif;`
with a comment that PP Gosha is the brand face and why it isn't loaded (README
Decision 5); `--font-size-body: 1rem; --font-size-h1: 1.75rem; --font-size-h2: 1.25rem;
--line-height: 1.5; --weight-heading: 700;`. No `@font-face`, no `url(`.

Space and size: a spacing scale `--space-1: 0.25rem; --space-2: 0.5rem; --space-3: 0.75rem;
--space-4: 1rem; --space-5: 1.5rem; --space-6: 2rem;` and semantic sizes built from it or
defined once: `--gutter: var(--space-4)` (16px), `--radius: var(--space-2)`,
`--content-max-width: 47.5rem` (760px, as now), `--logo-height: 3.5rem` (56px; brand
minimum 50px), `--pattern-height: 2.5rem`, `--border-width: 1px`,
`--border-width-strong: 2px`, `--focus-width: 3px`, `--focus-offset: 2px`,
`--tap-target: 2.75rem` (44px, used by phase 2), `--breakpoint-wide: 40rem` (comment
only; see rule 2). The builder may add tokens, never literals outside `:root`.

#### Header band

Replaces today's `<header>` inside `<main>`; it moves out of `<main>` so it spans the
window. Suggested markup:

```html
<header class="brand-band">
  <div class="brand-inner">
    <svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">
      <path fill="currentColor" d="…"/>  <!-- the paths from logo.svelte, d values unchanged -->
    </svg>
    <h1>Class photo upload</h1>
    <button type="button" id="sign-out" class="secondary" hidden>Sign out</button>
  </div>
  <svg class="pattern" aria-hidden="true" focusable="false" viewBox="…" preserveAspectRatio="xMinYMid slice">…</svg>
</header>
```

- The logo SVG: `d` values copied unchanged from `logo.svelte`; drop the Svelte
  attributes (`class={…}`, `id`, `data-name`, `class="cls-1"`); every path
  `fill="currentColor"`; no `<title>` (the `aria-label` names it), no `<script>`, no
  `style=`. `.logo { height: var(--logo-height); width: auto; }`: at 56px it is about
  203px wide, so it fits a 320px screen inside the gutters.
- Clear space: `.brand-inner` has padding of at least `--space-4` on every side,
  `--space-5` from the breakpoint up, `max-width: var(--content-max-width); margin: 0 auto;`
  `display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3) var(--space-5);`
  logo first, title next, **Sign out** pushed right (`margin-left: auto`).
- `.brand-band { background: var(--brand); color: var(--on-dark); }`; the `h1` in it uses
  `--on-dark`.
- **Sign out** (`button.secondary`) on the band: transparent background, `--on-dark`
  text and a `--border-width-strong` `--on-dark` border; its focus ring uses
  `--focus-on-dark`. Phase 2 finishes the button styles; this phase makes it readable on
  purple. `id="sign-out"`, `class="secondary"` and `hidden` stay exactly as now.

#### Pattern strip

An inline SVG redrawn from the brand guide's pattern (README Decision 8): a row of square
tiles on the purple band, each one shape in one sub-brand colour: a square with a quarter
circle, a right triangle, a half-circle "pill", a four-pointed star cut by four quarter
circles, a diagonally split square. Plain `<rect>`, `<path>`, `<circle>`, each with a
class naming its colour (`woodwork`, `metalwork`, `lasers`, `textiles`, `electronics`,
`printing-3d`, `ceramics`, `asmbly-white`); rules `.pattern .woodwork { fill: var(--woodwork); }`
and so on. About 10–12 tiles of 40×40 user units, `viewBox` wide enough for a 1440px
window at `height: var(--pattern-height)`; `preserveAspectRatio="xMinYMid slice"`;
`.pattern { display: block; width: 100%; height: var(--pattern-height); overflow: hidden; }`
so a narrow screen cuts it off on the right. `aria-hidden="true"`, `focusable="false"`.
Under 4 KB. No `<text>`, `<image>`, `href`, `fill="#…"` or `<script>` in it. (SVG
coordinates in `viewBox`, `d`, `x`, `width` are geometry, not CSS values, and are not
tokens.)

#### Signing-in states

The band sits outside `#app`, so it shows while "Signing in…" and "Sign-in didn't
finish. Sign in again." are on screen; **Sign out** stays hidden until the script shows it
(unchanged). Nothing else from `#app` shows.

#### Main

`<main>` keeps its children from `#dry-run-banner` down. Page and content background
`--page-bg` (the card's old `#fff` goes), padding `--space-5`, `margin: var(--gutter)` on
phones and `var(--space-5) auto` with `max-width: var(--content-max-width)` from the
breakpoint up. The existing `.banner`, `.drop-zone`, `.message`, `.warning`, `.result`,
button and `select` rules are re-pointed at tokens with their current shapes (their
literal colours become tokens; `#fff4ce`/`#e0c060`, `#f9eef6`, `#fdf1f1`, `#f6f6f6` become
`--asmbly-purple-20`-based or `--page-bg` for now); phase 2 redesigns them. `opacity: 0.5`
on disabled buttons becomes a token or, better, phase 2's disabled style; in this phase
`--disabled-opacity: 0.5` is acceptable.

#### Size

Today the served page is about 42 KB; the logo adds about 5 KB, the pattern under 4 KB,
the CSS a few KB. Ceiling 100 KB, asserted by a test.

#### What must not change

The `<script nonce="__CSP_NONCE__">` block and the JSON config block, byte for byte; every
element ID the script reads (`page.html` line 565: `sign-out`, `dry-run-banner`,
`signing-in`, `sign-in-problem`, `sign-in-again`, `app`, `class-select`, `class-status`,
`drop-zone`, `photo-input`, `photo-status`, `photo-note`, `preview`, `submit`,
`submit-status`, `result`); the `[hidden] { display: none !important; }` rule; the
warning `<p>` followed directly by the Submit `<button>`; the classes the script sets
(`error`, `ok`, `dragging`, `message`); every text; `lambda_function.py`.

### docs

`functions/classes/class_photo_upload_page/README.md`:

- "What It Serves": replace "no outside fonts or images" with what is embedded: the
  official logo as inline SVG (source repository, file and commit above), a decorative
  pattern SVG redrawn from the brand guide, system font stacks (Roboto where installed;
  PP Gosha not loaded, and why), nothing fetched. The CSP block stays as it is and says
  the branding didn't change it.
- A "Brand and design tokens" subsection: the design rule (tokens once on `:root`, `var()`
  everywhere else, no literals outside, no duplicate values, SVG colours by
  `currentColor` or class), the brand and derived tokens with values and formula, and that
  `test_styles_use_tokens_only` enforces it.
- "The Page", item 1: the purple band with the logo, the title and **Sign out**, then the
  pattern strip; the stage banner under it.

`docs/README.md` is not changed: what the service does, how it is triggered and its URL
are the same.

## Tests

In `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`. Typed
helpers, no new dependency:

- `_style() -> str`: the text of the one `<style nonce=…>` block of `PAGE_HTML`.
- `_root_block() -> str` and `_rules_after_root() -> str`: the `:root { … }` rule (which
  must be the first rule) and everything after it.
- `_tokens() -> dict[str, str]`: `--name: value;` pairs from the root block.
- `_colour(name: str) -> str`: a token's hex value, following `var(--other)` references.
- `_mix(a: str, b: str, p: float) -> str`: `p × a + (1 − p) × b` per sRGB channel, rounded,
  as `#rrggbb`.
- `_contrast(foreground: str, background: str) -> float`: WCAG 2.1 contrast ratio.

Tests:

- `test_page_shows_official_logo_in_header`: exactly one
  `<svg class="logo" role="img" aria-label="Asmbly Makerspace"`, before
  `id="dry-run-banner"` and `id="signing-in"`, with `viewBox="0 0 443.61 122.16"`, and
  containing the icon path prefix `m122.16,77.71V0H0v44.44h20.85` (the official vector).
- `test_logo_meets_brand_minimum`: `--logo-height` resolves to at least 50px (rem × 16)
  and the `.logo` rule's `height` is `var(--logo-height)`.
- `test_pattern_is_decorative`: exactly one `<svg class="pattern"` with
  `aria-hidden="true"` and `focusable="false"`, containing no `<text`, `<image`, `href`,
  `<script` or `fill="#`.
- `test_brand_tokens_match_the_guide`: the ten brand tokens have exactly the guide's
  values (case-insensitive).
- `test_derived_tokens_follow_the_formula`: each `--asmbly-purple-N` equals
  `_mix(purple, asmbly_white, N/100)` and each `-shade` equals
  `_mix(colour, midnight_black, 0.8)` (phase 2 adds its tints to the list).
- `test_styles_use_tokens_only` (the owner's rule): in `_rules_after_root()` there is no
  `#` followed by 3–8 hex digits, no `rgb(`, `rgba(`, `hsl(`, `hsla(`, no colour keyword
  as a value (`(?<![\w-])(white|black|red|green|blue|gray|grey|yellow|purple)(?![\w-])`,
  so `white-space` doesn't match), no length with a unit (`\d*\.?\d+(px|rem|em|vh|vw)`)
  outside the one `@media (min-width: …)` condition, no percentage other than `100%`,
  no `font-family:` with a literal family (only `var(`). The markup outside `<style>` and
  `<script>` has no `fill="#`, `stroke="#`, `style=` or `color=`.
- `test_tokens_are_defined_once`: in the root block no token is defined twice; no two
  tokens share a colour literal (compared as lower-case `#rrggbb`) or a font stack; the
  `--space-*` steps are all different; references with `var()` are not literals.
- `test_every_token_used_is_defined`: every `var(--x)` in the stylesheet names a token
  in the root block (catches a typo that silently falls back).
- `test_page_has_no_pure_white_or_black`: `#fff`, `#ffffff`, `#000`, `#000000` appear
  nowhere in the page (case-insensitive), and `--ceramics` is used only by the pattern.
- `test_brand_colour_pairs_meet_contrast`: for these (foreground, background, minimum)
  pairs, `_contrast` passes: `--text`/`--page-bg` 4.5, `--on-dark`/`--brand` 4.5,
  `--brand`/`--page-bg` 4.5, `--error`/`--page-bg` 4.5, `--ok`/`--page-bg` 4.5,
  `--focus`/`--page-bg` 3.0, `--focus-on-dark`/`--brand` 3.0,
  `--text`/`--disabled-bg` 4.5. Phase 2 adds its pairs.
- `test_page_loads_no_fonts_or_outside_assets`: no `@font-face` or `url(` in `_style()`;
  no `<link`; the only `<img` is the preview, without `src`; no `http://` or `https://`
  outside the `<script>` blocks.
- `test_served_page_is_small`: `len(_call(_event())["body"].encode("utf-8")) < 100 * 1024`.
- Existing tests all pass without edits; `test_csp_header` in particular is unchanged.

## Acceptance criteria

1. The header band, logo, title and pattern appear before the stage banner and the
   "Signing in…" text, and the logo is the official vector at 50px high or more (#112
   AC 1, AC 6; `test_page_shows_official_logo_in_header`, `test_logo_meets_brand_minimum`).
2. The page's colours are the guide's and their derived tints and shades, with no pure
   white or black (#112 AC 2; `test_brand_tokens_match_the_guide`,
   `test_derived_tokens_follow_the_formula`, `test_page_has_no_pure_white_or_black`).
3. **Design rule (owner):** every colour, tint, font stack, spacing, radius and size is a
   token defined once on `:root`; every other rule and both SVGs use tokens
   (`var()`, `currentColor` or a class); no inline styles; no duplicated values
   (`test_styles_use_tokens_only`, `test_tokens_are_defined_once`,
   `test_every_token_used_is_defined`).
4. The pattern strip is decorative, hidden from screen readers, and cannot widen the page
   (#112 AC 3; `test_pattern_is_decorative`, the 320px check in Verification).
5. Headings are bold and at least 1.25 × body size; no font file is loaded (#112 AC 4;
   `test_page_loads_no_fonts_or_outside_assets`).
6. The CSP is unchanged, nothing outside is loaded, the page is under 100 KB, and no admin
   action is needed (#112 AC 5; `test_csp_header` unchanged,
   `test_page_loads_no_fonts_or_outside_assets`, `test_served_page_is_small`).
7. The pairs in `test_brand_colour_pairs_meet_contrast` pass.
8. The README names the logo's source and commit, what the page embeds, the design rule,
   and the CSP (#112 AC 7).

## Verification

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_page
.venv/bin/python -m pytest
```

No template, layer or requirements change, so `cfn-lint`, `sam validate` and `sam build`
are not required; run them anyway if anything outside
`functions/classes/class_photo_upload_page/` changed.

In a browser before the pull request (the look needs no server): render the page with
`lambda_function.render_page({"authDomain": "example.invalid", "clientId": "x", "pageUrl": "https://example.invalid/class-photo-upload", "dryRun": True}, "n")`,
write it to the scratchpad, open it at 1280px and 320px wide (headless Chromium if
available), and check: band and logo, pattern cut off at the right at 320px, no
horizontal scroll, no CSP or CSS errors in the console. The script will try to sign in
and fail; that is expected there. Don't commit screenshots.

On stage after deploy: open `<FacilitiesApiUrl>/class-photo-upload` in a private window:
the band and logo show while signing in; after sign-in **Sign out** shows on the band;
DevTools Console has no CSP violation; Network shows only the page, the sign-in host and
`/class-photo-upload/classes`; at 400% zoom the logo's edges stay sharp.

## Admin actions

None.

## Hand-off

Phase 2 can rely on: the token block and its names (brand, derived, semantic, type, space
and size tokens, including `--tap-target`, `--focus`, `--focus-on-dark`,
`--border-width-strong`); the helpers `_style()`, `_root_block()`, `_rules_after_root()`,
`_tokens()`, `_colour()`, `_mix()`, `_contrast()` and the contrast and derived-token lists
in the test file; the header band (`header.brand-band`) outside `<main>` with **Sign
out** in it; `<main>` holding everything from `#dry-run-banner` down with today's IDs,
classes and order; the script unchanged.
