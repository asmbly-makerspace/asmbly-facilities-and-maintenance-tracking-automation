# Manual QA: Shared CSP helper

Acceptance steps for `feature/shared-csp-helper`, by story, so each check maps back to
#139 (epic #136).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`. Prod stays unchanged until
`/promote`, so it is one of the "befores" these steps compare stage with. For the kiln
page it is not a byte-for-byte "before": see step 1.

> Automated checks already passed on the branch (integration gate): pytest 1943 passed,
> 8 subtests passed; cfn-lint 0 errors, and the 4 W3005 warnings in `template.yaml` are
> byte-identical to `origin/stage`; sam validate pass; sam build pass. Nothing was
> skipped. Run again at 6e71ad3 while writing this: pytest 1943 passed, 8 subtests
> passed. The scripts in steps 1 to 5 were run against stage (still at 07b9b79, before
> the merge) and prod on 2026-10-17, and printed what their **Expect** says. Steps 8 and
> 9 use the AWS CLI and were not run while writing this. These steps cover what a person
> should see in a browser, in the HTTP headers, and in AWS.

## Prerequisites

- **Admin actions: none.** The checkpoint lists none. Nothing changes in the deploy role
  (`template-cicd.yaml`) or the templates, and there's no new secret, SSM parameter or
  layer. `common/csp.py` goes into the existing common layer, which both page functions
  already use.
- **Risk while the stage deploy runs:** the deploy publishes a new `common-layer-stage`
  version and updates the 12 functions that use it. For a few seconds during that
  update, stage may answer 502. Start once the "Deploy Staging Pipeline" run is green.
  If a step still gets a 502, wait a few seconds and try again. Both page functions now
  import `csp` from the layer as they start, so a 502 that doesn't go away means the
  function can't load it: step 8 checks the layer and the logs.
- If `/promote` has already run, prod has this change too and can't serve as a "before".
  Rely on step 1's recorded stage value and the pins (step 14) instead.
- If another pull request that changes the kiln page's `page.html` or
  `layers/common/python/common/brand.py` merged to `stage` after 07b9b79, the kiln hash
  changes for that reason. Check with
  `git log --oneline 07b9b79..origin/stage -- functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html layers/common/python/common/brand.py`.
  This pull request touches neither file, so the command lists nothing unless another
  one did. If it lists a commit, step 3's `MATCH` and the pins (step 14) are the check
  for the kiln header instead of step 1's `stage vs before the merge` line.
- The stage API address. Stage has no custom domain. On 2026-10-17 it was
  `https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage`. Run every step from the
  repository root:

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
  API Gateway answers `403`. The steps use GET with `-D` to save the headers.
- Access to:
  - Chrome or Firefox with responsive mode. In Chrome: DevTools, **Toggle device
    toolbar**, **Dimensions: Responsive**. In Firefox: **Responsive Design Mode**.
  - A staff account in the staff user pool, for the photo page in a browser (step 7).
  - AWS CLI v2 credentials for us-east-2 that can read CloudFormation, Lambda and the
    CloudWatch log groups `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-stage`
    and `/asmbly/lambda/ClassPhotoUploadPageFunction-stage`. Optional step 9 also needs
    `lambda:InvokeFunction` on `ClassPhotoUploadPageFunction-stage`.
  - This repository's `.venv`, created as in `CLAUDE.md` (steps 5 and 11 to 17), and
    `python3`.

Both pages are public GET routes, so no step needs a webhook, a Slack signature or a
token. The only sign-in is the photo page's own staff sign-in, in step 7. The kiln page
lists drop-off names, so don't attach its saved HTML or a screenshot of prod's list to
the pull request or an issue.

---

## #139: A new page can reuse the CSP helper and the shared pieces (phases 1, 2)

### Both pages send the same Content-Security-Policy as before

