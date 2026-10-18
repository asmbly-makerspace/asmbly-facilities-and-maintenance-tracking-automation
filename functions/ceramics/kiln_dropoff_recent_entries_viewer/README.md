# Kiln Drop Off Recent Entries Viewer

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [Look and brand tokens](#look-and-brand-tokens)
- [AWS Resources](#aws-resources)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)
- [Testing](#testing)

## Purpose

### Endstate

Kiln-Ops would like to simplify their record keeping practice for themselves and their users by having users use a QR code to scan a QR code, complete a form to drop off their piece, then write a unique identifier on a slip for their piece. The kiln staff can then easily load all of the pieces into the kiln and use the associated slips to digitally log which pieces are in the kiln. Afterwards, the slips will be discarded, and through digital records ClickUp can automatically email members that their piece is completed.

### Problem

ClickUp Forms when submitted show a completely static page and there’s no way to have a unique identifier.

### End Result

ClickUp Forms allow for a Redirect URL. Using this, once a member completes the form they will be redirected to a page that will show the names and IDs of recent drop offs. In case there is any delay in ClickUp creating the entry and it being available in the redirect URL, the user can refresh the page to see their ID. When it is available, the ID will be hand written on a slip for them to use. (Future this could be printed)

### Solution by This Lambda

Enable users to get an ID of their kiln drop off submission so they can transfer that to a paper receipt.

## How It Works

This diagram illustrates the secure, server-side workflow for displaying recent ClickUp tasks after a form submission. This architecture avoids exposing API keys.

### Components:

-   **User's Browser:** The end-user's web browser.
-   **ClickUp Form:** The native form where the user submits their entry.
-   **AWS API Gateway:** A managed service that provides a public URL (endpoint) for our application.
-   **AWS Lambda:** A serverless function that contains the Python logic.
-   **AWS Secrets Manager:** Holds the ClickUp API token (secret `clickup/api/token`, key `CLICKUP_API_TOKEN`).
-   **AWS Systems Manager Parameter Store:** Holds the drop-off list ID (parameter `/<stage>/config/clickup/ceramics/dropOffRequests`, key `list_id`).
-   **ClickUp API:** The official API for accessing ClickUp data.

### Visual Flow

```
+---------------+      +----------------+      +-----------------+      +---------------------+
| User's        |      | ClickUp        |      | AWS API Gateway |      | AWS Lambda Function |
| Browser       |      | Form           |      | (Public URL)    |      | (Your Code)         |
+---------------+      +----------------+      +-----------------+      +---------------------+
|                     |                      |                       |
(1) Submit Form ------------->|                      |                       |
|                     |                      |                       |
(2) Redirect Browser -------->|--------------------->|                       |
|                     |                      |                       |
|                     |             (3) Trigger Function ----------->|
|                     |                      |                       |
|                     |                      |                       | (4) Get list ID and token
|                     |                      |                       |---------------------->[SSM Parameter Store, Secrets Manager]
|                     |                      |                       |                      |
|                     |                      |                       |<----------------------| (5) Return list ID and token
|                     |                      |                       |
|                     |                      |                       | (6) Request Tasks
|                     |                      |                       |---------------------->[ClickUp API]
|                     |                      |                       |                      |
|                     |                      |                       |<----------------------| (7) Return Task Data
|                     |                      |                       |
|                     |             (8) Return HTML Page   |
|<--------------------------------------------|<-----------------------|
|                     |                      |                       |
(9) Display Page              |                      |                       |
|                     |                      |                       |
```

### Step-by-Step Data Flow:

1.  **Kiln DropOff Form Submission**
    * **Source:** User's Browser
    * **Destination:** ClickUp Kiln Drop Off Form
    * **Action:** The user fills out the form and clicks "Submit".

2.  **HTTP Redirect**
    * **Source:** ClickUp Form
    * **Destination:** AWS API Gateway
    * **Action:** ClickUp instructs the user's browser to navigate to the AWS API Gateway URL. No task data is sent here.

3.  **Trigger Lambda Function**
    * **Source:** AWS API Gateway
    * **Destination:** AWS Lambda
    * **Action:** The incoming request to the API Gateway endpoint automatically triggers your Lambda function to run.

4.  **Fetch the list ID and the API token**
    * **Source:** AWS Lambda
    * **Destination:** SSM Parameter Store, then AWS Secrets Manager
    * **Action:** The function reads the drop-off list ID from the SSM parameter `/<stage>/config/clickup/ceramics/dropOffRequests` (key `list_id`), then the ClickUp API token from Secrets Manager. Secrets Manager holds only the token.

5.  **Return the list ID and the token**
    * **Source:** SSM Parameter Store and AWS Secrets Manager
    * **Destination:** AWS Lambda
    * **Action:** The values are passed back to the running function. If the token is empty, the function stops here and shows the error page.

6.  **Request Tasks from ClickUp API**
    * **Source:** AWS Lambda
    * **Destination:** ClickUp API
    * **Action:** The Lambda function makes a server-to-server API request to api.clickup.com, using the fetched secrets for authentication. This call is not subject to CORS rules.

7.  **Return Task Data**
    * **Source:** ClickUp API
    * **Destination:** AWS Lambda
    * **Action:** The ClickUp API returns a JSON object containing all tasks created in the last 24 hours.

8.  **Generate and Return HTML**
    * **Source:** AWS Lambda
    * **Destination:** AWS API Gateway
    * **Action:** The function processes the JSON data, builds the table rows, fills them into the page shell `page.html`, and returns the page as the response. Each drop-off's name and ID are HTML-escaped, so text typed into the form shows as text and never runs as code. A drop-off with no custom ID shows its ClickUp task ID. The "Time Submitted" column is in US Central time (`America/Chicago`), with `CST` or `CDT` after each time, for example `2023-12-31 18:00:00 CST`. ClickUp gives the time in UTC; the zone data decides whether daylight saving time applies. The function packages `tzdata` (in `requirements.txt`), so the conversion works even if the Lambda runtime has no system zone data. If the zone can't be loaded, the function logs the error and shows the error page.

9.  **Display Page**
    * **Source:** AWS API Gateway
    * **Destination:** User's Browser
    * **Action:** The API Gateway forwards the HTML response to the user's browser, which then renders the final page showing the list of recent submissions.

### Errors and security headers

- If anything goes wrong (a missing environment variable, an empty token, an SSM, Secrets Manager or ClickUp error), the page says only "Could not retrieve the list of submissions." The details go to the log group `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-<stage>`, never to the page.
- The error page has the same header band, Refresh button and logo as the list page, and shows the error message in a box, then "Please wait 1-2 minutes and refresh." above the Refresh button. It shows no list and no "No submissions found" line. That line appears only when the list loads and nothing was dropped off in the last 24 hours ("No submissions found in the last 24 hours. Please try refreshing.").
- Every response, the list and the error page alike, is sent with these headers:
  - `Content-Type: text/html; charset=utf-8`
  - `X-Content-Type-Options: nosniff`
  - `Cache-Control: no-store`, so Refresh always fetches a fresh list
  - `Content-Security-Policy: default-src 'none'; style-src 'sha256-<hash>'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, where `<hash>` is the base64 SHA-256 of the text of the one `<style>` block the page serves (the one in `page.html`, with the shared brand tokens filled in). The page runs no script and loads nothing from any other site: the icon and the logo are drawn in the page and the fonts are the device's own. The browser applies the style block only if its hash matches, and it ignores any `style="…"` attribute. The page can't be shown inside a frame.
- The policy is built by `csp.hash_policy` in the common layer's [`common/csp.py`](../../../layers/common/python/common/csp.py), which the class photo upload page also uses. `lambda_function.py` calls it once, when the function starts, over `page.html` with the shared brand tokens and logo filled in, so editing the stylesheet or `layers/common/python/common/brand.py` needs no change to the policy. If `page.html` ever has no `<style>` block or more than one, `csp.style_hash_source` raises `ValueError`; that, or a lost or doubled `/* __BRAND_TOKENS__ */` marker, makes the function fail as it starts, and API Gateway answers every request with a bare 502 instead of a page. A deploy does not catch that; the tests do (`test_style_hash_rejects_zero_or_two_style_blocks`, `test_csp_style_hash_matches_served_style`, and the shared `test_hash_pages_allow_only_their_served_style`), so run them after editing `page.html`.
- If you ever need an image, font or script from another site, the policy must allow it. Build it with the helper rather than a string in `lambda_function.py`: `csp.strict_policy([("style-src", csp.style_hash_source(PAGE_TEMPLATE)), ("img-src", "https://…")])` gives the same policy with one more directive, and `test_no_function_builds_a_csp_by_hand` fails on a hand-written one. Prefer drawing it in the page, as the icon and logo are.
- The Refresh button is a plain link back to the same page, so it works without script.

## Look and brand tokens

The page follows the Asmbly brand guide with the ceramics colour as its accent, in the
same way as the class photo upload page (`functions/classes/class_photo_upload_page/`).
The list page, the empty list and the error page share one shell, `page.html`, next to
`lambda_function.py`. The function reads it once per container. First it fills in the
two brand markers from the common layer's
[`common/brand.py`](../../../layers/common/python/common/brand.py), which the class photo
upload page shares: `/* __BRAND_TOKENS__ */` in the `:root` block gets the shared brand
tokens, and `<!-- __ASMBLY_LOGO__ -->` in the footer gets the Asmbly logo. It computes
the CSP hash over that filled shell. Then, for each page, it fills in two placeholders:
`__RELOAD_TEXT__` (the hint above the Refresh button) and `__MAIN_CONTENT__` (the list
or the error box). The main content goes in last, so a drop-off named `__RELOAD_TEXT__`
shows as that name.

- **Header band:** full width, in the ceramics colour `--ceramics` (#b34a9a), with the
  ceramics icon and the title in Asmbly White. Asmbly White on the ceramics colour is
  4.35:1: enough for large text and for the icon (3:1), not for body text. The band
  therefore holds only the icon and the `h1`, which is 1.75rem bold at every width. The
  subtitle and everything else sit on the Asmbly White page.
- **Table:** the header row on the ceramics 20% tint; drop-off IDs in a bold monospace
  1.125rem in the ceramics shade, never split across lines, because members copy them
  onto a slip. Names wrap anywhere, so a long name never widens the page. The time is in
  the small size and wraps only between the date and the time: the zone is joined to the
  time with a non-breaking space, so "18:00:00 CST" stays on one line.
- **Refresh button:** the ceramics shade, darker on hover where a pointer can hover, at
  least 44px by 44px, with a 3px focus ring.
- **Error box:** the lasers 20% tint, with a 4px lasers-shade edge on the left and a ✕
  before the heading, so it differs from the page by more than colour. Browsers older
  than iOS Safari 17.4 and Firefox 128 don't show the ✕; the edge and the heading still
  mark the error.
- **Footer:** the Asmbly logo in Asmbly Purple, 3.5rem (56px) tall, above the brand
  guide's 50px minimum.
- **Ceramics icon:** the single path of
  `https://asmbly.org/wp-content/uploads/2025/02/ceramics-white.svg` (viewBox
  `0 0 38.4 38.4`), copied without its `<style>` and `fill`, so it takes Asmbly White from
  the band through `fill: currentColor`. The pot is cut out of the square, so the band's
  colour shows through it. Screen readers announce it as "Ceramics".
- **Asmbly logo:** the official vector from `asmbly-makerspace/asmbly-classes`
  (`app/src/lib/components/logo.svelte`, commit
  `9a534a6c538df1e602fead183e30d93d97c247b4`), from `common/brand.py` (`ASMBLY_LOGO`),
  shared with the class photo upload page, with `fill: currentColor`. Screen readers
  announce it as "Asmbly Makerspace".
- **Type:** system font stacks, shared with the photo page through `common/brand.py`, so
  no font file is fetched. PP Gosha, the brand's heading face, is not used until Asmbly
  confirms its web licence covers this site.

### Tokens

Every colour, font stack, length and number is a CSS custom property, defined once: the
shared ones in [`common/brand.py`](../../../layers/common/python/common/brand.py)
(`BRAND_TOKENS`), the page's own in the `:root` block at the top of the stylesheet in
`page.html`. The served `:root` holds both. Every other rule uses them through `var()`.
No `style` attribute, no colour or size written anywhere else; the tests fail if that
changes.

A change to a shared token in `brand.py` changes this page and the class photo upload
page, and changes this page's CSP hash, which the function recomputes when it starts.
Both pages' pins then need regenerating (see [Testing](#testing)).

- Brand colours (shared): `--asmbly-purple` #292D6A, `--asmbly-white` #F2F4EF,
  `--midnight-black` #171d1a, `--ceramics` #b34a9a, `--lasers` #D33E43.
- Tints and shades, per sRGB channel, rounded:
  `tint(p) = p × colour + (1 − p) × asmbly-white`,
  `shade(p) = p × colour + (1 − p) × midnight-black`.
  `--ceramics-shade` (0.8) #944180, `--ceramics-shade-60` (0.6) #753867,
  `--ceramics-40` #d9b0cd, `--ceramics-20` #e5d2de, `--ceramics-10` #ece3e6 (this
  page's), `--lasers-shade` (0.8) #ad373b, `--lasers-20` #ecd0cd (shared). A test
  recomputes each, so to change a brand colour, change it and recompute its tints and
  shades.
- What each colour is for (this page's): `--page-bg`, `--text`, `--accent` (= `--ceramics`),
  `--on-accent`, `--accent-strong` (IDs, button), `--accent-hover`, `--table-head-bg`,
  `--row-hover-bg`, `--line`, `--focus`, `--logo-colour` (the only use of Asmbly Purple),
  `--error-bg`, `--error-edge`, and the glyph `--glyph-error`.
- Type and size (shared): `--font-body`, `--font-heading`, `--font-mono`,
  `--font-size-body`, `-h1`, `-h2`, `-small`, `--line-height*`, `--weight-*`,
  `--space-1` to `--space-6`, `--gutter`, `--radius`, `--logo-height`, `--border-width`,
  `--border-width-accent`, `--focus-width`, `--focus-offset`, `--tap-target`.
- Sizes (this page's): `--font-size-id`, `--content-max-width` (50rem),
  `--icon-height`.

Add a token only when a rule uses it. `--lasers` is the one token no rule reads; it is
the parent of the two lasers tokens.

The token, colour, contrast and logo checks run from `tests/page_style.py` at the
repository root, shared with the class photo upload page. This function's test file holds
the page's data (`STYLE_BLOCK`, `BRAND_COLOURS`, `DERIVED_COLOURS`, `CONTRAST_PAIRS`,
`ALLOWED_VALUE_WORDS`, `TOKEN_VALUE`, `RESERVED_TOKENS`, `SHARED_LITERALS`,
`SVG_ATTRIBUTES`) and its own layout tests.

### Contrast

WCAG 2.1, computed by `test_colour_pairs_meet_contrast` from the token values.

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
| `--error-edge` | `--error-bg` | error box edge, and the ✕ in the 20px bold heading | 3.0 | 4.27 |
| `--focus` | `--page-bg` | focus ring | 3.0 | 7.53 |
| `--logo-colour` | `--page-bg` | Asmbly logo | 3.0 | 11.30 |

The table header's line (`--line`, the ceramics 40% tint) is decorative; the header
row's tint and bold text set it apart.

## AWS Resources

Tags in AWS will be:

| Name        | Value                        |
|-------------|------------------------------|
| Project     | ceramics:kiln-dropoff-viewer |

### Permissions

The function's role (`KilnDropoffViewerLambdaRole` in `templates/ceramics.yaml`) can do
three things and nothing else:

- Write log streams and log events to its own log group,
  `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-<stage>`.
- Read the `clickup/api/token` secret from Secrets Manager.
- Read the `/<stage>/config/clickup/ceramics/dropOffRequests` parameter from SSM.

The role can't create log groups. CloudFormation creates this one. If someone deletes it
by hand, the function keeps working but its logs are lost until the log group exists
again under the same name. A normal deploy won't bring it back, because CloudFormation
doesn't notice a resource deleted outside it. An admin has to recreate the log group
with that name and a 30-day retention.

`tests/test_templates.py` fails if this role, or any other hand-written Lambda role, is
given an IAM action or a logs grant on anything but its own function's log group.

## Configuration

The template `templates/ceramics.yaml` sets two environment variables:

| Variable | Value | What it is |
| --- | --- | --- |
| `SECRET_NAME` | `clickup/api/token` | The Secrets Manager secret that holds the ClickUp API token under the key `CLICKUP_API_TOKEN` |
| `CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME` | `/<stage>/config/clickup/ceramics/dropOffRequests` | The SSM parameter with the drop-off list ID under the key `list_id` |

The list ID itself lives in `configs/clickup_ceramics_dropOffRequests.json`; the template turns that file into the SSM parameter. To point the page at another ClickUp list, change the JSON file and deploy.

The time zone of the "Time Submitted" column is the constant `CENTRAL_TIME_ZONE` (`America/Chicago`) in `lambda_function.py`, not configuration. Its zone data comes from the `tzdata` package in `requirements.txt`, which `sam build` installs with the function. The entry has no version, so each build gets the latest zone data.


## Deployment

The deployment process is managed and specified in the [Deployment Instructions](/docs/Deploying.md).

## Usage

The URL is in the ClickUp form in Ceramics -> Drop Off Requests -> Kiln Drop Off Form -> Settings -> Redirect URL.

## Testing

From the repository root:

```bash
.venv/bin/python -m pytest functions/ceramics/kiln_dropoff_recent_entries_viewer
```

The tests mock SSM, Secrets Manager and ClickUp, so they need no AWS access. After a deploy to stage, open `<stage API URL>/KilnOpsDropoffRecentEntriesViewer` and check that the list loads, each time ends in `CST` or `CDT` (which shows the deployed function has its zone data), Refresh reloads it, and the browser console shows no Content-Security-Policy violations. Stage has no custom domain, so `<stage API URL>` is the `FacilitiesApiUrl` output of the stage stack, `AsmblyFacilitiesMaintTrackingStack-stage`, which looks like `https://<api-id>.execute-api.us-east-2.amazonaws.com/stage`. Find it in the AWS console under CloudFormation, that stack, the **Outputs** tab. (In prod the page is `https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer`.)

The browser's own request for `/favicon.ico` may show as blocked by `default-src 'none'` (Firefox) or as a 403. That is older than the page's styling and is the one expected console message.

The tests also cover the look: every colour, size and font is a token (and every token is used and defined once), the tints and shades follow the formula, every pair in the contrast table meets its minimum, the Refresh button is a 44px target with a visible focus ring, hover looks exist only where a pointer can hover, table text wraps, the band holds only the icon and the title, the error page shares the shell, and the page with 50 drop-offs is under 60 KB. Two pins hold the page's look as it was on `stage` before story #138, which shares the brand tokens and logo through `layers/common/python/common/brand.py`: every page the function serves must have the `:root` tokens in `tests/fixtures/pinned_tokens.json` and the CSS rules in `tests/fixtures/pinned_rules.css`. After a deliberate change to the look, regenerate them with `.venv/bin/python -m tests.capture_page_pins` from the repository root and commit them with the change. A change to a shared token in `brand.py` changes both pages' pins, and this page's CSP hash, which the function recomputes when it starts. `tests/test_shared_brand.py` checks that neither `page.html` has its own copy of the shared tokens or logo, and that a changed shared token reaches both served pages. The header's checks are shared with the class photo upload page: `tests/page_csp.py` holds them, and `tests/test_page_csp.py` runs them on every page registered in its `PUBLIC_PAGES`, this one included (its empty list, a list with a drop-off, and the error page). That file also fails if a function writes a policy string by hand instead of calling `common/csp.py`. To see the pages without deploying, write `generate_html_page([...])`, `generate_html_page([])` and `generate_error_page()` to files and open them in a browser. A local file has no CSP header, so the policy is checked on stage.
