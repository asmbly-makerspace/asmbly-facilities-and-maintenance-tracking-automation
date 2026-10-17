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

> **Status:** [ ] Pending

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
| `--banner-edge` | `var(--woodwork)` | |
| `--hover-bg` | `var(--asmbly-purple-80)` | Asmbly White on it: 6.4:1 |
| `--control-edge` | `var(--asmbly-purple-60)` | 3.6:1 on Asmbly White (non-text 3:1) |
| `--drag-bg` | `var(--asmbly-purple-20)` | Midnight Black on it: 10.7:1 |
| `--edge-width` | `4px` | message left edges |
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
- Disabled **Submit**: `background: var(--disabled-bg); color: var(--text); border-style: dashed; border-color: var(--control-edge); cursor: not-allowed;`
  no `opacity` (it would lower the text's contrast; remove phase 1's `--disabled-opacity`
  if it is no longer used). Different from enabled by background, dashed border and
  cursor, and the label stays at 10.7:1.
- Focus: `:focus-visible { outline: var(--focus-width) solid var(--focus); outline-offset: var(--focus-offset); }`
  for `button`, `select`, `a`, and `.drop-zone input:focus-visible + label` (the hidden
  file input passes focus to its label, as today). Inside `.brand-band` the outline uses
  `--focus-on-dark`. Never `outline: none` without a replacement.

**Class list** (`select`): `width: 100%; max-width: 100%; min-height: var(--tap-target);`
`border: var(--border-width-strong) solid var(--control-edge); border-radius: var(--radius);`
`background: var(--page-bg); color: var(--text);`. A long class name is cut inside the
select, never widening the page.

**Photo box** (`.drop-zone`): `border: var(--border-width-strong) dashed var(--control-edge);`
`border-radius: var(--radius); padding: var(--space-5);` text centred. `.drop-zone.dragging`:
`background: var(--drag-bg); border-style: solid; border-color: var(--brand);`.

**Messages.** Four kinds, each with a non-colour cue (a left edge, a weight, and a
`::before` glyph that differs per kind). Glyphs are decorative: write them with the
alternative-text syntax so screen readers skip them, with a plain fallback first:
`content: "!"; content: "!" / "";` (a browser that doesn't know the second form keeps
the first). The visible text is unchanged.

| Kind | Selector | Look |
| --- | --- | --- |
| Error | `.message.error` (class status, photo status, `#result` errors, sign-in problem) | `--error` text, bold, `--edge-width` solid `--error` left edge, padding-left `--space-3`, glyph "✕" |
| Success | `.message.ok` (photo OK, "Location data was removed…", "Opened/Updated pull request #N", "Dry run: nothing was opened") | `--ok` text, `--edge-width` solid `--ok` left edge, glyph "✓" |
| Public-on-GitHub warning | `.warning` | `--warning-bg` background, `--text` text, `--edge-width` solid `--error` left edge, bold, glyph "!" |
| Stage banner | `.banner` | `--banner-bg` background, `--text` text, `--edge-width` solid `--banner-edge` left edge, glyph "i" or "⚙" |

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
  `--brand`/`--page-bg` 4.5 (links), `--control-edge`/`--page-bg` 3.0,
  `--focus`/`--page-bg` 3.0, `--focus-on-dark`/`--brand` 3.0, `--text`/`--disabled-bg` 4.5.
- `test_light_tints_carry_dark_text`: every rule whose `background` is a token resolving
  to a tint lighter than 60% (`--*-20`, `--*-40`) sets `color: var(--text)` or inherits it
  (no `--on-dark` in that rule).
- `test_message_kinds_differ_beyond_colour`: `.message.error`, `.message.ok`, `.warning`
  and `.banner` each have a left-edge border (`border-left` with `--edge-width`) and a
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