1. Kiln: compare stage's whole header with the one stage sent before the merge, and
   with prod's.

   ```bash
   curl -s -D "$QA_DIR/kiln-stage.headers" -o "$QA_DIR/kiln-stage.html" -w 'stage %{http_code}\n' "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
   curl -s -D "$QA_DIR/kiln-prod.headers"  -o "$QA_DIR/kiln-prod.html"  -w 'prod %{http_code}\n'  "$PROD_URL/KilnOpsDropoffRecentEntriesViewer"
   python3 -I - "$QA_DIR" <<'EOF'
   import base64, hashlib, re, sys

   # What stage sent before the merge (07b9b79, read on 2026-10-17). This branch builds the same string.
   BEFORE = ("default-src 'none'; style-src 'sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8='; "
             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

   def read(where):
       head = open(f"{sys.argv[1]}/kiln-{where}.headers", encoding="utf-8").read()
       body = open(f"{sys.argv[1]}/kiln-{where}.html", "rb").read()
       policy = re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$", head).group(1)
       style = re.findall(rb"<style>(.*?)</style>", body, re.S)
       own_hash = "'sha256-" + base64.b64encode(hashlib.sha256(style[0]).digest()).decode() + "'"
       return policy, style, policy.replace(own_hash, "<its own hash>")

   same = lambda a, b: "same" if a == b else "DIFFERENT"
   stage, prod = read("stage"), read("prod")
   print("stage:", stage[0])
   print("stage vs before the merge:      ", same(stage[0], BEFORE))
   print("stage vs prod, whole header:    ", same(stage[0], prod[0]))
   print("stage vs prod, served <style>:  ", same(stage[1], prod[1]))
   print("stage vs prod, each hash masked:", same(stage[2], prod[2]))
   EOF
   ```

   **Expect:** `stage 200` and `prod 200`, then:

   ```text
   stage: default-src 'none'; style-src 'sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8='; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
   stage vs before the merge:       same
   stage vs prod, whole header:     DIFFERENT
   stage vs prod, served <style>:   DIFFERENT
   stage vs prod, each hash masked: same
   ```

   The second line is the check that counts: the whole header string is the one stage
   sent before this change. This branch builds the same string; to see it, run
   `PYTHONPATH=layers/common/python .venv/bin/python -c 'from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as k; print(k.RESPONSE_HEADERS["Content-Security-Policy"])'`.

   Prod's whole header differs, and that is not from this change. Story #138 (PR #150,
   07b9b79) is on `stage` but not yet on `main`. It moved the shared tokens into a block
   of their own in the kiln page's `:root`, which changed the text of the served
   `<style>` (not its tokens or rules), and so its hash. On 2026-10-17 prod sent
   `style-src 'sha256-zwmov6/DM5/2u9QG+pB5W5x0clfW7jxavUDA6lkQdA4='`. The
   `served <style>` line shows the two `<style>` blocks differ, and the
   `each hash masked` line that, with each header's own hash replaced, the rest is the
   same: the same 5 directives in the same order. If prod already has #138, every line
   says `same`, and that is a pass too. A fail is `DIFFERENT` on
   `stage vs before the merge` or on `each hash masked`.
2. Photo: compare stage's header with prod's after replacing the nonce.

   ```bash
   curl -s -D "$QA_DIR/photo-stage.headers" -o "$QA_DIR/photo-stage.html" -w 'stage %{http_code}\n' "$STAGE_API_URL/class-photo-upload"
   curl -s -D "$QA_DIR/photo-prod.headers"  -o "$QA_DIR/photo-prod.html"  -w 'prod %{http_code}\n'  "$PROD_URL/class-photo-upload"
   python3 -I - "$QA_DIR" <<'EOF'
   import json, re, sys

   def read(where):
       head = open(f"{sys.argv[1]}/photo-{where}.headers", encoding="utf-8").read()
       body = open(f"{sys.argv[1]}/photo-{where}.html", encoding="utf-8").read()
       policy = re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$", head).group(1)
       nonce = re.search(r"script-src 'nonce-([A-Za-z0-9_-]+)'", policy).group(1)
       host = json.loads(re.search(r'id="page-config">(.*?)</script>', body, re.S).group(1))["authDomain"]
       return policy.replace(nonce, "<n>"), host

   (stage, stage_host), (prod, prod_host) = read("stage"), read("prod")
   print("stage:", stage)
   print("prod: ", prod)
   print("nonce replaced, stage vs prod:", "same" if stage == prod else "DIFFERENT")
   print("sign-in host in each page config: stage", stage_host, "| prod", prod_host)
   EOF
   ```

   **Expect:** `stage 200` and `prod 200`, then two equal policies and `same`:

   ```text
   stage: default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>'; img-src blob:; connect-src 'self' https://login.mcp.asmbly.org; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
   prod:  default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>'; img-src blob:; connect-src 'self' https://login.mcp.asmbly.org; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
   nonce replaced, stage vs prod: same
   sign-in host in each page config: stage login.mcp.asmbly.org | prod login.mcp.asmbly.org
   ```

   The 8 directives, their order and every byte other than the nonce must match. The
   `connect-src` host is each stack's `STAFF_AUTH_DOMAIN`, the same as the page config's
   `authDomain`. Both stacks used `login.mcp.asmbly.org` on 2026-10-17. If that host
   differs between them, the policies may differ in that host only.

