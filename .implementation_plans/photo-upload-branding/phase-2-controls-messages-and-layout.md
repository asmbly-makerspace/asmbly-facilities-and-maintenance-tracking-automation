---
phase_id: 2
title: Controls, messages, result and layout
epic: 111
implements: [113]
depends_on: [1]
domain: [lambda, docs]
estimated_size: M
---

# Phase 2: Controls, messages, result and layout

> **Status:** [x] Complete — 2026-10-16 on branch feature/photo-upload-branding (prep amendments applied: see the end)

## Required reading

- `CLAUDE.md`; this plan's README (**Design rule**, **Decisions**); phase 1's document and
  its **Hand-off**.
- Story #113 and its acceptance criteria. Loading, progress and retry behaviour belong to
  #114, not here (README Decision 2).
- `functions/classes/class_photo_upload_page/page.html` after phase 1: the token block,
  the rules for `button`, `.button`, `select`, `.banner`, `.drop-zone`, `.message`,
  `.warning`, `.preview`, `.result`; and in the `<script>` (read only, **not changed**):
  `setMessage` (adds `error` or `ok` to `.message` elements, removes both when cleared),
  `renderError` and `renderResult` (build `p.message.ok`, `p.message.error`, plain `p`,
  `ul > li`, `pre`, and links from `pullRequestLink`, all inside `#result`), the drop
  zone's `dragging` class.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py` after phase 1:
  the helpers and the contrast and derived-token lists.
- `.implementation_plans/class-photo-upload/MANUAL_QA.md`: the flows that must behave as
  before.
- WCAG 2.1: 1.4.3 (contrast), 1.4.10 (reflow at 320 CSS px), 1.4.11 (non-text contrast),
  2.4.7 (focus visible), 2.5.5 (target size, used here as 44px).

## Goal

The class list, the photo box, every button, the four kinds of message (error, success,
the public-on-GitHub warning, the stage banner) and the result look finished in the
brand, read at 4.5:1 or better, differ from one another by more than colour, show a clear
focus ring and hover, fit a 320px screen and 200% zoom with no horizontal scroll, and
keep every text, position and behaviour exactly as before. Everything follows phase 1's
design rule (tokens only), and the `<script>` stays unchanged.

## Files to create

None.

## Files to modify

- `functions/classes/class_photo_upload_page/page.html`: the `<style>` block only (new
  tokens in the token block, rewritten component rules). Markup changes are limited to
  adding classes to existing elements if a rule needs one; no element is added between
  `#public-warning` and `#submit`, no ID, text or order changes, and the `<script>`
  blocks are byte-for-byte unchanged.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: the tests
  below.
- `functions/classes/class_photo_upload_page/README.md`: "The Page" and "Testing".

## Implementation details

### lambda (page.html styles)

**New tokens** (in the token block; derived ones by phase 1's formula and added to
`test_derived_tokens_follow_the_formula`):

| Token | Value | Formula / reference |
| --- | --- | --- |
| `--lasers-20` | `#ecd0cd` | `mix(lasers, asmbly-white, 0.2)` |
| `--woodwork-20` | `#f2e8c5` | `mix(woodwork, asmbly-white, 0.2)` |
| `--warning-bg` | `var(--lasers-20)` | Midnight Black on it: 11.8:1 |
| `--banner-bg` | `var(--woodwork-20)` | Midnight Black on it: 14.0:1 |
| `--banner-edge` | `var(--brand)` | 10.2:1 on `--banner-bg` (prep amendment 2; woodwork was 1.6:1) |
| `--hover-bg` | `var(--asmbly-purple-80)` | Asmbly White on it: 6.4:1 |
| `--drag-bg` | `var(--asmbly-purple-20)` | Midnight Black on it: 10.7:1 |
| `--code-bg` | `var(--asmbly-purple-20)` | the dry-run description's `pre`; Midnight Black on it: 10.7:1 |

Tints lighter than 60% (all the `-20` tokens) only ever carry `--text` (Midnight Black),
never Asmbly White: the brand guide's tint rule. Error and success **text** stays on
`--page-bg` (`--error` on `--lasers-20` would be 4.3:1 and `--ok` on a green tint 3.8:1,
both too low).

