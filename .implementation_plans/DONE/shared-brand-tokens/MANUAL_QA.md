# Manual QA: Shared brand tokens

Acceptance steps for `feature/shared-brand-tokens`, by story, so each check maps back to
#138 (epic #136).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`. Prod stays unchanged until
`/promote`, so it is the "before" these steps compare stage with.

> Automated checks already passed on the branch (integration gate, before the docs
> commit): pytest 1871 passed, 8 subtests passed; cfn-lint 0 errors, and the 4 W3005
> warnings in `template.yaml` (lines 582, 592 and 605 twice) are byte-identical to
> `origin/stage`; sam validate pass; sam build pass. Nothing was skipped. Run again at
> bba0614 while writing this: pytest 1871 passed, 8 subtests passed. These steps cover
> what a person should see in a browser, in the HTTP headers, and in AWS.

## Prerequisites

- **Admin actions: none.** The checkpoint lists none. Nothing changes in the deploy role
  (`template-cicd.yaml`), and there's no new secret or SSM parameter. The photo
  function's new layer comes from the `CommonLayerARN` parameter that
  `templates/classes.yaml` already had.
- **Risk while the stage deploy runs:** the deploy publishes a new `common-layer-stage`
  version and updates the 12 functions that use it (the 11 that already did, plus
  `ClassPhotoUploadPageFunction`). For a few seconds during that update, stage may answer
  502. Start once the "Deploy Staging Pipeline" run is green. If a step still gets a 502,
  wait a few seconds and try again.
- If `/promote` has already run, prod has this change too and can't serve as the "before".
  In that case, rely on the pins (step 14) for steps 1 to 3.
- The stage API address. Stage has no custom domain. This is the stage stack's
  `FacilitiesApiUrl` output, built from the `FacilitiesApi` resource. Run every step from
  the repository root:

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  PROD_URL="https://facilities.asmbly.org"
  QA_DIR=$(mktemp -d)   # pages and headers saved below go here, outside the repository
  ```

  | Page | Stage | Prod |
  | --- | --- | --- |
  | Kiln drop-off viewer | `$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer` | `https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer` |
  | Class photo upload page | `$STAGE_API_URL/class-photo-upload` | `https://facilities.asmbly.org/class-photo-upload` |

- **Don't use `curl -I`.** It sends a HEAD request, and these routes accept only GET, so
  API Gateway answers `403` with `x-amzn-errortype: MissingAuthenticationTokenException`
  on prod and stage alike. The steps use GET with `-D` to save the headers.
- Access to:
  - Chrome or Firefox with responsive mode. In Chrome: DevTools, **Toggle device
    toolbar**, **Dimensions: Responsive**. In Firefox: **Responsive Design Mode**.
  - A staff account in the staff user pool, for the photo page in a browser (step 3).
  - AWS CLI credentials for us-east-2 that can read CloudFormation, Lambda and the
    CloudWatch log group `/asmbly/lambda/ClassPhotoUploadPageFunction-stage`. Optional
    step 7 also needs `lambda:InvokeFunction` on `ClassPhotoUploadPageFunction-stage`.
  - This repository's `.venv`, created as in `CLAUDE.md` (steps 1 and 12 to 17), plus
    `python3` and `openssl` (steps 4 and 5).

Both pages are public GET routes, so no step needs a webhook, a Slack signature or a
token. The only sign-in is the photo page's own staff sign-in, in step 3.

---

## #138: Brand colours, type, spacing and the Asmbly logo come from one place (phases 1, 2)

### Visitors see no change