### The kiln hash and the photo nonces

3. Kiln: the hash in the header is the hash of the `<style>` the page served (one
   command).

   ```bash
   curl -s -D "$QA_DIR/kiln.headers" -o "$QA_DIR/kiln.html" "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer" && python3 -I -c 'import base64,hashlib,re,sys; p=re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$",open(sys.argv[1],encoding="utf-8").read()).group(1); d=dict(x.strip().split(" ",1) for x in p.split(";")); s=re.findall(rb"<style>(.*?)</style>",open(sys.argv[2],"rb").read(),re.S); h="sha256-"+base64.b64encode(hashlib.sha256(s[0]).digest()).decode(); print("style blocks:",len(s)); print("header style-src:",d["style-src"]); print("served <style>:  ",repr(h)); print("MATCH" if len(s)==1 and d["style-src"]==repr(h) else "MISMATCH")' "$QA_DIR/kiln.headers" "$QA_DIR/kiln.html"
   ```

   **Expect:**

   ```text
   style blocks: 1
   header style-src: 'sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8='
   served <style>:   'sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8='
   MATCH
   ```

   `MATCH` is what counts; the hash value is the one in step 1 while `page.html` and
   `brand.py` are as on 07b9b79. The kiln error page ("Could not retrieve the list of
   submissions.") uses the same shell and sends the same header; a person can't cause
   it on stage, and `test_hash_pages_allow_only_their_served_style` (step 12) checks it.
4. Photo: two requests get different nonces, and each header's nonce is the one on the
   page's `<style>` and `<script>` (one command).

   ```bash
   for i in 1 2; do curl -s -D "$QA_DIR/photo-$i.headers" -o "$QA_DIR/photo-$i.html" "$STAGE_API_URL/class-photo-upload"; python3 -I -c 'import re,sys; p=re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$",open(sys.argv[1],encoding="utf-8").read()).group(1); b=open(sys.argv[2],encoding="utf-8").read(); d=dict(x.strip().split(" ",1) for x in p.split(";")); n=re.fullmatch(r".nonce-([A-Za-z0-9_-]+).",d["script-src"]).group(1); print("nonce",n,"| style-src same:",d["style-src"]==d["script-src"],"| <style> has it:",("<style nonce=\""+n+"\">") in b,"| <script> has it:",("<script nonce=\""+n+"\">") in b)' "$QA_DIR/photo-$i.headers" "$QA_DIR/photo-$i.html"; done; echo "distinct nonces: $(grep -hoi "script-src 'nonce-[^']*'" "$QA_DIR"/photo-[12].headers | sort -u | wc -l | tr -d ' ')"
   ```

   **Expect:** two lines of the form
   `nonce <n> | style-src same: True | <style> has it: True | <script> has it: True`,
   each with a different 22-character `<n>`, then `distinct nonces: 2`.
5. Run the repository's own shared checks, `tests/page_csp.py`, on what stage served in
   steps 3 and 4. They also check that every `<style>` and every executable `<script>`
   carries the nonce, that the kiln page has no script, and that neither page has an
   inline `style=` or `on…=` attribute.

   ```bash
   .venv/bin/python - "$QA_DIR" <<'EOF'
   import re, sys
   from tests import page_csp

   def read(name):
       head = open(f"{sys.argv[1]}/{name}.headers", encoding="utf-8").read()
       body = open(f"{sys.argv[1]}/{name}.html", encoding="utf-8").read()
       return re.search(r"(?im)^content-security-policy:[ \t]*(.+?)[ \t]*\r?$", head).group(1), body

   print("kiln:", page_csp.style_hash_problems(*read("kiln")))
   for name in ("photo-1", "photo-2"):
       print(f"{name}:", page_csp.nonce_problems(*read(name)))
   EOF
   ```

   **Expect:** `kiln: []`, `photo-1: []` and `photo-2: []`. An empty list is a pass; a
   failure prints what is wrong.

### Visitors see no change

6. Open the kiln page on stage (`echo "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"`)
   and on prod in two windows. In responsive mode, set the width to **320**, compare,
   then set it to **1280** and compare.
   **Expect:** at both widths, the two pages look the same: the header band in the
   ceramics colour with its icon and title, the hint and the **Refresh** button, the
   table (or "No submissions found in the last 24 hours. Please try refreshing."), and
   the Asmbly logo in the footer. Only the list's rows differ, since stage's ClickUp list
   isn't prod's. The page is styled, which shows the browser accepted the `<style>`
   under the policy. At 320px nothing scrolls sideways. The browser console shows no
   Content-Security-Policy violation. The one message to expect is for the browser's own
   `/favicon.ico` request, shown as blocked or as a 403, which is older than this change.
7. Open the photo page on stage (`echo "$STAGE_API_URL/class-photo-upload"`) and on prod.
   Each sends you to the staff pool's sign-in. Sign in with a staff account on both.
   Compare at **320** and at **1280** wide. **Don't press Submit on prod**: there, it
   opens or updates a pull request on `asmbly-classes`.
   **Expect:** at both widths, the two pages look the same: the Asmbly Purple band with
   the logo, "Class photo upload" and **Sign out**, the pattern strip under it, and the
   **Class** list, **Choose a photo** and **Submit**. The **Class** list fills in, which
   needs the page's script (allowed by its nonce) and its fetch to its own API (allowed
   by `connect-src 'self'`). The one difference allowed is on stage: under the band, the
   banner "Stage: dry run. Submitting checks the photo and shows what would happen;
   nothing is opened on GitHub." Prod has no banner. The class names come from each
   stage's own data and may differ. At 320px nothing scrolls sideways, and the console
   shows no Content-Security-Policy violation.