**Buttons.**

- Primary (`button`, `.button`, i.e. **Submit**, **Choose a photo**, **Sign in again**):
  `background: var(--brand); color: var(--on-dark); border: var(--border-width-strong) solid var(--brand);`
  `min-height: var(--tap-target); padding: var(--space-2) var(--space-5); border-radius: var(--radius);`
  `font-weight: var(--weight-heading)`. Hover (not disabled): `--hover-bg` background and
  border.
- **Sign out** (`button.secondary` on the band): phase 1's outline; hover fills it with
  `--on-dark` and turns its text `--brand`.
- Disabled **Submit**: `background: var(--disabled-bg); color: var(--text); border-style: dashed; border-color: var(--control-border); cursor: not-allowed;`
  no `opacity` (it would lower the text's contrast; remove phase 1's `--disabled-opacity`
  if it is no longer used). Different from enabled by background, dashed border and
  cursor, and the label stays at 10.7:1.
- Focus: `:focus-visible { outline: var(--focus-width) solid var(--focus); outline-offset: var(--focus-offset); }`
  for `button`, `select`, `a`, and `.drop-zone input:focus-visible + label` (the hidden
  file input passes focus to its label, as today). Inside `.brand-band` the outline uses
  `--focus-on-dark`. Never `outline: none` without a replacement.

**Class list** (`select`): `width: 100%; max-width: 100%; min-height: var(--tap-target);`
`border: var(--border-width-strong) solid var(--control-border); border-radius: var(--radius);`
`background: var(--page-bg); color: var(--text);`. A long class name is cut inside the
select, never widening the page.

**Photo box** (`.drop-zone`): `border: var(--border-width-strong) dashed var(--control-border);`
`border-radius: var(--radius); padding: var(--space-5);` text centred. `.drop-zone.dragging`:
`background: var(--drag-bg); border-style: solid; border-color: var(--brand);`.

**Messages.** Four kinds, each with a non-colour cue (a left edge, a weight, and a
`::before` glyph that differs per kind). Glyphs are decorative: write them with the
alternative-text syntax so screen readers skip them, with a plain fallback first:
`content: "!"; content: "!" / "";` (a browser that doesn't know the second form keeps
the first). The visible text is unchanged.

| Kind | Selector | Look |
| --- | --- | --- |
| Error | `.message.error` (class status, photo status, `#result` errors, sign-in problem) | `--error` text, bold, `--border-width-accent` solid `--error` left edge, padding-left `--space-3`, glyph "✕" |
| Success | `.message.ok` (photo OK, "Location data was removed…", "Opened/Updated pull request #N", "Dry run: nothing was opened") | `--ok` text, `--border-width-accent` solid `--ok` left edge, glyph "✓" |
| Public-on-GitHub warning | `.warning` | `--warning-bg` background, `--text` text, `--border-width-accent` solid `--error` left edge, bold, glyph "!" |
| Stage banner | `.banner` | `--banner-bg` background, `--text` text, `--border-width-accent` solid `--banner-edge` left edge, glyph "i" or "⚙" |