1. Save both pages from stage and from prod, then compare what each serves: the `:root`
   tokens, the CSS rules after `:root`, and the markup. The script uses the
   repository's own `tests/page_style.py`, the parser the pin tests use.

   ```bash
   curl -s -o "$QA_DIR/kiln-stage.html"  "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
   curl -s -o "$QA_DIR/kiln-prod.html"   "$PROD_URL/KilnOpsDropoffRecentEntriesViewer"
   curl -s -o "$QA_DIR/photo-stage.html" "$STAGE_API_URL/class-photo-upload"
   curl -s -o "$QA_DIR/photo-prod.html"  "$PROD_URL/class-photo-upload"
   .venv/bin/python - "$QA_DIR" <<'EOF'
   import re, sys
   from tests import capture_page_pins, page_style

   STYLE = re.compile(r'<style(?: nonce="[A-Za-z0-9_-]+")?>(.*?)</style>', re.S)

   def markup(page: str) -> str:
       """The page without its <style>, nonces and page config, whitespace collapsed."""
       page = re.sub(r"<style\b.*?</style>", "", page, flags=re.S)
       page = re.sub(r'nonce="[A-Za-z0-9_-]+"', 'nonce=""', page)
       page = re.sub(r'(id="page-config">).*?(</script>)', r"\1\2", page, flags=re.S)
       return " ".join(page.split())

   for name in ("kiln", "photo"):
       stage, prod = (open(f"{sys.argv[1]}/{name}-{where}.html", encoding="utf-8").read() for where in ("stage", "prod"))
       s, p = (page_style.Stylesheet.from_page(page, STYLE) for page in (stage, prod))
       same = lambda a, b: "same" if a == b else "DIFFERENT"
       print(f"{name}: tokens {same(s.tokens(), p.tokens())}, "
             f"rules {same(capture_page_pins.pinned_rules_text(s), capture_page_pins.pinned_rules_text(p))}, "
             f"markup {same(markup(stage), markup(prod))}")
   EOF
   ```

   **Expect:**

   ```text
   kiln: tokens same, rules same, markup DIFFERENT
   photo: tokens same, rules same, markup same
   ```

   For the kiln page, only `tokens` and `rules` must be `same`. Its markup holds the
   drop-off list, and stage's ClickUp list isn't prod's, so `markup` is `same` only when
   both lists happen to hold the same rows (both empty, for example). For the photo
   page, all three must be `same`. The stage dry-run banner is in both pages' markup
   (as `<p id="dry-run-banner" class="banner" hidden>`), and the page's script shows it
   when its page config says `"dryRun": true`. The page config is the one part that
   differs, and the script masks it. When this script was run on bba0614, comparing
   prod's pages with this branch's rendered shells, it printed `same` for the tokens
   and rules of both pages and for the photo page's markup.
2. Open the kiln page on stage (`echo "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"`)
   and on prod in two windows. In responsive mode, set the width to **320**, compare,
   then set it to **1280** and compare.
   **Expect:** at both widths, the two pages look the same:
   - the full-width header band in the ceramics colour, with the ceramics icon and the
     title in Asmbly White;
   - the hint above the **Refresh** button;
   - the table, or "No submissions found in the last 24 hours. Please try refreshing."
     when that stage has no drop-offs from the last 24 hours;
   - the Asmbly logo in Asmbly Purple in the footer.

   Colours, fonts, spacing and logo match. Only the list's rows differ. At 320px nothing
   scrolls sideways, and the table's text wraps. The browser console shows no
   Content-Security-Policy violation. The one message to expect is for the browser's own
   `/favicon.ico` request, shown as blocked or as a 403, which is older than this change.
   If stage shows the error page ("Could not retrieve the list of submissions."), it uses
   the same shell, so compare its band, button and logo. The cause is then in
   `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-stage`. The list shows
   drop-off names, so don't attach a screenshot of prod's list to the pull request or
   an issue.
3. Open the photo page on stage (`echo "$STAGE_API_URL/class-photo-upload"`) and on prod.
   Each sends you to the staff pool's sign-in. Sign in with a staff account on both.
   Compare at **320** and at **1280** wide. **Don't press Submit on prod**: there, it
   opens or updates a pull request on `asmbly-classes`.
   **Expect:** at both widths, the two pages look the same:
   - the full-width Asmbly Purple band, with the Asmbly logo, "Class photo upload" and
     **Sign out**;
   - the pattern strip under the band;
   - the **Class** list, **Choose a photo** and **Submit**, with the same colours,
     fonts, spacing and logo.

   The one difference allowed is on stage: under the band, the banner "Stage: dry run.
   Submitting checks the photo and shows what would happen; nothing is opened on
   GitHub." (dark text on the light woodwork tint, with a purple edge and "i"). Prod has
   no banner. The class names come from each stage's own data and may differ. At 320px
   nothing scrolls sideways, and the console shows no Content-Security-Policy violation.

