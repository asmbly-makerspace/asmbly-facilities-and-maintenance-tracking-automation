---
plan: kiln-dropoff-ceramics-branding
epic: 132
---

# Kiln drop-off ceramics branding: implementation plan

**Created:** 2026-10-17

## Overview

The Recent Kiln Drop-Offs page (`https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer`,
where the ClickUp kiln drop-off form sends members) works but looks dated next to the
restyled class photo upload page (plan `photo-upload-branding`, epic #111). Its colours
are hardcoded and off-brand (a green Refresh button at about 2.9:1, blue IDs at about
4.3:1, both below WCAG AA), it hotlinks a font that never loads (asmbly.org sends no CORS
header) and two images from asmbly.org, and its CSS lives in a Python f-string with
doubled braces.

This plan restyles the page with the same design-token approach as
`functions/classes/class_photo_upload_page/page.html`, with the **ceramics colour**
(`--ceramics` #b34a9a) and its tints and shades as the accent and the **ceramics icon** in
the header band, and the Asmbly logo, base colours and type kept. The list page and the
error page share one shell. What the page lists and how it gets the list do not change:
the SSM, Secrets Manager and ClickUp calls, the 24-hour window, the sort order, the
columns, the texts, `html.escape` on every outside value, and the status codes stay as
they are. The Content-Security-Policy gets tighter: nothing is loaded from asmbly.org any
more, and the one inline style block is allowed by its hash instead of `'unsafe-inline'`.

Only `functions/ceramics/kiln_dropoff_recent_entries_viewer/` changes (its
`lambda_function.py`, a new `page.html`, its tests and its README). No template,
configuration, layer or deploy-role change.

## Design rule

The same rule as `photo-upload-branding` (owner's requirement there, applied here as the
task asks):

- Every brand colour, tint, shade, font stack, spacing, radius and size is a CSS custom
  property defined **once** in the `:root` token block of `page.html`, named after the
  brand guide (`--ceramics`, `--asmbly-white`, `--midnight-black`, …).
- Tints and shades follow one formula (Decision 6), and a test recomputes each.
- Semantic tokens (`--accent`, `--text`, `--page-bg`, `--error-bg`, `--focus`, …) are
  built from the brand tokens with `var()`; rules use them.
- Every rule outside `:root` uses tokens only: no `#hex`, `rgb()`, `hsl()`, colour
  keywords or lengths.
- The inline SVGs carry no colour literals (`fill: currentColor` from a rule). No
  `style=` attributes (the hash-based CSP would block them anyway).

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #133 | Kiln drop-off page: ceramics colours and icon, Asmbly logo and type, readable on a phone | 1 |
| #134 | Kiln drop-off page: the error page carries the same ceramics styling | 1 |

Phase 1 lands both stories: its pull request says `Closes #133`, `Closes #134` and
`Closes #132`.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Ceramics-branded page shell, tokens and tests](phase-1-ceramics-page-shell.md) | lambda, docs | M | [ ] Pending |

## Dependencies

- `photo-upload-branding` (epic #111, complete, on `stage`): the reference for the token
  block, the test helpers (copied, not imported) and the inline Asmbly logo (the official
  vector from `asmbly-makerspace/asmbly-classes` `app/src/lib/components/logo.svelte`,
  commit `9a534a6c538df1e602fead183e30d93d97c247b4`, as already inlined in
  `functions/classes/class_photo_upload_page/page.html`).
- The ceramics icon artwork: `https://asmbly.org/wp-content/uploads/2025/02/ceramics-white.svg`
  (Last-Modified 2025-02-06, 898 bytes, one `<path>` in a `0 0 38.4 38.4` viewBox),
  inlined without its `<style>` and `fill`.
- No phase dependencies (one phase).

## Parallelism

One phase; nothing to run in parallel. Do not build at the same time as a fix for #95,
which would edit the same test file (`test_kiln_dropoff_viewer_lambda_function.py`).

## Admin actions

None. No named resource, secret, parameter, route or deploy-role change.

## Related work

- **Epic #111 / plan `photo-upload-branding`** (complete): the design system this plan
  copies. Its files (`functions/classes/class_photo_upload_page/*`) are not changed; they
  are shared with #114.
- **#95** (open): would change the exception text the ClickUp helper raises and the kiln
  test that pins it (`test_lambda_handler_error_page_hides_exception_text`). Shares the
  kiln test file: sequential only.
- **#79** (open): caller checks on public routes. This page stays public with no caller
  check; this plan doesn't add one.
- **#74, #85** (closed): the escaping, the generic error page and the "no list on the
  error page" rules. Their tests stay and must keep passing (only the pinned CSP value
  and the `@font-face` assertion change, as the tightening requires).
- Open pull requests #68 (templates) and #131 (stage to main): no shared files.

## Out of scope

- Anything the page does: the ClickUp, SSM and Secrets Manager calls, the 24-hour window,
  the sort order, the three columns, the texts, the status codes, the Refresh link.
- **Times are shown in UTC** (`%Y-%m-%d %H:%M:%S` of the UTC timestamp), which members in
  Austin may misread. Changing it is a behaviour change, so it is left for the owner to
  decide (listed in the briefing as a possible follow-up).
- A caller check on the route (#79); the helper's exception text (#95).
- The decorative brand-pattern strip of the photo upload page (Decision 9).
- PP Gosha (Decision 5), a dark theme, printing slips, any script.
- `docs/README.md`: the service's behaviour, trigger, URL and caller configuration don't
  change (Decision 12).

## Security

- **CSP tightened.** Today: `default-src 'none'; style-src 'unsafe-inline'; font-src https://asmbly.org; img-src https://asmbly.org; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
  After: `default-src 'none'; style-src 'sha256-<hash of the one <style> block>'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
  No host, no `data:`, no `script-src`. The hash is computed at import from `page.html`,
  and a test recomputes it from the served body.
- `html.escape` stays on every outside value (task name, custom ID, task ID). The shell
  is filled by plain `str.replace` of two placeholders, main content last, so text from
  ClickUp is never itself searched for a placeholder (a test sends a task named
  `__RELOAD_TEXT__`).
- No script, no `onclick`, no `style=` attribute, no outside URL in the page; tests
  enforce each.
- The error page stays generic: no exception text, list ID or token (the #74 and #85
  tests stay).
- The route stays a public GET with no caller check (#79); no IAM, secret or route change.

## Decisions

Made without asking, inside `/offshore` (2026-10-17).

1. **One phase.** Both stories share one page shell, one stylesheet and one test file;
   splitting the error page into its own phase would be a few lines. Alternative: two
   phases (list page, then error page). Reason: proportionate; the task asked for one.
2. **The shell moves to `page.html`** next to `lambda_function.py`, read once at import,
   with two placeholders (`__RELOAD_TEXT__`, `__MAIN_CONTENT__`). Alternative: keep the
   CSS in the Python f-string. Reason: same layout as the reference page, no `{{ }}`
   doubling, and the token tests parse a plain file. `CodeUri` is the function's folder,
   so `sam build` packages it (checked in Verification).
3. **Accent is the ceramics colour; Asmbly base colours stay.** `--ceramics` fills the
   header band; its 80% shade (`--ceramics-shade`) is the Refresh button and the drop-off
   IDs; its 20% tint is the table header; Asmbly White is the page, Midnight Black the
   text, Asmbly Purple the logo. Alternative: Asmbly Purple as the accent (the photo
   page's choice, #111 Decision 7). Reason: this page serves only ceramics, and the task
   asks for a ceramics theme.
4. **The band is true `--ceramics` (#b34a9a), holding only large text and the icon.**
   Asmbly White on #b34a9a is 4.35:1: enough for large text (3:1) and for the icon
   (non-text, 3:1), not for body text. The band holds only the `h1` (at least 1.5rem,
   bold, at every width) and the icon; the subtitle and everything else sit on Asmbly
   White. Alternative: a darker band (`--ceramics-shade`, 5.70:1). Reason: the brand
   colour itself is what makes the page read as ceramics; a test pins the band's content
   and the h1 size so this can't silently regress.
5. **PP Gosha is dropped; the photo page's system font stacks are used.** It never loads
   today (no CORS header on asmbly.org), and nobody has confirmed its web licence covers
   `facilities.asmbly.org` (#111 open question). Alternative: keep the `@font-face` and
   `font-src`. Reason: no visible change, a tighter CSP, one less outside dependency. A
   follow-up can embed it through `--font-heading` if the licence is confirmed.
6. **Tint and shade formula** (as #111 Decision 11): `tint(p) = p × colour + (1 − p) ×
   asmbly-white`, `shade(p) = p × colour + (1 − p) × midnight-black`, per sRGB channel,
   rounded. Written as hex literals with the formula in a comment; a test recomputes
   each. Values: `--ceramics-shade` (0.8) #944180, `--ceramics-shade-60` (0.6) #753867,
   `--ceramics-40` #d9b0cd, `--ceramics-20` #e5d2de, `--ceramics-10` #ece3e6,
   `--lasers-shade` (0.8) #ad373b, `--lasers-20` #ecd0cd. Alternative: `color-mix()`.
   Reason: older Safari ignores it and would lose the colour and the contrast.
7. **Both images are inlined as SVG.** The Asmbly logo is copied from the photo upload
   page's inline logo (the official vector); the ceramics icon from asmbly.org's
   `ceramics-white.svg`, each with `fill: currentColor` from a rule. `font-src` and
   `img-src` leave the CSP. Alternative: keep hotlinking (needs `img-src
   https://asmbly.org`). Reason: tighter CSP, no WordPress dependency, sharp at any zoom.
8. **`style-src` uses the hash of the style block, not `'unsafe-inline'`.** The style is
   static, so its SHA-256 is computed once at import. Alternative: keep
   `'unsafe-inline'` (allowed by the task) or a per-request nonce (the photo page's
   way). Reason: strictly tighter, deterministic (no per-request work), and it also
   blocks any `style=` attribute.
9. **No brand-pattern strip.** The photo page's strip is a redraw awaiting the official
   file (#111 Decision 8). Reason: keeps the page small and avoids copying an unofficial
   drawing; can be added later with the same tokens.
10. **Contrast is computed by tests** with the WCAG 2.1 formula copied into the kiln test
    file (no new dependency). Pairs and minimums are listed in the phase document and the
    function README.
11. **Test helpers are copied, not shared.** The token and contrast helpers are copied
    from `functions/classes/class_photo_upload_page/tests/test_lambda_function.py` into
    the kiln test file. Alternative: a shared test module. Reason: that file is shared
    with #114's work; extracting a shared module would touch it. A follow-up can dedupe.
12. **`docs/README.md` is not changed.** The service's behaviour, trigger, URL and caller
    configuration are the same; only the function README changes.
13. **Size ceiling**: the page with 50 drop-offs is under 60 KB (`Cache-Control:
    no-store`, no compression: every Refresh downloads it). Today's page is about 6 KB
    plus rows; the inline logo adds about 5 KB.
14. **Times stay in UTC.** Showing Austin time would change the table's contents, which
    the task forbids. Listed for the owner as a possible follow-up.
15. **Header icon is announced as "Ceramics"** (`role="img" aria-label="Ceramics"`), the
    Asmbly logo as "Asmbly Makerspace". Alternative: mark the icon decorative. Reason:
    names the studio for screen-reader users at no cost.