### The deploy and the photo page's error pages

8. Both page functions run the new layer version and load `common.csp` without an
   error. Run this after steps 1 to 7, so both functions have started since the deploy.

   ```bash
   aws lambda list-layer-versions --layer-name common-layer-stage --region us-east-2 \
     --query 'max_by(LayerVersions, &Version).[LayerVersionArn,CreatedDate]' --output text
   for f in KilnDropoffRecentEntriesViewerFunction ClassPhotoUploadPageFunction; do
     echo "$f: $(aws lambda get-function-configuration --function-name "$f-stage" --region us-east-2 --query 'Layers[].Arn' --output text)"
     aws logs tail "/asmbly/lambda/$f-stage" --region us-east-2 --since 1h > "$QA_DIR/$f.log"
     echo "$f: $(grep -cE 'ImportModuleError|No module named|Traceback' "$QA_DIR/$f.log") error lines"
   done
   ```

   **Expect:** the newest `common-layer-stage` version was created by this merge's
   deploy (or a later one), and both functions list that same `...:layer:common-layer-stage:<version>`
   ARN (the kiln function lists the requests layer too). Each prints `0 error lines`. If
   more than an hour has passed since step 7, widen `--since`.
9. *(Optional: needs `lambda:InvokeFunction` on the stage function.)* The photo page's
   400 page, and the trailing-newline fix. Through the stage API a person can't send
   either case: the function checks the host and path in the request context, and API
   Gateway sets them. Invoke the stage function directly instead, with the tests' event
   and a host that isn't one, then with a host that ends in a line break. The page
   function reads nothing, calls nothing and changes nothing.

   ```bash
   for case in bad-host trailing-newline; do
     python3 -I -c 'import json, sys; e = json.load(open(sys.argv[1])); e["requestContext"]["domainName"] = {"bad-host": "evil.example/x", "trailing-newline": "facilities.asmbly.org\n"}[sys.argv[2]]; print(json.dumps(e))' \
       functions/classes/class_photo_upload_page/tests/fixtures/api_event_page.json "$case" > "$QA_DIR/photo-$case-event.json"
     aws lambda invoke --function-name ClassPhotoUploadPageFunction-stage --region us-east-2 \
       --payload "fileb://$QA_DIR/photo-$case-event.json" "$QA_DIR/photo-$case.json" > /dev/null
     python3 -I -c 'import json, sys; r = json.load(open(sys.argv[1])); print(sys.argv[2], r["statusCode"], "| page-config in body:", "page-config" in r["body"]); print("  CSP:", r["headers"]["Content-Security-Policy"])' "$QA_DIR/photo-$case.json" "$case"
   done
   ```

   **Expect:**

   ```text
   bad-host 400 | page-config in body: False
     CSP: default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
   trailing-newline 400 | page-config in body: False
     CSP: default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
   ```

   The CSP is the error pages' policy as before, now from `csp.strict_policy()`. The
   bad host answered 400 before this change too. The host with a trailing newline is the
   behavior fix: before the merge, stage answered it 200 with the page. The log group
   `/asmbly/lambda/ClassPhotoUploadPageFunction-stage` gets
   `Refused the class photo page for an unexpected host or path` for each, without the
   host or the path. The 500 page needs a bad `STAFF_AUTH_DOMAIN` or
   `CLASS_PHOTO_APP_CLIENT_ID`, which change only through the templates, so the tests
   cover it (steps 14 and 15).