### The pages' Content-Security-Policy

4. Kiln: one GET, then check the policy's 5 directives and that its hash is the hash of
   the `<style>` the page served.

   ```bash
   curl -s -D "$QA_DIR/kiln.headers" -o "$QA_DIR/kiln.html" "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
   grep -i '^content-security-policy' "$QA_DIR/kiln.headers"
   python3 -I -c '
   import base64, hashlib, re, sys
   head, body = (open(p, "rb").read() for p in sys.argv[1:3])
   csp = re.search(rb"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$", head).group(1).decode()
   print("directives:", len([d for d in csp.split(";") if d.strip()]))
   sent = re.search(r"style-src .sha256-([A-Za-z0-9+/=]+).", csp).group(1)
   styles = re.findall(rb"<style>(.*?)</style>", body, re.S)
   served = base64.b64encode(hashlib.sha256(styles[0]).digest()).decode()
   print("style blocks:", len(styles)); print("header hash:", sent); print("served hash:", served)
   print("MATCH" if sent == served else "MISMATCH")
   ' "$QA_DIR/kiln.headers" "$QA_DIR/kiln.html"
   ```

   You can also hash the served `<style>` with `openssl` and compare the result by eye
   with the header:

   ```bash
   python3 -I -c 'import re,sys; sys.stdout.buffer.write(re.search(rb"<style>(.*?)</style>", open(sys.argv[1],"rb").read(), re.S).group(1))' "$QA_DIR/kiln.html" | openssl dgst -sha256 -binary | openssl base64 -A; echo
   ```

   **Expect:** the header is
   `content-security-policy: default-src 'none'; style-src 'sha256-<hash>'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
   and the script prints `directives: 5`, `style blocks: 1`, two equal hashes and
   `MATCH`. The hash is not prod's, and that is expected. The shared tokens now sit in a
   block of their own in `:root`, so the `<style>` text changed while its tokens and
   rules did not (step 1). At bba0614 the served hash is
   `sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8=`. Prod's on 2026-10-17 was
   `sha256-zwmov6/DM5/2u9QG+pB5W5x0clfW7jxavUDA6lkQdA4=`. A later change to either
   `page.html` or `brand.py` changes the hash again, so `MATCH` is what counts.
5. Photo: two GETs, then check the policy's 8 directives, that each request gets its
   own nonce, and that the `<style>` and `<script>` carry it.

   ```bash
   for i in 1 2; do
     curl -s -D "$QA_DIR/photo-$i.headers" -o "$QA_DIR/photo-$i.html" "$STAGE_API_URL/class-photo-upload"
     grep -i '^content-security-policy' "$QA_DIR/photo-$i.headers"
   done
   python3 -I -c '
   import re, sys
   nonces = []
   for i in (1, 2):
       head, body = (open(f"{sys.argv[1]}/photo-{i}.{ext}", encoding="utf-8").read() for ext in ("headers", "html"))
       csp = re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*$", head).group(1)
       script, style = (re.search(k + r" .nonce-([A-Za-z0-9_-]+).", csp).group(1) for k in ("script-src", "style-src"))
       nonces.append(script)
       print(f"request {i}: {len([d for d in csp.split(chr(59)) if d.strip()])} directives, nonce {script},",
             "style-src same:", style == script, "| body uses it:", f"<style nonce=\"{script}\">" in body and f"<script nonce=\"{script}\">" in body)
   print("nonces differ:", nonces[0] != nonces[1])
   ' "$QA_DIR"
   ```

   **Expect:** two headers of the form
   `content-security-policy: default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>'; img-src blob:; connect-src 'self' https://<staff sign-in host>; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
   each with a different `<n>`. The script prints, for each request,
   `8 directives, nonce <n>, style-src same: True | body uses it: True`, and then
   `nonces differ: True`. Prod gives the same shape (unchanged).

### The photo page and its 400 and 500 pages answer as before

