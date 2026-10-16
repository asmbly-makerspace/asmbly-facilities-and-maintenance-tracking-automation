---
phase_id: 6
title: The upload page and docs
epic: 73
implements: [104, 105, 106, 107, 108, 109]
depends_on: [5]
domain: [lambda, infra, docs]
estimated_size: L
---

# Phase 6: The upload page and docs

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; #73 "What we want" and "What the page must say"; README Security and
  Decisions 7, 8, 18 and 19.
- Phase 5's hand-off (routes, request and response shapes, error strings) and phase 2's
  message texts.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py`:
  `RESPONSE_HEADERS` (a page's headers and CSP) and how it escapes.
- Cognito hosted UI endpoints: `/oauth2/authorize` (authorization code with PKCE,
  `code_challenge_method=S256`), `/oauth2/token` (public client: `grant_type`,
  `client_id`, `code`, `redirect_uri`, `code_verifier`), `/logout` (`client_id`,
  `logout_uri`).

## Goal

A staff member opens `https://facilities.asmbly.org/class-photo-upload` (or the stage
URL), is sent to the staff sign-in and back, picks a class, drops in a photo, sees at
once whether it is acceptable (with location data removed on the device), reads the
public-on-GitHub warning, clicks Submit, and gets a link to the opened or updated pull
request, or, on stage, the dry-run report. `docs/README.md` lists the page.

## Files to create

- `functions/classes/class_photo_upload_page/__init__.py`: empty.
- `functions/classes/class_photo_upload_page/lambda_function.py`: serves the page.
- `functions/classes/class_photo_upload_page/page.html`: the page, with its one inline
  `<style>` and one inline `<script>`, and two markers `__CSP_NONCE__` and
  `__PAGE_CONFIG__`.
- `functions/classes/class_photo_upload_page/README.md`.
- `functions/classes/class_photo_upload_page/tests/__init__.py`.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`.

## Files to modify

- `templates/classes.yaml`: the page function, its log group, a new parameter
  `StaffAuthDomain`, and an output.
- `template.yaml`: the `StaffAuthDomain` parameter, passing it to `ClassesStack`, the
  `/class-photo-upload` path, and an invoke permission.
- `template-cicd.yaml`: the page function and log group in both policies; the
  auth-domain parameter in `AllowSSMParameterRead`.
- `docs/README.md`: a "Classes" group under Core Services.
- `functions/classes/class_photo_upload_api/README.md`: link to the page's README.

## Implementation details

### infra

`template.yaml` parameter:

```yaml
  StaffAuthDomain:
    Type: 'AWS::SSM::Parameter::Value<String>'
    Default: /config/cognito/staff/auth-domain
    Description: Host name of the staff pool's hosted sign-in (no scheme). Fetched from SSM.
```

Pass `StaffAuthDomain: !Ref StaffAuthDomain` in `ClassesStack.Parameters`, and declare it
in `templates/classes.yaml` (`Type: String`, `AllowedPattern: '^[A-Za-z0-9.-]+$'`).

`templates/classes.yaml`:

```yaml
  ClassPhotoUploadPageLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/asmbly/lambda/ClassPhotoUploadPageFunction-${Stage}"
      RetentionInDays: 14
      Tags:
        - Key: Project
          Value: classes:class-photo-upload

  ClassPhotoUploadPageFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub "ClassPhotoUploadPageFunction-${Stage}"
      Description: "Serves the class photo upload page (static sign-in shell; data comes from the authorized API routes)."
      CodeUri: ../functions/classes/class_photo_upload_page/
      Handler: lambda_function.lambda_handler
      Runtime: python3.12
      Timeout: 5
      LoggingConfig:
        LogGroup: !Ref ClassPhotoUploadPageLogGroup
      Environment:
        Variables:
          STAGE: !Ref Stage
          STAFF_AUTH_DOMAIN: !Ref StaffAuthDomain
          CLASS_PHOTO_APP_CLIENT_ID: !Ref ClassPhotoAppClientId
          CLASS_PHOTO_DRY_RUN: !If [IsProd, 'false', 'true']
      Tags:
        Project: classes:class-photo-upload
```

No layers, no policies (it reads nothing). Output `ClassPhotoUploadPageFunctionArn`.

`template.yaml` path (no `security`: see README Decision 7; a comment in the template
says so):

```yaml
          # The page is the sign-in entry point: a browser navigation can't carry a token.
          # It serves fixed HTML and reads nothing; its data routes below use the authorizer.
          /class-photo-upload:
            get:
              x-amazon-apigateway-integration:
                httpMethod: POST
                type: aws_proxy
                uri:
                  Fn::Sub: "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ClassesStack.Outputs.ClassPhotoUploadPageFunctionArn}/invocations"
              responses: {}
