# Class Photo Upload Page

## Table of Contents

- [Purpose](#purpose)
- [Why the Route Has No Authorizer](#why-the-route-has-no-authorizer)
- [What It Serves](#what-it-serves)
- [Sign-In](#sign-in)
- [The Page](#the-page)
- [Brand and Design Tokens](#brand-and-design-tokens)
- [Location Removal](#location-removal)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Testing](#testing)

## Purpose

Serves the page at `https://facilities.asmbly.org/class-photo-upload` (stage:
`<FacilitiesApiUrl>/class-photo-upload`) where signed-in staff pick a class, drop in a
photo, see at once whether it is acceptable, and submit it. Submitting opens or updates
the class's pull request on `asmbly-classes` (prod), or shows what it would do (stage).
The work is done by the [Class Photo Upload API](../class_photo_upload_api/README.md);
this function only serves the page (epic #73).

## Why the Route Has No Authorizer

`GET /class-photo-upload` is the sign-in entry point. A browser opening the address
can't send a token, so the route can't sit behind the Cognito authorizer (plan README,
Decision 7). It is safe without one because the function:

- returns one fixed HTML document whose only inputs are public values: the staff pool's
  sign-in host, this page's app client ID, the page's own address and whether submitting
  is a dry run;
- reads no secret or parameter, calls no service, and changes nothing;
- shows only its title and "Signing in…" until the person has signed in.

The class list and the submission come from `GET /class-photo-upload/classes` and
`POST /class-photo-upload/submit`, which are behind `StaffCognitoAuthorizer` and also
check the token's app client (see the API's README). `tests/test_templates.py` fails if
any other `/class-photo-upload` route loses its authorizer.

## What It Serves

`page.html` (one inline `<style>`, one inline `<script>`, no libraries), read once per
container. When it is read, the shared brand tokens and the Asmbly logo from the common
layer's [`common/brand.py`](../../../layers/common/python/common/brand.py) go in at its
`/* __BRAND_TOKENS__ */` and `<!-- __ASMBLY_LOGO__ -->` markers (see
[Brand and Design Tokens](#brand-and-design-tokens)). Two more markers are filled in per
request:

- `__CSP_NONCE__`: a fresh `secrets.token_urlsafe(16)` nonce on the `<style>` and the
  `<script>`.
- `__PAGE_CONFIG__`: `{"authDomain", "clientId", "pageUrl", "dryRun"}` as JSON inside
  `<script type="application/json" id="page-config">`, with `<`, `>` and `&` written as
  `\u003c`, `\u003e` and `\u0026` so no value can close the element.

`pageUrl` is `https://` + the request's `domainName` + its `path` (`/class-photo-upload`
on the custom domain, `/<stage>/class-photo-upload` on the API's own host). It is the
sign-in return address and the base of the API calls, so it must be a callback URL on
the app client. A host or path that doesn't look like that answers 400; a missing or
invalid `STAFF_AUTH_DOMAIN` or `CLASS_PHOTO_APP_CLIENT_ID` answers 500. Both are plain
pages with no details.

Headers:

```text
Content-Type: text/html; charset=utf-8
X-Content-Type-Options: nosniff
Cache-Control: no-store
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>';
  img-src blob:; connect-src 'self' https://<auth domain>; base-uri 'none';
  form-action 'none'; frame-ancestors 'none'
```

`img-src blob:` is for the photo preview. The page uses no `style` attributes, which the
policy would block.

The branding (plan `photo-upload-branding`, epic #111) didn't change this policy, because
the page fetches nothing for it. Everything is inline:

- **The logo.** It is the official primary horizontal Asmbly logo, copied as an inline
  SVG from `asmbly-makerspace/asmbly-classes`, file `app/src/lib/components/logo.svelte`,
  commit `9a534a6c538df1e602fead183e30d93d97c247b4`. The path data is unchanged. The
  Svelte attributes and `xmlns` were dropped, and the paths take their colour from CSS
  (`fill: currentColor`). It is about 5 KB. It lives in `common/brand.py`
  (`ASMBLY_LOGO`), shared with the kiln drop-off viewer, and `page.html` holds only its
  marker.
- **The pattern strip.** It is redrawn from the brand guide's strip as an inline SVG,
  because no official vector of the strip was found (plan README, Decision 8). It is
  one 640×40 motif in an SVG `<pattern>` that fills a single `<rect>`, and it is hidden
  from screen readers.
- **Fonts.** The page uses system font stacks and loads no font file: no `@font-face`
  and no `url(` that points outside the page (the only `url(` is the pattern's own
  `fill="url(#brand-tiles)"`).
  - Body text is Roboto where the device has it, or the system sans-serif otherwise.
  - Headings use a bold system stack (`"Helvetica Neue"`, `"Segoe UI"`, …). PP Gosha,
    the brand's heading face, isn't loaded until Asmbly confirms its web licence covers
    this page (plan README, Decision 5).

Everything from outside (class names, problems, warnings, messages, the pull request
title and description) is inserted with `textContent`; the page never uses `innerHTML`.

The function logs `Served class photo page (dry_run=...)` for each page it serves, the name
of a missing variable, and that it refused an unexpected host or path (without the
values). It never logs the query string, which after sign-in carries the one-time code.

## Sign-In

Authorization code with PKCE on the staff pool's hosted sign-in (the app client is
public: no client secret exists).

1. Without a valid ID token in `sessionStorage`, the page makes a random 32-byte verifier
   and state, keeps them in `sessionStorage`, and goes to
   `https://<auth domain>/oauth2/authorize` (`response_type=code`, `scope=openid`,
   `code_challenge_method=S256`, `redirect_uri=<pageUrl>`).
2. Back on the page with `code` and `state`, it removes them from the address bar,
   checks `state`, and posts the code and verifier to `https://<auth domain>/oauth2/token`.
   It keeps the ID token and its expiry in `sessionStorage` for the tab's life.
3. Every API call sends the ID token in `Authorization`, as it is.
4. A 401 on a token that worked before signs in again once. A 401 on a token that was
   just issued, a wrong `state` or a failed exchange shows "Sign-in didn't finish. Sign in
   again." with a button, so the page never loops between itself and the sign-in. A 403
   shows "You're not allowed to use this page."
5. **Sign out** clears `sessionStorage` and goes to `https://<auth domain>/logout` with
   `client_id` and `logout_uri=<pageUrl>`.

A 401 during a submission sends the person to sign in again; they choose the photo again
when they come back.

## The Page

In order:

1. A full-width Asmbly Purple band with the Asmbly logo, "Class photo upload" and
   (once signed in) **Sign out**, then the decorative pattern strip. The band shows
   while the page signs in and when sign-in didn't finish. Under it, on stage, is the
   banner "Stage: dry run. Submitting checks the photo and shows what would happen;
   nothing is opened on GitHub."
2. **Class**: a list filled from `GET /class-photo-upload/classes`, by the name the site
   shows. A class with a `problem` (a character that can't be in a file name) is listed;
   choosing it shows the problem and keeps Submit disabled. A `warning` (another class
   shares its photo) shows under the list.
   - **While it loads**, the list is disabled and marked busy (`aria-busy`), a progress
     bar shows under it, and the page says "Loading classes…"; after 5 seconds without an
     answer, "Still loading classes from Neon…". Each is announced once.
   - **If it can't be loaded**, the page shows the API's message, or "Couldn't load the
     class list. Try again in a minute." (no answer at all, or none within 35 seconds:
     "Couldn't reach the server. Check your connection and try again."), and a **Try
     again** button that loads the list again in place, without reloading the page or
     signing in again. While it loads, the button stays (unavailable) and keeps the
     focus; when the list arrives, the button goes and the focus moves to the list.
   - **Once loaded**, a note under the list says when it was read from Neon ("Class list
     from Neon at 10:42 AM.", in the browser's time), adding "Neon didn't answer the
     last refresh, so this list may be out of date." when the API marks it `stale`.
   - **Refresh class list** (shown once a list has loaded) reads the list from Neon
     again (`GET /class-photo-upload/classes?refresh=1`), with the same busy state and
     "Refreshing the class list from Neon…". The chosen class stays chosen when it is
     still listed. It then says one of: "Class list refreshed from Neon."; "The class
     list was refreshed less than a minute ago, so this is that list. Try again in a
     minute." (the API refreshes at most once a minute); or, as an error, "Neon didn't
     answer, so the class list wasn't refreshed. The list shown is the last one read."
     A failed refresh never empties the list. The button can't be used while a
     submission runs. The outcome takes the place of a chosen class's problem or
     warning text under the list (choosing the class again shows it); Submit still
     stays disabled for a class with a problem.
3. **Photo**: drag it onto the box or choose it. The page removes location data (below),
   then runs the server's checks in the server's order with the server's messages, word
   for word (`photo_checks.py`): 4 MB or less, a JPEG by its content, 3:2 landscape
   within 1% after the orientation flag, no location. An acceptable photo shows a
   preview, its size, and "Location data was removed from this photo." when something was
   removed.
4. The warning, directly above Submit: "When you submit, this photo becomes public on
   GitHub right away, before anyone reviews it. It stays visible in the pull request even
   if the pull request is never merged."
5. **Submit**, enabled only for a class without a problem and an acceptable photo (and
   not while the class list loads). It posts `{"class_name", "photo_base64"}` (the
   cleaned bytes) with `XMLHttpRequest`, whose upload events tell the page when the
   photo has been sent. While it runs, the class list, **Choose a photo** (and dropping
   a photo), **Refresh class list** and **Submit** can't be used, a progress bar shows,
   and the page names the step it is on, each announced once: "Preparing the photo…",
   "Sending the photo…", then "Waiting for the server to check it and open the pull
   request…" (on stage: "…check it and plan the pull request…"). The seconds since it
   started ("12 s") show beside it and aren't announced. After any failure the class
   and the photo stay, so one click submits again.
6. The result: "Opened pull request #N" or "Updated pull request #N" with a link; on
   stage, "Dry run: nothing was opened", the file it would add or replace, the files it
   would remove (or none), whether it would open a new pull request or update #N, and the
   title and description; any warnings. Errors show the API's message as given,
   including its two GitHub failures ("Couldn't open the pull request. Nothing was
   changed on GitHub. Try again in a minute." and "Couldn't finish the pull request on
   GitHub. Submit the same class again: …"). When the answer has none:
   - 429 (API Gateway's throttle): "Too many submissions at once. Wait a minute and try
     again."
   - The photo was sent but the result is unknown (a 502 or 504 without a message, an
     OK answer that isn't JSON, a dropped connection, or no answer within 35 seconds of
     the photo being sent): on prod, "The server didn't confirm the result in time. A
     pull request may or may not have been opened on GitHub. Submitting the same class
     again is safe: it updates the same pull request instead of opening a second one.";
     on stage, "The server didn't answer in time. This is a dry run, so nothing was
     opened on GitHub. Try again." A throttled call (the API runs at most 3 at once)
     can also answer a 5xx without a message, and shows the same.
   - The photo never left the browser (offline, or an upload that made no progress for
     35 seconds): "Couldn't reach the server. Check your connection and try again."
   - Any other answer without a message: "Something went wrong on our side. Try again
     later."

### How It Looks

The texts above are word for word what the page shows; only their look is described
here.

- **Buttons.** **Submit**, **Choose a photo** and **Sign in again** are Asmbly Purple
  with Asmbly White text, at least 44px high. **Sign out** is an outline on the band
  that fills with Asmbly White on hover. On a device with a mouse or trackpad, a
  button turns the 80% purple tint while the pointer is over it; on a phone, where a
  tap would leave that look on, it doesn't change. **Submit** while disabled is the 20% purple tint with a dashed border, dark
  text and a "not allowed" cursor, so it differs from the enabled button by more than
  colour. **Try again**, **Refresh class list** and **Submit** look the same while they
  are busy; they use `aria-disabled` then instead of `disabled`, because a browser moves
  the focus off a focused button that becomes disabled. **Choose a photo** takes the
  same look while a submission runs. Every control shows a 3px focus ring from the keyboard (woodwork yellow on
  the band, Asmbly Purple elsewhere); the hidden file input shows its ring on **Choose a
  photo**.
- **The class list and the photo box** have a 60% purple border that turns Asmbly
  Purple on hover. The list is dashed and tinted while it is disabled (as the classes
  load), and cuts a long class name short instead of widening the page. While a photo is
  dragged over the box, the box is tinted and its dashed border turns solid purple.
- **Messages.** Four kinds differ from one another and from plain text by a 4px left
  edge and a glyph in a small square, not by colour alone:
  - an error ("Couldn't load the class list…", a photo problem, a failed submission,
    "Sign-in didn't finish…"): dark red bold text, a red edge and "✕";
  - a success ("This photo can be used…", "Location data was removed from this photo.",
    the first line of the result): green text, a green edge and "✓". When that first
    line is "Opened pull request #N" or "Updated pull request #N", it is all link, so
    it reads in Asmbly Purple, underlined, after the green edge and "✓";
  - the public-on-GitHub warning: dark bold text on the light lasers-red tint, a red
    edge and "!";
  - the stage banner: dark text on the light woodwork tint, a purple edge and "i".

  "Signing in…", the loading and submitting steps and a class `warning` keep the plain
  text style. The class list's time and the seconds a submission has taken are smaller
  (the small text size).
- **Progress.** The busy indicator is the browser's own progress bar without a value
  (it moves on its own), filled with Asmbly Purple (`accent-color`), as wide as the
  column and 8px high, under the class list or under **Submit**. The page adds no
  animation of its own. The glyphs are decorative: their
  alternative text is empty, so screen readers read only the message. Browsers that
  don't know that syntax (Safari before 17.4, Firefox before 128) show no glyph; the
  edge, the background and the weight still tell the kinds apart.
- **The result** is a card with a purple top edge. Its link is underlined (thicker on
  hover), long file names and the pull request description wrap inside it, and the
  description sits in a tinted monospace block. The card's 1px border is decorative
  (2.2:1); its purple top edge marks it.
- **Layout.** One column, up to 760px wide. At 320px and at 200% zoom nothing scrolls
  sideways: the header wraps, the pattern is cut off, and the text wraps.

## Brand and Design Tokens

The page follows the Asmbly brand guide (the screenshots in issue #111). Its served
stylesheet starts with one `:root { … }` block of design tokens, which holds the page's
own tokens from `page.html` and the shared ones from `common/brand.py` (below). That block
is the only place a colour, font stack, length or other number is written. Every other
rule uses the tokens through `var(--…)`. The only literals allowed outside the block are
`0`, `100%`, `auto`, `none`, `inherit`, `currentColor`, `transparent` and keywords that
aren't colours.

There is one exception: the breakpoint in `@media (min-width: 40rem)`, because CSS
can't use `var()` there. It must equal the `--breakpoint-wide` token, and a test checks
that it does.

The tokens are defined once: the shared ones in
[`common/brand.py`](../../../layers/common/python/common/brand.py) (`BRAND_TOKENS`, also
served by the kiln drop-off viewer), the page's own in the `:root` block of `page.html`.
The function fills the shared ones in at the `/* __BRAND_TOKENS__ */` marker when it
reads `page.html`, so the served `:root` holds both. The shared ones are Asmbly Purple,
Asmbly White, Midnight Black, Ceramics and Lasers, the two lasers tokens below, the font
stacks, type sizes, line heights and weights, the spacing scale, `--gutter`, `--radius`,
`--logo-height`, `--border-width`, `--border-width-accent`, `--focus-width`,
`--focus-offset` and `--tap-target`. A change to one of them in `brand.py` changes both
pages, and both pages' pins then need regenerating (see [Testing](#testing)). The page's
own are everything else here: the area colours, the purple tints, the semantic and glyph
tokens, and its own sizes (`--content-max-width` 47.5rem, the control, progress and
glyph sizes).

- **Defined once.** A token that means the same as another refers to it
  (`--focus-on-dark: var(--woodwork)`). No colour literal, font stack or spacing step is
  written twice.
- **The SVGs** carry no colour of their own. The logo uses `currentColor`, and each
  pattern shape has a class (`woodwork`, `lasers`, …) that a rule colours with its
  token. No element has a `style` attribute.
- **Brand colours**, exactly as the guide gives them:

  | Token | Value | Defined in |
  | --- | --- | --- |
  | `--asmbly-purple` | `#292D6A` | `brand.py` (shared) |
  | `--asmbly-white` | `#F2F4EF` | `brand.py` (shared) |
  | `--midnight-black` | `#171d1a` | `brand.py` (shared) |
  | `--woodwork` | `#F3B61B` | `page.html` |
  | `--metalwork` | `#578BC9` | `page.html` |
  | `--lasers` | `#D33E43` | `brand.py` (shared) |
  | `--textiles` | `#79CCC4` | `page.html` |
  | `--electronics` | `#00916E` | `page.html` |
  | `--printing-3d` | `#EE6E23` | `page.html` |
  | `--ceramics` | `#b34a9a` | `brand.py` (shared) |

  The sub-brand colours are used only in the pattern strip, in the focus ring on the
  purple band (woodwork), as shades in the error and success text and edges, and as
  20% tints behind the warning (lasers) and the stage banner (woodwork). There is no
  pure white or black.
- **Derived colours** are computed per sRGB channel and rounded. A tint is
  `tint(p) = p × colour + (1 − p) × asmbly-white`, and a shade is
  `shade = 0.8 × colour + 0.2 × midnight-black`. They are written as hex, not
  `color-mix()`, so older browsers show them too.

  | Token | Value | Formula |
  | --- | --- | --- |
  | `--asmbly-purple-80`, `-60`, `-40`, `-20` | `#515585`, `#797d9f`, `#a2a4ba`, `#caccd4` | tint 0.8, 0.6, 0.4, 0.2 |
  | `--lasers-shade` | `#ad373b` | shade of lasers (error text, 5.6:1 on Asmbly White); shared, in `brand.py` |
  | `--electronics-shade` | `#057a5d` | shade of electronics (success text, 4.8:1) |
  | `--lasers-20` | `#ecd0cd` | tint 0.2 of lasers (the warning's background); shared, in `brand.py` |
  | `--woodwork-20` | `#f2e8c5` | tint 0.2 of woodwork (the stage banner's background) |

  Tints lighter than 60% only ever carry Midnight Black text (the guide's rule), and a
  test checks every rule that puts one behind text.
- **Semantic tokens** are what the rules use, and each is built from the brand tokens:
  `--page-bg`, `--text`, `--brand`, `--on-dark`, `--line`, `--line-on-dark`,
  `--control-border`, `--tint-bg`, `--error`, `--ok`, `--focus`, `--focus-on-dark`,
  `--disabled-bg`, `--hover-bg`, `--drag-bg`, `--code-bg`, `--warning-bg`, `--banner-bg`
  and `--banner-edge`.
- **Glyph tokens** (`--glyph-error`, `--glyph-ok`, `--glyph-warning`, `--glyph-banner`)
  each hold one character and its empty alternative text (`"✕" / ""`), so the glyph is
  written once and the rules use it through `var()`.
- **Type and space tokens:**
  - type: `--font-body`, `--font-heading`, `--font-mono` (the result's description and
    the banner's "i"), `--font-size-*`, `--line-height*` and `--weight-*`;
  - spacing: the scale `--space-1` (0.25rem) to `--space-6` (2rem);
  - sizes: `--gutter`, `--radius*`, `--content-max-width`, `--logo-height` (3.5rem, so
    56px against the brand minimum of 50px), `--pattern-height`, `--preview-max-height`,
    `--border-width*`, `--focus-*`, `--visually-hidden-size`, `--tap-target` (2.75rem,
    44px), `--glyph-size`, `--glyph-offset`, `--underline-offset` and `--track-fill`
    (the flexible column of the header grid and of each message's glyph-and-text grid).

  Hover rules sit in `@media (hover: hover)`, which has no number, so the one
  `min-width` breakpoint stays the only literal outside the block.

These tests enforce the rule:

- `test_styles_use_tokens_only` works from an allowlist. Outside `:root`, a
  declaration's value may hold only `var()` references, `0`, `100%`, the header's
  grid-area names, and the non-colour keywords in `ALLOWED_VALUE_WORDS`. So any colour
  (hex, `rgb()`, a named or system colour), any length or number, and any literal font
  family fails. The inline SVGs may carry only the attributes in `SVG_ATTRIBUTES`, and
  `fill` only as `url(#…)`.
- `test_token_block_holds_only_tokens` checks that the one `:root` block holds only
  tokens, and that each token is a `#rrggbb` colour, a `var()`, a length or number,
  (for `--font-*`) a font stack (two or more families, the last a generic family such as
  `sans-serif`), or (for the four `--glyph-*` glyphs) one character with an empty
  alternative text.
- `test_tokens_are_defined_once` catches a duplicate token, colour, font stack or other
  literal. Two tokens of different kinds may share a number only when the pair is listed
  in `SHARED_LITERALS`, with the reason (for example, `--font-size-body` and `--space-4`
  are both `1rem`).
- `test_every_token_used_is_defined` catches a `var()` that names no token, and
  `test_every_token_is_used` catches a token nothing uses, apart from the ones listed in
  `RESERVED_TOKENS` with their reason.
- `test_brand_tokens_match_the_guide` and `test_derived_tokens_follow_the_formula`
  check the colour values, and `test_brand_colour_pairs_meet_contrast` checks the WCAG
  2.1 contrast of the colour pairs the page uses.

The logic of these checks, and of the logo check in
`test_page_shows_official_logo_in_header`, is in `tests/page_style.py` at the
repository root, shared with the kiln drop-off viewer. This page's test file holds its
data (`STYLE_BLOCK`, `SCRIPT_BLOCKS`, `BRAND_COLOURS`, `DERIVED_COLOURS`,
`CONTRAST_PAIRS`, `ALLOWED_VALUE_WORDS`, `GRID_AREAS`, `TOKEN_VALUE`, `RESERVED_TOKENS`,
`SHARED_LITERALS`, `SVG_ATTRIBUTES`, `MEDIA_RULE`, `MESSAGE_KINDS`, `LOADING_MESSAGES`)
and the tests that only this page has.

To change a colour or a size, change its token. To add a style, use the existing
tokens, or add a token to the block first. Add a word to `ALLOWED_VALUE_WORDS` only if
it is a CSS keyword that can't carry a colour or a size.

## Location Removal

Done in the browser, so the location never leaves the device (plan README, Decisions 18,
25 and 26). Only header bytes change: the compressed image data, from the main image's
SOS marker to its EOI, is copied unchanged, and the orientation flag stays. A photo with
nothing to remove is sent byte for byte as chosen.

- **EXIF.** In every EXIF segment, each GPS IFD pointer (tag `0x8825`) in IFD0, IFD1 or
  the Exif sub-IFD is deleted: the later entries move up 12 bytes, the count drops by
  one, the next-IFD offset follows, and the freed bytes are zeroed. The GPS IFD itself
  (its entries, next-IFD field and every value they point to) is zeroed. Bytes of the
  TIFF header and the other IFDs' tables are never zeroed.
- **XMP.** A standard XMP segment with GPS properties is dropped whole. Extended XMP
  chunks are joined by GUID; when the joined data has GPS properties, every chunk of that
  GUID is dropped (and so is any single chunk that has them).
- **Embedded images and trailers.** The page finds the main image's EOI by walking its
  entropy-coded data. If the bytes after it (MPF images, gain maps, motion-photo video)
  hold a JPEG with EXIF or XMP GPS, or the XMP GPS pattern anywhere, everything after
  the EOI is dropped; otherwise it is kept as it is.
- **What it can't remove.** Location the page can't take out without re-encoding (a
  thumbnail with GPS inside the headers, the GPS pattern inside the image data) is
  refused with "This photo has location data the page can't remove. Export it again as a
  JPEG without location and try again." The server would refuse it too.

"Location" means GPS coordinates; place names (IPTC City, XMP `photoshop:City`) are not
removed (Decision 25).

## AWS Infrastructure

Defined in `templates/classes.yaml` (nested stack `ClassesStack`), wired in
`template.yaml`:

| Resource | Name |
| --- | --- |
| Function | `ClassPhotoUploadPageFunction-${Stage}` (Python 3.12, 5 s timeout, the common layer only (brand tokens and logo), no policies) |
| Log group | `/asmbly/lambda/ClassPhotoUploadPageFunction-${Stage}`, 14 days |
| Route | `GET /class-photo-upload` on `FacilitiesApi`, no authorizer |
| Invoke permission | `ClassPhotoUploadPageInvokePermission`, for `GET /class-photo-upload` only |

Tag: `Project: classes:class-photo-upload`.

## Configuration

Environment variables (all set by `templates/classes.yaml`):

| Variable | Value |
| --- | --- |
| `STAFF_AUTH_DOMAIN` | The staff pool's hosted sign-in host, no scheme, from SSM `/config/cognito/staff/auth-domain` (template parameter `StaffAuthDomain`) |
| `CLASS_PHOTO_APP_CLIENT_ID` | The page's app client ID, from SSM `/config/cognito/staff/class-photo-app-client-id` |
| `CLASS_PHOTO_DRY_RUN` | `false` on prod, `true` elsewhere; only shows or hides the stage banner (the API function decides what a submission does) |

The first two are required. Outside this repository: the staff pool's
`class-photo-upload` app client (AsmblyMCPs) must list the page's address, prod and
stage, as both a callback URL and a sign-out URL (plan README, admin action 3). The
step-by-step setup of the app client and the `/config/cognito/staff/*` parameters is in
[docs/Deploying.md, "One-Time Admin Setup: Class Photo Upload"](../../../docs/Deploying.md#one-time-admin-setup-class-photo-upload).

## Testing

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_page
```

The tests cover the served HTML: the config and nonce, the stage address, the CSP, a
config value that tries to close its script, the error pages, the warning's place above
Submit, that the page's messages and limits are the server's, that it uses no
`innerHTML` or `style` attributes, and that the log holds no query string. They also
cover the branding: the official logo in the header and its minimum size, that the
pattern is decorative, the design-token rule above, the colour contrast, that no font
or outside asset is loaded, and that the served page is under 100 KB. And the controls:
that light tints carry dark text, that the four message kinds each have a left edge and
their own glyph while plain status text has neither, a focus ring on every control, 44px
tap targets, a hover look on every control (only inside `@media (hover: hover)`), a
disabled look that is dashed and not only coloured, that the result's text wraps and its
link is underlined, and that nothing hides a horizontal overflow. And the loading
states: the progress bars (labelled, hidden, coloured from tokens, no animation), **Try
again** and **Refresh class list** (named by their text), the elapsed seconds kept out of
the live regions, every loading and progress message, the disabled look of busy buttons
and of **Choose a photo**, and that the submission goes to the page's own origin.
Two pins hold the page's look as it was on `stage` before story #138, which shares
the brand tokens and logo through `layers/common/python/common/brand.py`: the served page must
have the `:root` tokens in `tests/fixtures/pinned_tokens.json` and the CSS rules in
`tests/fixtures/pinned_rules.css`. After a deliberate change to the look, regenerate them
with `.venv/bin/python -m tests.capture_page_pins` from the repository root and commit
them with the change. A change to a shared token in `brand.py` changes both pages' pins.
`tests/test_shared_brand.py` checks that neither `page.html` has its own copy of the
shared tokens or logo, that a changed shared token reaches both served pages, and that
this function, with only the common layer, loads no boto3 or `requests`.

Some things the tests can't see; check them by hand when you change the styles:

- Render the page (`lambda_function.render_page` with a test config) in Chrome or
  Firefox at 320px wide and at 1280px with 200% zoom, with the longest class name chosen
  and a dry-run result with long file names: nothing scrolls sideways.
- Walk it with the keyboard: **Sign out**, the class list, **Try again** or **Refresh
  class list**, **Choose a photo**, **Submit**, the result's link, each with a visible
  ring; pressing **Refresh class list** or **Submit** with Enter keeps the focus on it.
  (Safari doesn't focus a button on a mouse click, so after picking a class from the
  keyboard and clicking **Submit**, the focus is on the list, which is disabled while
  the submission runs, and moves to the page; that is expected.) (Safari skips buttons and
  links on Tab unless "Press Tab to highlight each item" is on.)
- Check any colour pair the tests don't list with the WebAIM contrast checker.
- Safari may draw a native `select` at its own height rather than 44px.

`test_page_script.py` runs the page's own script with Node (no npm package):
`tests/page_script_harness.mjs` runs it in `node:vm` with a small fake DOM, a fake clock
and scripted server answers, one scenario per test. The scenarios cover the class list's
busy state, "Still loading…" after 5 seconds, a failed or unanswered load and **Try
again** (focus included), the time and stale notes, **Refresh class list** and its three
outcomes (keeping the chosen class, and never emptying the list), and the submission:
controls unavailable, the three steps and the elapsed seconds, one request for a double
click, the class and photo kept after a failure, the unconfirmed and dry-run messages
(502, 504, dropped connection, the 35-second limit), a slow upload that keeps moving,
and a failure before the photo was sent. The fake DOM moves focus to the page when a
focused control is hidden or disabled, as browsers do. Without `node` the tests are
skipped on your machine; in CI (where `CI` is set) a missing `node` fails them.
GitHub's `ubuntu-latest` runner has Node.

```bash
node functions/classes/class_photo_upload_page/tests/page_script_harness.mjs --list
```

The JPEG code has no test of its own in Node, and the server re-checks every photo. When
you change it, run it in a browser against the server's checks: load the page's JPEG
code (the part of the script between "Settings and messages" and "Page state") in
headless Chromium, run `checkPhoto` and `removeLocation` over JPEGs from
`functions/classes/class_photo_upload_api/tests/jpeg_builder.py` and real photos, and
compare with `photo_checks.check_photo`: the messages must match, the cleaned photo must
pass the server's check, and its bytes from SOS to EOI must equal the original's. Then
go through the manual checks in the plan's `MANUAL_QA.md` on stage. Among them: **Sign
out** returns straight to the hosted sign-in (the app client's sign-out URL is the page,
which signs in again at once), so there is no "signed out" screen; that is expected.