6. The page itself:

   ```bash
   curl -s -o "$QA_DIR/photo.html" -w '%{http_code} %{content_type}\n' "$STAGE_API_URL/class-photo-upload"
   grep -o 'id="page-config">[^<]*' "$QA_DIR/photo.html"
   grep -o '<p id="dry-run-banner"[^>]*>' "$QA_DIR/photo.html"
   ```

   **Expect:**
   - `200 text/html; charset=utf-8`;
   - the page config,
     `{"authDomain": "<staff sign-in host>", "clientId": "<app client ID>", "pageUrl": "https://<api-id>.execute-api.us-east-2.amazonaws.com/stage/class-photo-upload", "dryRun": true}`
     (public values only);
   - `<p id="dry-run-banner" class="banner" hidden>`.

   On prod, the same commands show `"dryRun": false` and
   `"pageUrl": "https://facilities.asmbly.org/class-photo-upload"`.
7. *(Optional: needs `lambda:InvokeFunction` on the stage function.)* The 400 page.
   Through API Gateway, a person can't cause it: the function checks the host and path
   in the request context, and API Gateway sets them. Invoke the stage function directly
   instead, with the tests' event and a host that isn't one. The page function reads
   nothing, calls nothing and changes nothing.

   ```bash
   python3 -I -c 'import json, sys; e = json.load(open(sys.argv[1])); e["requestContext"]["domainName"] = "evil.example/x"; print(json.dumps(e))' \
     functions/classes/class_photo_upload_page/tests/fixtures/api_event_page.json > "$QA_DIR/photo-400-event.json"
   aws lambda invoke --function-name ClassPhotoUploadPageFunction-stage --region us-east-2 \
     --payload "fileb://$QA_DIR/photo-400-event.json" "$QA_DIR/photo-400.json"
   python3 -I -c 'import json, sys; r = json.load(open(sys.argv[1])); print(r["statusCode"]); print(r["body"])' "$QA_DIR/photo-400.json"
   ```

   **Expect:** `400` and a plain page whose body is
   `<p>This page can&#x27;t be opened from this address.</p>`, with no `page-config`.
   The log group `/asmbly/lambda/ClassPhotoUploadPageFunction-stage` gets
   `Refused the class photo page for an unexpected host or path`, without the host or
   the path. That is the same answer as before. The diff changes only how `_template()`
   reads `page.html`; it doesn't touch the error pages.
8. The 500 page. A person can't cause it on stage. It needs a missing or invalid
   `STAFF_AUTH_DOMAIN` or `CLASS_PHOTO_APP_CLIENT_ID`, and those change only through the
   templates. The tests cover it, along with the 400 cases:

   ```bash
   .venv/bin/python -m pytest -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py -k "returns_400 or returns_500"
   ```

   **Expect:** `15 passed` (at bba0614). The tests are
   `test_missing_env_returns_500_without_details`, `test_invalid_auth_domain_returns_500`,
   `test_unexpected_path_returns_400`, `test_bad_domain_returns_400` and
   `test_event_without_request_context_returns_400`. The 500 page says "Something went
   wrong on our side. Try again later.", with no variable name or value in it.

### The photo function has only CommonLayer

9. Read the layers of the photo function and of the kiln function, which already used
   the common layer:

   ```bash
   aws lambda get-function-configuration --function-name ClassPhotoUploadPageFunction-stage \
     --region us-east-2 --query Layers
   aws lambda get-function-configuration --function-name KilnDropoffRecentEntriesViewerFunction-stage \
     --region us-east-2 --query 'Layers[].Arn'
   ```

   **Expect:** the photo function lists exactly one layer, whose `Arn` ends in
   `:layer:common-layer-stage:<version>`. Before this change it had no layers. The kiln
   function's list includes the same `common-layer-stage:<version>`, because the deploy
   moved all 12 functions that use the layer to the new version.