### The "Adding a Public Page" guide

10. A reviewer reads `docs/CONTRIBUTING.md`, section
    [Adding a Public Page](../../docs/CONTRIBUTING.md#adding-a-public-page). It is
    listed in the file's contents, between "Adding a New Lambda Function" and "Coding
    Standards".
    **Expect:** the section says how to build a new page from the shared pieces, not by
    copying either page, and names:
    - **The CLAUDE.md steps:** start from "Adding a New Lambda Function", with a link to
      `CLAUDE.md`'s Rules; a caller check, with the class photo page's answer and issue
      #79; a log group `/asmbly/lambda/<FunctionName>-${Stage}` with a retention period;
      the function and log group in `GitHubDeployPolicystage` and
      `GitHubDeployPolicyprod`, with the **Risk** note that an admin redeploys that
      stack first.
    - **The shared tokens and logo:** `page.html` with one `<style>` whose first rule is
      `:root` holding `/* __BRAND_TOKENS__ */`, the optional `<!-- __ASMBLY_LOGO__ -->`,
      `brand.fill_brand(...)` from `layers/common/python/common/brand.py`, and
      `Layers: [!Ref CommonLayerARN]`.
    - **The CSP helper:** `layers/common/python/common/csp.py`, "never write it by
      hand", with `csp.hash_policy(...)` for a page with no script,
      `csp.new_nonce()` and `csp.nonce_policy(...)` for a page with a script, and
      `csp.strict_policy()` for an error page.
    - **The test helpers:** `tests/page_style.py`, `tests/page_csp.py`, `PUBLIC_PAGES`
      in `tests/test_page_csp.py` (and that `test_every_html_page_is_registered` fails
      until the page is in it), `PAGES` and `served_sheets()` in
      `tests/capture_page_pins.py`, and pinning the header in the page's own tests.
    - **Docs:** the function's README and its entry in `docs/README.md`.

    The links to `../CLAUDE.md#rules`, `../CLAUDE.md#what-this-repository-does` and
    `README.md#core-services` open those sections on GitHub. The "Coding Standards"
    section's page-tests bullet now points to `tests/page_csp.py` and this section. Both
    function READMEs say their policy is built by `common/csp.py`.

### Local steps a reviewer can run

11. The whole suite:

    ```bash
    .venv/bin/python -m pytest -q
    ```

    **Expect:** `1943 passed, 8 subtests passed` at 6e71ad3. More tests if `stage` has
    gained some since, but none failing.
12. The registry of public pages runs the shared checks on every page:

    ```bash
    .venv/bin/python -m pytest -q tests/test_page_csp.py -k "every_html_page_is_registered or hash_pages_allow or nonce_pages_put"
    ```

    **Expect:** `3 passed`: `test_every_html_page_is_registered`,
    `test_hash_pages_allow_only_their_served_style[kiln]` (its empty list, a list with a
    drop-off, and its error page) and
    `test_nonce_pages_put_a_fresh_nonce_on_style_and_script[photo]`.
13. No function writes a CSP by hand. The AST test reads every `.py` file under
    `functions/` outside `tests/` and fails on a string that reads like a policy, and
    checks that both pages import `csp` from `common`. Its self-test shows what it finds
    and what it skips.

    ```bash
    .venv/bin/python -m pytest -q "tests/test_page_csp.py::test_no_function_builds_a_csp_by_hand" "tests/test_page_csp.py::test_hand_built_csp_check_finds_a_policy_string"
    grep -rn "default-src\|frame-ancestors" functions --include=lambda_function.py || echo "nothing found"
    ```

    **Expect:** `2 passed`, then `nothing found`.

    To see both guards catch a new page that isn't registered and writes its own
    policy, add a throwaway one, run the two tests, and remove it:

    ```bash
    mkdir -p functions/qa_demo/new_page
    printf '<html><style>a{}</style></html>\n' > functions/qa_demo/new_page/page.html
    printf '%s\n' "HEADERS = {\"Content-Type\": \"text/html\", \"Content-Security-Policy\": \"default-src 'none'; base-uri 'none'\"}" > functions/qa_demo/new_page/lambda_function.py
    .venv/bin/python -m pytest -q tests/test_page_csp.py -k "every_html_page_is_registered or no_function_builds_a_csp_by_hand"
    rm -r functions/qa_demo
    git status --short -- functions
    ```

    **Expect:** `2 failed`, with `FAILED tests/test_page_csp.py::test_every_html_page_is_registered`
    and `FAILED tests/test_page_csp.py::test_no_function_builds_a_csp_by_hand`. Then
    `git status` prints nothing: the throwaway page is gone.
14. The header pins: each page's header as it was on `stage` 07b9b79.

    ```bash
    .venv/bin/python -m pytest -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py functions/ceramics/kiln_dropoff_recent_entries_viewer \
      -k "byte_for_byte_unchanged or error_page_csp_is_unchanged or different_nonces_on_header or csp_style_hash_matches or csp_is_no_looser or sets_csp_header"
    ```

    **Expect:** `6 passed`. For the photo page:
    `test_csp_header_is_byte_for_byte_unchanged` (the header for a fixed nonce, and the
    one served with its nonce replaced), `test_error_page_csp_is_unchanged` (the 400 and
    500 pages' headers) and
    `test_two_requests_get_different_nonces_on_header_style_and_script`. For the kiln
    page: `test_lambda_handler_sets_csp_header`,
    `test_csp_style_hash_matches_served_style` and `test_csp_is_no_looser_than_before`.
15. The trailing-newline regression tests. These can't be exercised through the stage
    API, because API Gateway sets `domainName` and `path` and `STAFF_AUTH_DOMAIN` comes
    from the template. Only a direct invoke of the function reaches them; optional
    step 9 does that for the host.

    ```bash
    .venv/bin/python -m pytest -q functions/classes/class_photo_upload_page/tests/test_lambda_function.py -k "trailing_newline or line_break"
    ```

    **Expect:** `5 passed`: `test_domain_or_path_with_a_trailing_newline_returns_400`
    for the domain and the path, and `test_auth_domain_with_a_line_break_returns_500`
    for `host.example\n`, `host.example\r\n` and `host.example\nx` (the logged plain
    500, not an exception from building the CSP).
16. The helper's own tests and the shared checks' tests:

    ```bash
    .venv/bin/python -m pytest -q layers/common/tests/test_csp.py tests/test_page_csp.py
    ```

    **Expect:** `64 passed`. Among them: the three policy shapes
    (`test_strict_policy_alone_is_the_error_page_policy`,
    `test_hash_policy_is_the_kiln_shape`, `test_nonce_policy_is_the_photo_shape`),
    `test_csp_imports_only_the_standard_library`,
    `test_importing_csp_loads_no_third_party_module`, and
    `test_page_csp_does_not_import_the_helper`.
17. No page body or look pin changed, and the capture script reproduces the pins. Run
    the first command on the branch, before it merges.

    ```bash
    git diff --stat origin/stage...HEAD -- 'functions/*/*/page.html' 'functions/*/*/tests/fixtures' layers/common/python/common/brand.py
    .venv/bin/python -m tests.capture_page_pins
    git status --short -- functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/fixtures functions/classes/class_photo_upload_page/tests/fixtures
    ```

    **Expect:** the `git diff` prints nothing. The script prints
    `kiln: 54 tokens, 39 rule lines` and `photo: 79 tokens, 105 rule lines`, and
    `git status` prints nothing. If `git status` lists a fixture, the step failed:
    report it, and restore the fixtures with `git checkout -- <those paths>`.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
