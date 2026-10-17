# Class Photo Upload Page

## Table of Contents

- [Purpose](#purpose)
- [Why the Route Has No Authorizer](#why-the-route-has-no-authorizer)
- [What It Serves](#what-it-serves)
- [Sign-In](#sign-in)
- [The Page](#the-page)
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

`page.html` (one inline `<style>`, one inline `<script>`, no libraries, no outside fonts
or images), read once per container, with two markers filled in per request:

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
policy would block. Everything from outside (class names, problems, warnings, messages,
the pull request title and description) is inserted with `textContent`; the page never
uses `innerHTML`.

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

1. "Class photo upload", **Sign out**, and on stage the banner "Stage: dry run.
   Submitting checks the photo and shows what would happen; nothing is opened on GitHub."
2. **Class**: a list filled from `GET /class-photo-upload/classes`, by the name the site
   shows. A class with a `problem` (a character that can't be in a file name) is listed;
   choosing it shows the problem and keeps Submit disabled. A `warning` (another class
   shares its photo) shows under the list. If the list can't be loaded, the page shows
   the API's message, or "Couldn't load the class list. Try again in a minute."
3. **Photo**: drag it onto the box or choose it. The page removes location data (below),
   then runs the server's checks in the server's order with the server's messages, word
   for word (`photo_checks.py`): 4 MB or less, a JPEG by its content, 3:2 landscape
   within 1% after the orientation flag, no location. An acceptable photo shows a
   preview, its size, and "Location data was removed from this photo." when something was
   removed.
4. The warning, directly above Submit: "When you submit, this photo becomes public on
   GitHub right away, before anyone reviews it. It stays visible in the pull request even
   if the pull request is never merged."
5. **Submit**, enabled only for a class without a problem and an acceptable photo. It
   posts `{"class_name", "photo_base64"}` (the cleaned bytes) and shows "Submitting…".
6. The result: "Opened pull request #N" or "Updated pull request #N" with a link; on
   stage, "Dry run: nothing was opened", the file it would add or replace, the files it
   would remove (or none), whether it would open a new pull request or update #N, and the
   title and description; any warnings. Errors show the API's message as given. When the
   answer has none (API Gateway's own 429, 502 or 504), the page says "Too many
   submissions at once. Wait a minute and try again." for 429 and "Something went wrong on
   our side. Try again later." otherwise; with no answer at all, "Couldn't reach the
   server. Check your connection and try again."

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
| Function | `ClassPhotoUploadPageFunction-${Stage}` (Python 3.12, 5 s timeout, no layers, no policies) |
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
`innerHTML` or `style` attributes, and that the log holds no query string.

The page's JavaScript has no automated test in CI (plan README, Decision 19): the
repository has no JavaScript test runner, and the server re-checks every photo. When you
change the script, run it in a browser against the server's checks: load the page's JPEG
code (the part of the script between "Settings and messages" and "Page state") in
headless Chromium, run `checkPhoto` and `removeLocation` over JPEGs from
`functions/classes/class_photo_upload_api/tests/jpeg_builder.py` and real photos, and
compare with `photo_checks.check_photo`: the messages must match, the cleaned photo must
pass the server's check, and its bytes from SOS to EOI must equal the original's. Then
go through the manual checks in the plan's `MANUAL_QA.md` on stage. Among them: **Sign
out** returns straight to the hosted sign-in (the app client's sign-out URL is the page,
which signs in again at once), so there is no "signed out" screen; that is expected.