10. Check the photo function's log group after the requests above (the first one ran the
    new code's imports). `aws logs tail` needs AWS CLI v2:

    ```bash
    aws logs tail /asmbly/lambda/ClassPhotoUploadPageFunction-stage --region us-east-2 --since 1h > "$QA_DIR/photo.log"
    grep -c 'Served class photo page' "$QA_DIR/photo.log"
    grep -E 'ImportModuleError|No module named|Traceback' "$QA_DIR/photo.log" || echo "no import errors"
    ```

    **Expect:** a count of at least 1. Steps 1, 5 and 6 each served the page, which logs
    `Served class photo page (dry_run=...)`. Then `no import errors`. If more than an
    hour has passed since step 6, widen `--since`.

### Page sizes

11. Measure what stage serves:

    ```bash
    curl -s "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer" | wc -c
    curl -s "$STAGE_API_URL/class-photo-upload" | wc -c
    curl -s "$PROD_URL/class-photo-upload" | wc -c
    ```

    **Expect:** the kiln page is under 61440 bytes (60 KB) with however many drop-offs
    stage lists. The photo page is under 102400 bytes (100 KB) and within about 1 KB of
    prod's (prod's was 70193 bytes on 2026-10-17). Stage rarely lists 50 drop-offs, so
    step 12 checks 50 rows.
12. The kiln page with 50 drop-offs, rendered locally the way
    `test_page_with_50_dropoffs_is_under_60kb` renders it (60-character names):

    ```bash
    PYTHONPATH=layers/common/python .venv/bin/python -c '
    from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as kiln
    tasks = [{"id": f"id{i}", "custom_id": f"KO-{1000 + i}", "name": "N" * 60, "date_created": str(1704067200000 + i)} for i in range(50)]
    print(len(kiln.generate_html_page(tasks).encode("utf-8")), "bytes with 50 rows (limit 61440)")'
    ```

    **Expect:** a number under 61440. At bba0614 it is
    `26562 bytes with 50 rows (limit 61440)`. In the suite,
    `test_page_with_50_dropoffs_is_under_60kb` (kiln) and `test_served_page_is_small`
    (photo, under 100 KB) hold these limits.

### Local steps a reviewer can run

13. The whole suite:

    ```bash
    .venv/bin/python -m pytest -q
    ```

    **Expect:** `1871 passed, 8 subtests passed` at bba0614. More tests if `stage` has
    gained some since, but none failing.
14. The pins: the tokens and rules each page serves must equal what `stage` served at
    6fd11c9, before this change.

    ```bash
    .venv/bin/python -m pytest -q functions/ceramics/kiln_dropoff_recent_entries_viewer functions/classes/class_photo_upload_page \
      -k "served_tokens_are_the_stage_tokens or served_rules_are_the_stage_rules"
    ```

    **Expect:** `4 passed`: `test_served_tokens_are_the_stage_tokens` and
    `test_served_rules_are_the_stage_rules`, for each page. The kiln pair checks every
    page the kiln function serves.
15. Changing one shared token changes both pages:

    ```bash
    .venv/bin/python -m pytest -q "tests/test_shared_brand.py::test_changing_a_shared_token_changes_both_pages"
    ```

    **Expect:** `1 passed`. The test changes a shared token in `common.brand`, sees the
    new value on both served pages, restores it, and sees `#292D6A` back on both.
16. The rest of the shared-brand tests and the brand module's own:

    ```bash
    .venv/bin/python -m pytest -q tests/test_shared_brand.py layers/common/tests/test_brand.py
    ```

    **Expect:** `17 passed`. Among them:
    - `test_page_html_has_no_copy_of_the_shared_tokens_or_logo`;
    - `test_logo_matches_both_pages`;
    - `test_photo_page_imports_no_third_party_module` (the photo function, with only the
      common layer, loads no boto3 or `requests`);
    - `test_brand_imports_only_the_standard_library`.
17. The capture script reproduces the committed pins:

    ```bash
    .venv/bin/python -m tests.capture_page_pins
    git status --short -- functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/fixtures functions/classes/class_photo_upload_page/tests/fixtures
    ```

    **Expect:** the script prints `kiln: 54 tokens, 39 rule lines` and
    `photo: 79 tokens, 105 rule lines`, and `git status` prints nothing. If `git status`
    lists a fixture, the step failed: report it, and restore the fixtures with
    `git checkout -- <those paths>`.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