Plain status messages ("Signing in…", "Loading classes…", "Submitting…", a class
warning) keep the plain `.message` style: `--text`, no edge, no glyph (README Decision 2:
#114 owns loading behaviour). Don't hide empty `.message` elements with `display: none`:
they are live regions, and hiding them can stop screen readers announcing the next
message.

**Result card** (`.result`): `border: var(--border-width) solid var(--line); border-radius: var(--radius); padding: var(--space-4);`
`background: var(--page-bg)`. Inside: `p, li, pre { overflow-wrap: anywhere; }`,
`pre { white-space: pre-wrap; background: var(--code-bg); color: var(--text); padding: var(--space-3); border-radius: var(--radius); }`,
`a { color: var(--brand); text-decoration: underline; }` and its hover
(`text-decoration-thickness: var(--border-width-strong)`). The first line ("Opened pull
request #N", "Dry run: nothing was opened") takes the success style from `.message.ok`.

**Preview** (`.preview`): `max-width: 100%; height: auto;` within the existing max height
(as a token), `border-radius: var(--radius)`.

**Layout and reflow.** Content flows in one column; nothing has a fixed width larger than
the gutter-adjusted screen. `.brand-inner` wraps (phase 1); the pattern is cut off
(phase 1). Headings and buttons wrap their text. At 320 CSS px (and 1280px at 200%
zoom, which is 640 CSS px) there is no horizontal scroll. Don't use
`overflow-x: hidden` on `body` or `main` to hide an overflow; fix the element.

**Keyboard order** stays the DOM order: **Sign out** (band), the class list,
**Choose a photo** (via the file input), **Submit**, the result's link. No `tabindex`.

### docs

`functions/classes/class_photo_upload_page/README.md`:

- "The Page": one sentence per part on how it looks now (the four message kinds and how
  they differ, disabled **Submit**, the result card), and that the texts are unchanged.
- "Testing": the new style tests (tokens only, contrast pairs computed from the tokens,
  focus, tap targets, message cues), and the manual checks: 320px and 200% zoom, keyboard
  walk-through, WebAIM contrast check of any colour pair the tests don't list.

`docs/README.md`: not changed.

## Tests

In `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`, using phase
1's helpers. A typed helper `_rule(selector: str) -> str` returns the declarations of the
rule whose selector list contains `selector` (exact match of one selector in the list).

- `test_derived_tokens_follow_the_formula` (extended): `--lasers-20` and `--woodwork-20`.
- `test_brand_colour_pairs_meet_contrast` (extended): `--text`/`--warning-bg` 4.5,
  `--text`/`--banner-bg` 4.5, `--text`/`--drag-bg` 4.5, `--text`/`--code-bg` 4.5, `--on-dark`/`--hover-bg` 4.5,
  `--brand`/`--page-bg` 4.5 (links), `--control-border`/`--page-bg` 3.0,
  `--focus`/`--page-bg` 3.0, `--focus-on-dark`/`--brand` 3.0, `--text`/`--disabled-bg` 4.5.
- `test_light_tints_carry_dark_text`: every rule whose `background` is a token resolving
  to a tint lighter than 60% (`--*-20`, `--*-40`) sets `color: var(--text)` or inherits it
  (no `--on-dark` in that rule).
- `test_message_kinds_differ_beyond_colour`: `.message.error`, `.message.ok`, `.warning`
  and `.banner` each have a left-edge border (`border-left` with `--border-width-accent`) and a
  `::before` rule whose `content` glyph differs from the other three; each `::before`
  has the `/ ""` alternative-text form.
- `test_focus_is_visible`: `:focus-visible` rules exist for `button`, `select`, `a` and
  `.drop-zone input:focus-visible + label`, each with `outline` using `var(--focus-width)`
  (which resolves to at least 2px) and a focus colour token; a `.brand-band` focus rule
  uses `--focus-on-dark`; the stylesheet has no `outline: none` and no `outline: 0`.
- `test_tap_targets_are_44px`: `button`, `.button` and `select` set
  `min-height: var(--tap-target)`, and `--tap-target` resolves to at least 44px.
- `test_disabled_submit_differs_beyond_colour`: the `button:disabled` rule sets
  `border-style: dashed` and `cursor: not-allowed`, and the stylesheet has no `opacity`
  on disabled buttons.
- `test_result_text_wraps`: `.result p`, `.result li` and `.result pre` (or one rule
  covering them) set `overflow-wrap: anywhere`; `.result a` sets
  `text-decoration: underline`.
- `test_no_hidden_horizontal_overflow`: no `overflow-x: hidden` on `body`, `html` or
  `main`, and no `tabindex` in the markup.
- Phase 1's `test_styles_use_tokens_only`, `test_tokens_are_defined_once`,
  `test_every_token_used_is_defined`, `test_served_page_is_small` and all the original
  tests (warning above Submit, banner text, messages, CSP, one script and style) pass
  without edits.

## Acceptance criteria

1. Buttons, the class list and the photo box use the brand tokens, with a hover, a focus
   ring of at least 2px at 3:1 or more, a distinct drag look, and a disabled **Submit**
   that differs by more than colour (#113 AC 1; `test_focus_is_visible`,
   `test_disabled_submit_differs_beyond_colour`, contrast pairs).
2. All text pairs reach 4.5:1 (3:1 for large text), and tints lighter than 60% carry
   Midnight Black text (#113 AC 2; `test_brand_colour_pairs_meet_contrast`,
   `test_light_tints_carry_dark_text`, a WebAIM check in Verification).
3. Error, success, warning and banner differ from one another and from plain text by an
   edge and a glyph; "Signing in…", "Loading classes…" and "Submitting…" stay plain, and
   no loading behaviour is added (#113 AC 3; `test_message_kinds_differ_beyond_colour`).
4. Every text, the warning's place directly above **Submit**, and the page's behaviour are
   unchanged (#113 AC 4; the original tests unchanged; the script unchanged in the diff;
   the stage walk-through).
5. No horizontal scroll at 320px or at 200% zoom; header wraps; pattern is cut off;
   **Submit** and **Choose a photo** are at least 44px high (#113 AC 5;
   `test_tap_targets_are_44px`, `test_no_hidden_horizontal_overflow`, Verification).
6. Keyboard order **Sign out**, class list, **Choose a photo**, **Submit**, result link,
   with focus always visible (#113 AC 6; `test_focus_is_visible`, Verification).
7. The result is a card with an underlined link and wrapping text (#113 AC 7;
   `test_result_text_wraps`).
8. The design rule from phase 1 still holds (phase 1's token tests pass).

## Verification

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_page
.venv/bin/python -m pytest
```

No template, layer or requirements change (so `cfn-lint`, `sam validate`, `sam build`
aren't required unless something outside the page's folder changed).

Before the pull request, render the page as in phase 1's Verification, then use the
browser's devtools to show each state by removing `hidden` and adding classes by hand
(no script change): `#app` visible, a `.message.error`, a `.message.ok`, the banner, a
disabled and an enabled **Submit**, `.drop-zone.dragging`, and a `#result` filled with a
long file name, a link and a `pre`. Check at 320px and at 1280px with 200% zoom: no
horizontal scroll, header wraps. Tab through: **Sign out**, class list, **Choose a
photo**, **Submit**, link, each with a visible ring. Check any colour pair the tests
don't list with the WebAIM contrast checker. Don't commit screenshots.

On stage after deploy, in a private window, run the class-photo-upload plan's
`MANUAL_QA.md` flows (sign-in, class list, a wrong photo, a phone photo with location, a
dry-run submit, **Sign out**) and confirm each behaves and reads as before, now in the new
look; repeat the keyboard walk-through and the 320px check on a phone.

## Admin actions

None.

## Hand-off

The page is fully restyled: tokens on `:root` (phase 1 plus this phase's), component
rules for buttons, select, drop zone, the four message kinds and the result card, and the
tests that enforce tokens, contrast, focus, tap targets and message cues. The `<script>`
is unchanged, so #114 can change loading behaviour on top of this styling and should style
any new state with these tokens and message kinds.

As built (only the `<style>` block of `page.html` changed; everything outside it is
byte-for-byte the phase 1 page):

- **New tokens:** `--lasers-20`, `--woodwork-20`; `--hover-bg`, `--drag-bg`, `--code-bg`,
  `--warning-bg`, `--banner-bg`, `--banner-edge` (`--brand`); `--glyph-error` "✕",
  `--glyph-ok` "✓", `--glyph-warning` "!", `--glyph-banner` "i" (each `"x" / ""`);
  `--font-mono`, `--font-size-small`, `--glyph-size` (1.25rem, listed in
  `SHARED_LITERALS` with `--font-size-h2`), `--glyph-offset`, `--underline-offset`.
  `RESERVED_TOKENS` now holds only `--breakpoint-wide`.
- **Message kinds:** a grid (`auto` glyph column, `--track-fill` text column) with a
  `::before` square (`--glyph-size`, Asmbly White glyph on the kind's edge colour). A new
  kind for #114 adds a selector to the shared grid and `::before` rules, a `--glyph-*`
  token, a `border-left: var(--border-width-accent) solid …` and a row in
  `MESSAGE_KINDS`. The banner's "i" uses `--font-mono` so it doesn't read as a capital I.
- **Hover** rules live only in `@media (hover: hover)`; `test_controls_have_hover` fails
  on a `:hover` outside it.
- **Test helpers added:** `_rules() -> list[tuple[str, list[str], str]]` (media
  condition, selectors, declarations, for every rule after `:root`) and
  `_rule(selector: str, media: str = "") -> str` (the declarations of every rule whose
  selector list holds exactly `selector`). New tests: `test_light_tints_carry_dark_text`,
  `test_message_kinds_differ_beyond_colour`, `test_focus_is_visible`,
  `test_tap_targets_are_44px`, `test_controls_have_hover`,
  `test_disabled_controls_differ_beyond_colour` (the planned
  `test_disabled_submit_differs_beyond_colour`, widened to the disabled class list),
  `test_result_text_wraps`, `test_no_hidden_horizontal_overflow`. The new tests were
  mutation-checked: each fails when its rule is broken.
- **Departures from the values above, on purpose:** buttons, the class list, the
  preview and the `pre` use `--radius-control` (4px), not `--radius`, for the crisp
  corners of the brand's geometric tiles (the drop zone and the result card keep
  `--radius`); buttons use `--weight-strong` (600), not `--weight-heading`; the result
  card has `--space-4 --space-5` padding and an Asmbly Purple `--border-width-accent`
  top edge, so it reads as a card; the warning and the banner pad `--space-3 --space-4`,
  the inline error and success messages pad `--space-3` from their edge; `<main>` has no
  card edge (there is no lighter brand surface than Asmbly White, and the band, the
  messages and the result card carry the structure).
- **Verified in headless Chrome with the real CSP** (no console or CSP message): every
  state (signed out, sign-in problem, signed in, class chosen, good photo with preview
  and the location note, each photo error, the class-list error, dragging, submitting,
  the dry-run result with removals, title and description, an opened result, an error
  result) at 1280, 1920, 639 and 320px and at 200% zoom (640px at 2×): no horizontal
  scroll, the longest class name is cut inside the list, the header wraps (the title
  takes two lines at 320px). The keyboard order is **Sign out**, the class list,
  **Choose a photo** (the ring on its label), **Submit**, the result link, each with a
  3px ring (woodwork on the band). Hover looks checked on every control.
- **Colour pairs the tests don't list** (checked by computation, WCAG 2.1): the dashed
  `--control-border` of disabled controls on `--disabled-bg` is 2.5:1 (inactive
  components are exempt from 1.4.11; the dashed style, the tint and the cursor mark
  them); the result card's 1px `--line` on `--page-bg` is 2.2:1 (decorative; the
  card's purple top edge carries it); the banner's woodwork tint on the page is 1.1:1,
  which is why its edge is `--brand`.
- **Left for later:** Safari's native `select` height (not checked here; the README
  says so); the stage walk-through in `MANUAL_QA.md` after deploy.

## Prep amendments (2026-10-16)

`/prep` checked this phase against the code after phase 1 (drift detector and auditor).
These amendments win over the text above where they disagree.

1. **Reuse phase 1's tokens; add no duplicates.** `--control-edge` is phase 1's
   `--control-border` (purple-60, 3.6:1): use `--control-border` wherever this document
   says `--control-edge`. `--edge-width` is phase 1's `--border-width-accent` (4px): use
   `--border-width-accent` for the message edges and don't add `--edge-width` (a second
   `4px` token fails `test_tokens_are_defined_once`). `--disabled-opacity` doesn't
   exist: nothing to remove. `--drag-bg` and `--code-bg` stay as `var()` aliases of
   purple-20 (like `--tint-bg` and `--disabled-bg`), so each use can change on its own.
2. **The banner's edge is `--brand`, not woodwork.** Woodwork is 1.6:1 on
   `--banner-bg` and 1.8:1 on `--page-bg`, so the edge would be nearly invisible.
   `--banner-edge: var(--brand)` (10.2:1 on `--banner-bg`); the woodwork tint stays the
   background. Add the pairs `--banner-edge`/`--banner-bg` 3.0 and `--banner-edge`/`--page-bg` 3.0.
3. **Glyphs are tokens.** A literal string in a rule fails `test_styles_use_tokens_only`,
   and writing it twice (`content: "!"; content: "!" / "";`) duplicates a value. Each
   kind's glyph is one token that holds the whole alternative-text value
   (`--glyph-error: "✕" / "";`, `--glyph-ok: "✓" / "";`, `--glyph-warning: "!" / "";`,
   `--glyph-banner: "i" / "";`, no emoji such as "⚙"), and its `::before` rule is
   `content: var(--glyph-…)`. A browser without the `/ ""` form (Safari before 17.4,
   Firefox before 128) drops the glyph, because a `var()` declaration can't fall back;
   the edge, background and weight still tell the kinds apart, and screen readers never
   read a glyph. The README's "The Page" says so. `test_token_block_holds_only_tokens`
   allows a quoted single glyph followed by `/ ""` for `--glyph-*` tokens only, and
   `test_message_kinds_differ_beyond_colour` checks the four glyph tokens differ.
4. **Hover** (#113 AC 1 asks for one on the class list and the photo box too). Every
   hover rule sits in `@media (hover: hover)` (no number, so
   `test_breakpoint_matches_token` passes), so a tap doesn't leave a hover look on a
   phone, and carries `:not(:disabled)` where the control can be disabled:
   `button`/`.button` take `--hover-bg`; **Sign out** fills with `--on-dark`;
   `select:hover:not(:disabled)` and `.drop-zone:hover` take `border-color: var(--brand)`
   (the box's border only: a drop-target cue, since only **Choose a photo** opens the
   picker). New `test_controls_have_hover` checks these rules exist.
5. **Disabled class list.** `#class-select` is disabled while classes load:
   `select:disabled` takes the disabled Submit's look (`--disabled-bg`, `--text`, dashed
   `--control-border`, `cursor: not-allowed`).
6. **Light tints name their text colour.** `test_light_tints_carry_dark_text` requires
   an explicit `color: var(--text)` in every rule whose `background` resolves to a tint
   lighter than 60% ("or inherits it" can't be checked from the stylesheet).
7. **Message weights and spacing.** Error and warning text use `--weight-strong`;
   success and banner text the body weight. Every kind pads its text `--space-3` from
   its edge. The drop zone's children ignore the pointer while dragging
   (`.drop-zone.dragging * { pointer-events: none; }`) so the drag look doesn't flicker
   as the pointer crosses the text.
8. **Order inside `button, .button`:** `font: inherit` first, then `font-weight`
   (the shorthand resets the weight). If **Sign out** with the new padding pushes the
   title to three lines at 320px, give `.secondary` a smaller padding.
9. **Phase 1's tests change in these ways only, never loosened:** delete the
   `RESERVED_TOKENS` entries for `--asmbly-purple-80` and `--tap-target` (now used); add
   the new non-colour keywords (`underline`, `anywhere`, …) to `ALLOWED_VALUE_WORDS`;
   add `--lasers-20` and `--woodwork-20` to `DERIVED_COLOURS` and only the new pairs to
   `CONTRAST_PAIRS` (the warning, banner, drag, code and hover pairs, the banner edge,
   and Asmbly White on `--error` and `--ok` if a glyph sits on them; the others already
   exist); update the token block's formula comment to cover the lasers and woodwork
   tints. `_rule(selector)` is a new helper in this phase, not phase 1's, and it also
   finds rules inside `@media`. The band's focus rule sets
   `outline-color: var(--focus-on-dark)` over the base outline, which
   `test_focus_is_visible` accepts. Add `a:focus-visible`.
10. **Verification:** walk the keyboard order in Chrome or Firefox (Safari skips buttons
    and links on Tab unless "Press Tab to highlight each item" is on). Check 639px as
    well as 640px (1280px at 200% zoom is exactly the breakpoint). Safari may ignore
    `min-height` on a native `select`; note it if so (`appearance: none` would need a
    `url()` arrow, which the page forbids).
