---
plan: photo-upload-branding
epic: 111
---

# Photo upload branding: implementation plan

**Created:** 2026-10-16

## Overview

The class photo upload page (`https://facilities.asmbly.org/class-photo-upload`, built
by the `class-photo-upload` plan, epic #73) works, but the owner finds it "very plain and
looking juvenile" (#111). This plan restyles it to Asmbly's brand guide (the screenshots
in #111): a full-width Asmbly Purple band with the official Asmbly logo, the brand's
geometric pattern, the brand palette with derived tints, brand-like type, and finished,
accessible controls, messages and result card. Nothing the page does changes: the
script, the texts, the CSP, the routes and the API stay as they are. All styling lives
in design tokens on `:root` (the owner's design rule below), enforced by tests.

Only `functions/classes/class_photo_upload_page/page.html`, its tests and its README
change. No template, configuration, layer or deploy-role change.

## Design rule

The owner's requirement (relayed 2026-10-16): no hardcoded colours or magic values
scattered through the page.

- Every brand colour, tint, font stack, spacing, radius and size is a CSS custom property
  defined **once** in the `:root` token block, named after the brand guide
  (`--asmbly-purple`, `--asmbly-white`, `--midnight-black`, `--woodwork`, …).
- Tints and shades are derived by one formula (README Decision 11) and a test recomputes
  them.
- Semantic tokens (`--brand`, `--text`, `--page-bg`, `--error`, `--focus`, …) are built
  from the brand tokens with `var()`; rules use them.
- Every rule outside `:root` uses tokens only: no `#hex`, `rgb()`, `hsl()`, colour
  keywords or lengths (the one `@media` breakpoint is the documented exception, because
  CSS can't put `var()` there).
- The inline SVGs carry no colour literals: the logo uses `currentColor`, the pattern's
  shapes use classes that rules colour with tokens. No `style=` attributes.
- No value is defined twice: a token that means the same thing as another refers to it.

Enforced by `test_styles_use_tokens_only`, `test_tokens_are_defined_once`,
`test_every_token_used_is_defined`, `test_brand_tokens_match_the_guide` and
`test_derived_tokens_follow_the_formula` (phase 1).

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #112 | Class photo upload page: Asmbly logo, colours and type | 1 |
| #113 | Class photo upload page: branded, readable controls, messages and result | 2 |

The pull request that lands phase 1 says `Closes #112`; the one that lands phase 2 says
`Closes #113` and `Closes #111`. Inside `/offshore` both phases land in one pull request,
which closes all three.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Brand tokens, header, logo and type](phase-1-brand-tokens-and-header.md) | lambda, docs | M | [x] Complete |
| 2 | [Controls, messages, result and layout](phase-2-controls-messages-and-layout.md) | lambda, docs | M | [ ] Pending |

## Dependencies

- The `class-photo-upload` plan (epic #73): complete and on `stage`; this plan restyles
  its page.
- The official logo vector in `asmbly-makerspace/asmbly-classes`
  (`app/src/lib/components/logo.svelte`, commit
  `9a534a6c538df1e602fead183e30d93d97c247b4`), read with `gh api`; copied into the page,
  not linked.
- Phase 2 depends on phase 1 (its tokens, header and test helpers).

## Parallelism

Phases 1 and 2 have a dependency, and both modify `page.html`, its test file and its
README: sequential only.

## Admin actions

None. No named resource, secret, parameter, route or deploy-role change.

## Related work

- **#114** (open, the owner's): "slow Neon reads (cache the class list) and better loading
  UX". It owns new loading, progress and retry behaviour and the class-list cache, and
  will likely change the page's `<script>` and add states. Shares
  `functions/classes/class_photo_upload_page/page.html` and its tests with this plan:
  don't build the two at the same time. This plan leaves the script unchanged so #114 can
  build on top and style new states with these tokens and message kinds.
- **`class-photo-upload` plan** (complete): built the page; its `MANUAL_QA.md` is the
  behaviour checklist for phase 2's stage walk-through.
- **`functions/ceramics/kiln_dropoff_recent_entries_viewer`**: hotlinks PP Gosha and
  logos from asmbly.org. Not a pattern to copy here (README Decision 4); not changed.
- Open pull request #68 (template linting) touches templates only: no overlap.

## Out of scope

- New loading, progress or retry behaviour and caching the Neon class list (#114).
- The 400 and 500 error pages `lambda_function.py` serves (no `style-src`; they stay
  plain).
- The Cognito hosted sign-in page (branded on the staff pool in AsmblyMCPs).
- Any change to the page's behaviour, its script, its texts, the API or the templates.
- A dark theme.
- Other pages in this repository.
- Embedding PP Gosha (waits on the owner's licence answer; see Decision 5).

## Security

- The Content-Security-Policy stays exactly as it is (`default-src 'none'`, nonce-only
  script and style, `img-src blob:`, `connect-src 'self' https://<auth domain>`, no
  `font-src`); `test_csp_header` is not edited. The logo and pattern are inline SVG, which
  the policy allows without a source; nothing is fetched.
- No `style=` attributes, no `<script>`, `href` or `<image>` inside the SVGs, no
  `innerHTML`: the existing tests and phase 1's pattern test enforce it.
- The `<script>` is not changed, so sign-in, token handling, location removal and
  submission keep their reviewed behaviour.
- The page's public route and its checks are unchanged; no new route.

## Decisions

Made without asking, inside `/offshore` (2026-10-16).

1. **#111 is the epic.** It had no sub-issues; it was labeled `epic` and given stories
   #112 and #113 rather than a second epic. Alternative: a new epic with #111 as a
   story. Reason: #111 is the owner's request and a second epic would duplicate it.
2. **Loading UX belongs to #114.** The orchestrator relayed that the owner opened #114
   for loading, progress and retry behaviour and the Neon cache. This plan only restyles
   the existing states ("Signing in…", "Loading classes…", "Submitting…" keep the plain
   status style) and adds no behaviour. Alternative: a loading spinner here. Reason: one
   owner for each change; avoids two plans editing the script.
3. **Logo: the official vector, inlined.** The primary horizontal logo's SVG paths from
   `asmbly-classes` `logo.svelte` (commit 9a534a6), inlined with no `fill` attribute;
   `.logo { fill: currentColor; }` colours it (as built).
   Alternatives: a redraw (less faithful), a screenshot (blurry, and `img-src` would need
   `data:`), hotlinking `asmbly.org/wp-content/uploads/2023/12/purple-horizontal.svg`
   (a third host in the CSP). Reason: exact, crisp at any zoom, about 5 KB, no CSP change.
4. **No outside hosts, no CSP change, no new route.** Alternative: copy the kiln viewer's
   hotlinks to asmbly.org, or a same-origin asset route. Reason: the page is a public sign-in
   shell whose strict CSP is a reviewed security property; a route would need a caller
   check, a named resource and an admin redeploy of the deploy role.
5. **PP Gosha is not embedded; headings use a bold system stack.** PP Gosha (Pangram
   Pangram, commercial) has web copies in `asmbly-classes/app/src/lib/fonts/` (Bold and
   Light woff2, committed 2023 with no licence record) and on asmbly.org's WordPress theme,
   but nothing shows the licence covers `facilities.asmbly.org`. Fallback:
   `"Helvetica Neue", "Segoe UI", Roboto, Arial, system-ui, sans-serif` at weight 700.
   Alternative: embed PP Gosha Bold as a `data:` font (adds `font-src data:` and about
   45 KB to every load). **Owner decision**: confirm the licence and a follow-up can embed
   it via the `--font-heading` token.
6. **Roboto is not self-hosted.** Body: `Roboto, system-ui, -apple-system, …` (Roboto where
   the device has it: Android, ChromeOS, many desktops). Alternative: embed Roboto Regular
   (Apache 2.0) as `data:` woff2: needs `font-src data:` and adds about 20–40 KB to every
   load of a `no-store` page (no caching), for a small gain over system fonts. **Owner
   decision** if exact Roboto matters.
7. **Asmbly Purple replaces the ceramics magenta as the page's colour.** The page serves
   every class; magenta also drops below 4.5:1 on Asmbly White. Sub-brand colours are
   decorative (the pattern) or message tints.
8. **The pattern strip is redrawn**, as inline SVG of simple tiles in the sub-brand
   colours after the brand guide's strip; no official vector of the pattern was found in
   the org's repositories (`asmbly-classes` has the sub-brand icons, not the strip).
   **Owner decision**: supply the official pattern file to replace it.
9. **Status colours are shades of brand colours.** Error `--lasers-shade` `#ad373b`
   (5.6:1) and success `--electronics-shade` `#057a5d` (4.8:1), each 80% of the sub-brand
   colour and 20% Midnight Black; the warning and the stage banner use 20% tints of lasers
   red and woodwork yellow with Midnight Black text. Alternative: keep today's
   non-brand reds and greens. Reason: stays in the palette and passes contrast.
10. **The `<script>` is not changed.** The repository has no JavaScript test runner (the
    page's README, Decision 19 of the earlier plan); all restyling is CSS and static
    markup above `#dry-run-banner`. Alternative: add classes from the script. Reason:
    keeps the reviewed sign-in and photo code untouched.
11. **Design tokens (owner's rule, relayed 2026-10-16).** Every colour, tint, font
    stack, spacing, radius and size is a `:root` token named after the brand guide,
    defined once, and used everywhere by `var()`; tests enforce it (Design rule above).
    Tints are written as hex literals with the formula in a comment
    (`tint(p) = p × colour + (1 − p) × asmbly-white`, `shade = 0.8 × colour + 0.2 ×
    midnight-black`, per sRGB channel) and a test recomputes each. Alternative:
    `color-mix()` in CSS, which derives them in the browser but is ignored by browsers
    before 2023 (Safari 16.1 and older), which would lose the colour and the contrast.
12. **Contrast is computed by a test** from the tokens (WCAG 2.1 formula in the test
    file, no new dependency), plus a WebAIM check of anything the tests don't list.
13. **Size ceiling 100 KB** for the served page, asserted by a test (today about 42 KB;
    the branding added about 11 KB in phase 1). Reason: `Cache-Control: no-store` and no API Gateway
    compression mean every load downloads it.
14. **Error pages stay plain.** `ERROR_PAGE` has no `style-src`; branding it would change
    its CSP for a page staff rarely see.
15. **Two phases, sequential.** Identity (tokens, band, logo, pattern, type) then
    components (controls, messages, result, layout). Both edit the same three files.
16. **`docs/README.md` is not changed**: the service's behaviour, trigger, URL and
    configuration are the same; only the page's README changes.