```

```yaml
  ClassPhotoUploadPageInvokePermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !GetAtt ClassesStack.Outputs.ClassPhotoUploadPageFunctionArn
      Action: lambda:InvokeFunction
      Principal: apigateway.amazonaws.com
      SourceArn: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${FacilitiesApi}/*/GET/class-photo-upload"
```

`template-cicd.yaml`:

- `AllowSSMParameterRead`: add
  `!Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/auth-domain"`.
- Stage policy: `AllowLambdaFunctionManagement` +
  `…:function:ClassPhotoUploadPageFunction-stage`; `AllowCloudWatchLogsManagement` +
  `…:log-group:/asmbly/lambda/ClassPhotoUploadPageFunction-stage*`.
- Prod policy: the same with `-prod`.

### lambda: `class_photo_upload_page/lambda_function.py`

```python
PAGE_PATH = pathlib.Path(__file__).with_name("page.html")
PAGE_SUFFIX = "/class-photo-upload"
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")

def page_url(event: dict[str, Any]) -> str | None: ...
def render_page(config: dict[str, Any], nonce: str) -> str: ...
def response_headers(auth_domain: str, nonce: str) -> dict[str, str]: ...
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]: ...
```

1. `STAFF_AUTH_DOMAIN` and `CLASS_PHOTO_APP_CLIENT_ID` required (and `STAFF_AUTH_DOMAIN`
   must match `HOST_PATTERN`); missing or invalid → log the name, 500 with a plain HTML
   "Something went wrong on our side. Try again later." page (no detail).
   `dry_run` as in phase 5.
2. `page_url`: `"https://" + requestContext.domainName + requestContext.path`, only when
   the domain matches `HOST_PATTERN` and the path ends with `PAGE_SUFFIX` (prod:
   `/class-photo-upload`; stage: `/stage/class-photo-upload`); otherwise 400 plain page.
   The URL is both the sign-in return address and the API base (`<page_url>/classes`,
   `<page_url>/submit`); it must equal a callback URL on the app client.
3. `nonce = secrets.token_urlsafe(16)`. Config:
   `{"authDomain", "clientId", "pageUrl", "dryRun"}` → `json.dumps`, then replace `<`,
   `>`, `&` with `<`, `>`, `&`; substitute for `__PAGE_CONFIG__` inside
   `<script type="application/json" id="page-config">`. Substitute `__CSP_NONCE__`.
   Read `page.html` once per container (module-level cache).
4. Headers:
   ```text
   Content-Type: text/html; charset=utf-8
   X-Content-Type-Options: nosniff
   Cache-Control: no-store
   Referrer-Policy: no-referrer
   Content-Security-Policy: default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>';
     img-src blob:; connect-src 'self' https://<auth domain>; base-uri 'none';
     form-action 'none'; frame-ancestors 'none'
   ```
5. Logs one line per request at INFO (`"Served class photo page (dry_run=%s)"`); no
   query string (it carries the sign-in `code`).

### page: `page.html`

Plain HTML, CSS and JavaScript, no libraries or outside fonts. Everything from outside
(class names, messages, pull request title and body) is inserted with `textContent` or
`<option>` text, never `innerHTML`. Sections, in order:

1. **Header** "Class photo upload", a "Sign out" link, and on stage a banner:
   "Stage: dry run. Submitting checks the photo and shows what would happen; nothing is
   opened on GitHub."
2. **Sign-in** (script, before anything is shown):
   - Read `page-config`. If the URL has `code` and `state`: check `state` against
     `sessionStorage`, POST to `https://<authDomain>/oauth2/token`
     (`application/x-www-form-urlencoded`: `grant_type=authorization_code`, `client_id`,
     `code`, `redirect_uri=<pageUrl>`, `code_verifier`), keep `id_token` and its `exp` in
     `sessionStorage`, and `history.replaceState` to `pageUrl`.
   - Without a valid, unexpired ID token: make a 32-byte random verifier and state
     (base64url), `code_challenge = base64url(SHA-256(verifier))`, save both in
     `sessionStorage`, and go to `https://<authDomain>/oauth2/authorize?response_type=code&client_id=…&redirect_uri=<pageUrl>&scope=openid&state=…&code_challenge=…&code_challenge_method=S256`.
   - Every API call sends `Authorization: <id_token>`. A 401 clears the token and signs in
     again; a 403 shows "You're not allowed to use this page."
   - Sign out: clear `sessionStorage`, go to
     `https://<authDomain>/logout?client_id=…&logout_uri=<pageUrl>`.
3. **Class**: a `<select>` filled from `GET <pageUrl>/classes`; a class with `problem` is
   listed but choosing it shows the problem and keeps Submit disabled; a `warning` shows
   under the select. While loading: "Loading classes…". On failure: the response's
   `error`, or "Couldn't load the class list. Try again in a minute."
4. **Photo**: a drop zone and a file input (`accept="image/jpeg"`). On a file:
   - read it as an `ArrayBuffer`;
   - not `FF D8 FF` → the not-JPEG message (phase 2 table);
   - remove location (Decision 18): walk segments to SOS; in the EXIF APP1, find IFD0's
     `0x8825` entry, zero the GPS IFD (its entry table, next-IFD field, and every
     out-of-line value its entries point to, by type size: 1,2,7 → 1; 3 → 2; 4,9 → 4;
     5,10 → 8), then delete the entry from IFD0 by moving the later entries up 12 bytes,
     decrementing the count, moving the next-IFD offset after the new last entry and
     zeroing the freed 12 bytes; drop each XMP APP1 segment (standard or extended) that
     matches the GPS pattern. Bytes from SOS on are copied unchanged;
   - then check the result exactly as `photo_checks.check_photo` does (size after
     removal, SOF size, orientation 5–8 swap, 1% tolerance, location) with the same
     messages, word for word;
   - when something was removed: "Location data was removed from this photo.";
   - show a preview (`URL.createObjectURL`, which `img-src blob:` allows) and the size.
5. **Warning**, directly above Submit, always visible:
   "When you submit, this photo becomes public on GitHub right away, before anyone
   reviews it. It stays visible in the pull request even if the pull request is never
   merged."
6. **Submit**, disabled until a class without a problem and an acceptable photo are
   chosen. Sends `POST <pageUrl>/submit` with JSON `{"class_name", "photo_base64"}`
   (base64 of the cleaned bytes, via `FileReader.readAsDataURL` on a `Blob`). Shows
   "Submitting…" and disables itself while waiting.
7. **Result**:
   - `opened`: "Opened pull request #N" linking to `pull_request.url`;
     `updated`: "Updated pull request #N" with the link;
   - dry run (`would_open` / `would_update`): "Dry run: nothing was opened", then the
     file path and whether it would be added or replaced, the files it would remove
     (or "none"), "Would open a new pull request" or "Would update open pull request #N",
     and the title and body in a `<pre>`;
   - warnings from the response;
   - an error: the response's `error` text as given; a network failure: "Couldn't reach
     the server. Check your connection and try again."

Keep the script readable: small named functions (`parseJpeg`, `removeLocation`,
`checkPhoto`, `ratioText`, `signIn`, `apiFetch`, `renderResult`), `const`/`let`, no
globals beyond one `state` object.

### docs

- `functions/classes/class_photo_upload_page/README.md`: what it serves, why the route has
  no authorizer, the config it embeds, the CSP, the sign-in flow, the location removal,
  and the manual checks (the page's script has no automated tests; Decision 19).
- `docs/README.md`, under "Core Services", a new "#### Classes" group:
  - **Class Photo Upload** (`ClassPhotoUploadPageFunction`, `ClassPhotoUploadApiFunction`)
    - **What it does:** signed-in staff pick a class (from Neon, read only) and upload a
      3:2 JPEG; the server checks it and a GitHub App opens or updates one pull request
      per class on `asmbly-classes` with the photo under the exact file name, removing
      other images the class list would match. Stage is a dry run.
    - **How it's triggered:** a person opens the page (HTTP `GET`); the page calls
      `GET /class-photo-upload/classes` and `POST /class-photo-upload/submit`, both behind
      the staff Cognito authorizer.
    - **URL:** `https://facilities.asmbly.org/class-photo-upload` (stage:
      `<FacilitiesApiUrl>/class-photo-upload`).
    - **Config location:** the staff pool's `class-photo-upload` app client (callback and
      sign-out URLs) in AsmblyMCPs; the GitHub App "Asmbly Class Photos" installed on
      `asmbly-classes`; secret `github/class-photo-upload-app`; SSM
      `/config/cognito/staff/*`.
    - **How to undo:** before merge, close the pull request (the photo stays visible in
      it, as the page warns); after merge, revert the merge commit on `asmbly-classes`.
      To stop new pull requests at once, uninstall the App from `asmbly-classes` or
      suspend it.

## Tests

`functions/classes/class_photo_upload_page/tests/test_lambda_function.py`:

- `test_serves_page_with_config_and_nonce`: 200, `text/html`; the config JSON parses
  and has the auth domain, client ID, page URL (`https://facilities.asmbly.org/class-photo-upload`
  for a custom-domain event) and `dryRun`; the CSP's nonce equals the `nonce` attribute
  on the `<script>` and `<style>`.
- `test_stage_page_url_includes_stage`: `domainName` `abc123.execute-api…`, `path`
  `/stage/class-photo-upload` → that URL.
- `test_config_json_cannot_close_the_script`: a client ID of
  `x</script><script>alert(1)</script>` (from a patched environment) appears only as
  `</script>…`; the page contains exactly one `</script>` for the JSON block
  and one for the program.
- `test_csp_header`: exact directives above; `connect-src` has the auth domain;
  no `unsafe-inline`.
- `test_nonce_changes_per_request`.
- `test_missing_env_returns_500_without_details` and
  `test_invalid_auth_domain_returns_500`.
- `test_unexpected_path_returns_400`, `test_bad_domain_returns_400`.
- `test_page_has_public_warning_above_submit`: the warning text appears before the Submit
  button in the HTML.
- `test_page_messages_match_server_messages`: each message constant from
  `photo_checks` (with its `{…}` placeholders as written in the script's templates) and
  the API's error strings appear in `page.html`, so the browser and the server say the
  same thing.
- `test_page_uses_text_content_not_inner_html`: `innerHTML` does not occur in
  `page.html`.
- `test_logs_hold_no_query_string`: an event with `?code=SECRETCODE` → `SECRETCODE` not
  in `caplog`.

`tests/test_templates.py`:

- `test_class_photo_page_route_is_the_only_unauthorized_class_photo_route`: under
  `/class-photo-upload*`, only `/class-photo-upload` `get` lacks `security`.

## Acceptance criteria

1. `GET /class-photo-upload` serves the page; it shows nothing but the sign-in redirect
   until a valid ID token is held, and returns from sign-in to the same URL. (#104 AC1)
2. Class names are rendered as text; the config can't break out of its script block.
   (#104 AC5)
3. The page refuses non-JPEG, unreadable, non-3:2 or portrait (after orientation) and
   over-4 MB photos with phase 2's messages before upload, and keeps Submit disabled
   until the class and photo pass. (#105 AC1–AC5)
4. The page removes EXIF GPS and GPS-bearing XMP before upload without touching the
   compressed image data or the orientation flag, and says so. (#106 AC1–AC3)
5. The public-on-GitHub warning is directly above Submit. (#107 AC1)
6. After Submit the page links to the opened or updated pull request ("Opened" /
   "Updated pull request #N"), or shows the dry-run report on stage, or the server's
   plain error. (#107 AC2, AC7; #108 AC3; #109 AC2)
7. Both deploy-role policies list `ClassPhotoUploadPageFunction-{stage,prod}` and their
   log groups; the shared read lists `/config/cognito/staff/auth-domain`.
8. `docs/README.md` lists the page under Core Services with how it is triggered, its URL,
   its config location and how to undo a change. (#73 "Done when")
9. `pytest`, `cfn-lint`, `sam validate` and `sam build` pass.

## Verification

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

On stage, after all admin actions (MANUAL_QA.md holds the full list, by story):

- Open `<stage FacilitiesApiUrl>/class-photo-upload` in a private window → staff
  sign-in → back on the page with the class list and the dry-run banner.
- Drop a PNG renamed `.jpg` → not-JPEG message; a 4:3 photo → the 4:3 message; a phone
  photo with location → "Location data was removed from this photo."; a 3:2 JPEG →
  Submit enabled.
- Submit → "Dry run: nothing was opened" with the file name, removals and the pull
  request it would open; nothing on `asmbly-classes`.
- `exiftool -gps:all <downloaded cleaned file>` (or the page's own check) shows no GPS;
  `cmp` of the bytes after the SOS marker with the original shows no difference.

On prod, after promotion: the same flow opens a pull request on `asmbly-classes`; a
second photo for the same class updates it.

## Admin actions

- README admin action 1 (`/config/cognito/staff/auth-domain`) and 2 (redeploy the deploy
  role) **before this reaches `stage`**.
- README admin action 3 (the app client's callback and sign-out URLs) before stage
  testing.

## Hand-off

Feature complete: the page, its two data routes, docs. The pull request that lands this
phase says `Closes #104, #105, #106, #107, #108, #109`, and `Closes #73` once every item in
#73's "Done when" is checked.
