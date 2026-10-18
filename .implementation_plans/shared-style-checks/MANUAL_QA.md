# Manual QA: Shared style checks

Acceptance steps for `feature/shared-style-checks`, by story, so each check maps back to
#137 (epic #136).

This change is test code and docs only. `tests/page_style.py` now holds the style checks
that the kiln drop-off viewer's and the class photo upload page's tests each had a copy
of, and each page's test file keeps only that page's data. No page, handler, template or
configuration changes (story #137's last criterion), so nothing a person sees should
change.

- Steps 1 to 7 verify the change on your machine. They can run before or after the merge.
- Steps 8 to 14 run on the **stage stack**, after the pull request merges to `stage` and
  the "Deploy Staging Pipeline" run is green, and before `/promote`. They check that both
  pages still load, look as they did, and send the same Content-Security-Policy. Step 8 is
  an optional baseline taken before the merge.

> Automated checks already passed on the branch: pytest 1847 passed (8 subtests, 0
> skipped), cfn-lint 4 W3005 warnings in `template.yaml` (lines 582, 592, 605 twice),
> byte-identical to `origin/stage`, sam validate pass, sam build pass. Nothing was
> skipped. These steps cover what a reviewer can see on their machine and in a browser.

## Prerequisites

- Admin actions: **none**. The checkpoint lists no admin action. The change adds no AWS
  resource, so the deploy role (`template-cicd.yaml`) needs no redeploy.
- A checkout of `feature/shared-style-checks` for steps 1 to 7, with the virtual
  environment from `CLAUDE.md`
  (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt cfn-lint`)
  and the SAM CLI.
- The stage API address. Stage has no custom domain. This needs read-only AWS credentials
  for the account:

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  ```

  It is also the `FacilitiesApiUrl` output of `AsmblyFacilitiesMaintTrackingStack-stage`.
- A desktop browser with developer tools: responsive mode to set the 320px and 1280px
  widths, and the console to see Content-Security-Policy violations.
- A staff account that can sign in to the stage class photo upload page (the staff
  Cognito pool). Only the page's look is checked. Nothing is submitted.
- If a page doesn't load, look in the log groups
  `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-stage` and
  `/asmbly/lambda/ClassPhotoUploadPageFunction-stage`.

---

## #137: Both pages' style checks come from one test module (phase 1)

### On your machine

1. Confirm that the only deployable folders the change touches hold test and docs files.

   ```bash
   git fetch origin
   git diff --name-only origin/stage...HEAD -- functions layers templates template.yaml \
     template-cicd.yaml configs samconfig.toml
   ```

   **Expect:** exactly these four files. Neither `page.html` nor any
   `lambda_function.py` is in the list:

   ```text
   functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md
   functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py
   functions/classes/class_photo_upload_page/README.md
   functions/classes/class_photo_upload_page/tests/test_lambda_function.py
   ```

2. Run each test file on its own.

   ```bash
   .venv/bin/python -m pytest -q tests/test_page_style.py
   .venv/bin/python -m pytest -q functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py
   .venv/bin/python -m pytest -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py
   ```

   **Expect:** `16 passed`, `73 passed`, `113 passed`. The kiln and class photo counts
   match `origin/stage`: the refactor kept every test ID.

3. Run the shared module's own failing-case tests.

   ```bash
   .venv/bin/python -m pytest -v tests/test_page_style.py \
     -k "below_4_5 or unused_token or missing_path or packaged_folder"
   ```

   **Expect:** `4 passed, 12 deselected`. Each test gives a check an input the check must
   report:
   - `test_contrast_below_4_5_is_reported`: #777777 on #ffffff is reported as
     `4.48:1, below 4.5:1`, and #767676 passes.
   - `test_unused_token_is_reported`: a token that no `var()` reads.
   - `test_logo_with_a_missing_path_is_reported`: the official logo with one of its 17
     paths removed.
   - `test_page_style_is_outside_every_packaged_folder`: no template's `CodeUri` or
     `ContentUri` contains `tests/page_style.py`.

4. Change one brand colour in the kiln page and check that the named test fails.

   ```bash
   perl -pi -e 's/--asmbly-purple: #292D6A;/--asmbly-purple: #292D6B;/' \
     functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html
   .venv/bin/python -m pytest -q functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py
   git checkout -- functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html
   git status --short
   ```

   **Expect:** `1 failed, 72 passed`. The failure is `test_brand_tokens_match_the_guide`,
   and its message lists `'--asmbly-purple is #292D6B, the guide says #292D6A'`. After
   `git checkout`, `git status --short` doesn't list `page.html`.

5. Do the same in the class photo upload page.

   ```bash
   perl -pi -e 's/--asmbly-purple: #292D6A;/--asmbly-purple: #292D6B;/' \
     functions/classes/class_photo_upload_page/page.html
   .venv/bin/python -m pytest -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py
   git checkout -- functions/classes/class_photo_upload_page/page.html
   git status --short
   ```

   **Expect:** `3 failed, 110 passed`. The failures are `test_brand_tokens_match_the_guide`
   (same message as step 4), and `test_derived_tokens_follow_the_formula` for
   `--asmbly-purple-60` and for `--asmbly-purple-20`, the two tints this page derives from
   Asmbly Purple. After `git checkout`, `git status --short` doesn't list `page.html`.

6. Break one check in the shared module and check that both pages' tests fail.

   ```bash
   perl -pi -e 's/if ratio < minimum:/if ratio < minimum + 100:/' tests/page_style.py
   .venv/bin/python -m pytest -q tests/test_page_style.py \
     functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py \
     functions/classes/class_photo_upload_page/tests/test_lambda_function.py
   git checkout -- tests/page_style.py
   ```

   **Expect:** `35 failed, 167 passed`:
   - all 13 cases of the kiln page's `test_colour_pairs_meet_contrast`
   - all 21 cases of the class photo page's `test_brand_colour_pairs_meet_contrast`
   - `test_contrast_below_4_5_is_reported`

   One edit reaches both pages, so the contrast logic exists in one place only. After
   `git checkout`, run the same pytest command again. **Expect:** `202 passed`, and
   `git status --short` doesn't list `tests/page_style.py`.

7. Build, then check that the module isn't packaged.

   ```bash
   sam build
   find .aws-sam/build -name page_style.py -o -name test_page_style.py
   ```

   **Expect:** `sam build` succeeds, and `find` prints nothing. The build does hold the
   functions' own tests (19 `test_*.py` files at 64b140a), because they sit inside each
   function's folder. The repository-root `tests/` is in no function's folder. Don't
   commit `.aws-sam/`.

### On the stage stack

8. **Before the merge (optional baseline).** Stage serves the same two `page.html` files
   before and after this merge, so a baseline taken before the merge is the closest
   comparison. Take the screenshots from steps 9, 10, 12 and 13, and save the output of
   steps 11 and 14. Without a baseline, compare against the look each function's README
   describes: "Look and brand tokens" in
   `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md`, and "How It Looks"
   in `functions/classes/class_photo_upload_page/README.md`.

   Run steps 9 to 14 after the merge, once the "Deploy Staging Pipeline" run is green.

9. Open the kiln drop-off viewer in a window 1280px wide.

   ```bash
   echo "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
   ```

   **Expect:** the list loads. If nothing was dropped off in the last 24 hours, you see
   "No submissions found in the last 24 hours. Please try refreshing." instead. Check:
   - the header band is in the ceramics colour, with the ceramics icon and the title in
     Asmbly White
   - the table's header row is on the light ceramics tint
   - drop-off IDs are bold and monospace
   - each time ends in `CST` or `CDT`
   - Refresh reloads the page
   - the Asmbly logo is at the foot in Asmbly Purple
   - the console shows no Content-Security-Policy violation
   - everything matches the baseline

   If you see "Could not retrieve the list of submissions.", the error page loaded. This
   change can't cause that (ClickUp, SSM or Secrets Manager failed: see the log group),
   but the error page must still be styled the same way.

10. Narrow the same page to 320px.
    **Expect:**
    - nothing scrolls sideways
    - long names wrap
    - each drop-off ID stays on one line
    - the time wraps only between the date and the time
    - the band holds only the icon and the title
    - everything matches the baseline

11. Show the kiln page's security headers, and compute the style hash they must carry.
    `curl -sI` sends a HEAD request, but the template defines only `get` on both routes,
    so a HEAD request doesn't reach the function. These commands send a GET and print
    only the headers:

    ```bash
    curl -s -o /dev/null -D - "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer" \
      | grep -i -E '^(HTTP|content-security-policy|content-type|cache-control|x-content-type-options)'
    git fetch origin
    git show origin/stage:functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html | python3 -c \
      "import re,sys,hashlib,base64; s=re.search(r'<style>(.*?)</style>', sys.stdin.read(), re.S).group(1); print(base64.b64encode(hashlib.sha256(s.encode('utf-8')).digest()).decode())"
    ```

    **Expect:** status `200`. The error page from step 9 returns `500` with the same
    headers. The header names may be in lower case. The headers:

    ```text
    Content-Type: text/html; charset=utf-8
    X-Content-Type-Options: nosniff
    Cache-Control: no-store
    Content-Security-Policy: default-src 'none'; style-src 'sha256-<hash>'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
    ```

    `<hash>` is the value the Python line prints. At 64b140a it is
    `zwmov6/DM5/2u9QG+pB5W5x0clfW7jxavUDA6lkQdA4=`, and `origin/stage` before the merge
    has the same value. The whole line matches the baseline.

12. Open the class photo upload page in a window 1280px wide, and sign in with the staff
    account.

    ```bash
    echo "$STAGE_API_URL/class-photo-upload"
    ```

    **Expect:**
    - a full-width Asmbly Purple band with the Asmbly logo, "Class photo upload" and
      **Sign out**, then the decorative pattern strip
    - under them, the banner "Stage: dry run. Submitting checks the photo and shows what
      would happen; nothing is opened on GitHub."
    - the **Class** list fills
    - one column, up to 760px wide
    - **Choose a photo** is Asmbly Purple with Asmbly White text
    - the console shows no Content-Security-Policy violation
    - everything matches the baseline

    Don't submit anything.

13. Narrow the same page to 320px.
    **Expect:**
    - nothing scrolls sideways
    - the header wraps
    - the pattern is cut off
    - the text wraps
    - everything matches the baseline

14. Show the class photo page's policy for two requests. This route is also GET-only, so
    the command uses GET instead of `curl -sI`.

    ```bash
    for i in 1 2; do
      curl -s -o /dev/null -D - "$STAGE_API_URL/class-photo-upload" \
        | grep -i -E '^(HTTP|content-security-policy)'
    done
    ```

    **Expect:** status `200` both times, and each time:

    ```text
    Content-Security-Policy: default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>'; img-src blob:; connect-src 'self' https://<auth domain>; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
    ```

    - Within one response, `<n>` is the same in `script-src` and `style-src`.
    - The second response has a different `<n>`: the page makes a fresh nonce for each
      request.
    - `<auth domain>` is the staff pool's sign-in host (SSM
      `/config/cognito/staff/auth-domain`).
    - Apart from the nonce, the line matches the baseline.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

cfn-lint reports the 4 W3005 warnings in `template.yaml` that `origin/stage` already has.
