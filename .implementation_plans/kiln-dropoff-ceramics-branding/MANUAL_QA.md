# Manual QA: Kiln drop-off page, ceramics branding

Acceptance steps for `feature/kiln-dropoff-ceramics-branding`, by story, so each check
maps back to #133 and #134 (epic #132).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`.

> Automated checks already passed on the branch: pytest 1771 passed (4 subtests passed),
> cfn-lint 0 errors (4 W3005 warnings in `template.yaml` on `FacilitiesCertificate` /
> `FacilitiesApiCustomDomain`, identical on `origin/stage`), sam validate pass, sam build
> pass (`page.html` packaged byte for byte). Nothing was skipped. These steps cover what a
> person should see in a browser, in the response headers and in CloudWatch.

The page is a plain public `GET` page (the ClickUp kiln drop-off form's redirect), not a
webhook, so every stage step opens it or fetches it directly. Nothing has to be sent by
hand to imitate a third party.

## Prerequisites

- **Admin actions: none.** The checkpoint lists none, and the plan says why: no named
  resource, secret, parameter, route or deploy-role change.
- The stage page address (stage has no custom domain):

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  PAGE_URL="$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
  echo "$PAGE_URL"
  ```

- Access to: read-only AWS CLI in us-east-2 (for the command above and the log group
  `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-stage`); desktop Chrome or
  Firefox with DevTools; a phone if you have one.
- A checkout of `stage` after the merge, with the virtual environment from `CLAUDE.md`
  (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt cfn-lint`),
  for the local steps. They call no network and no AWS. (On Windows, use Git Bash and
  `.venv/Scripts/python`.)
- **Real names on stage.** Stage reads the same ClickUp kiln drop-off list as prod, so the
  stage page shows real members' names. Do not create ClickUp tasks to test with (members
  at the kiln would see them). **Screenshots must not show member rows:** crop the table
  body out, or screenshot the stage empty state, the local pages (fake fixture names
  such as "Customer J") or the error page.
- The local pages, rendered from the function's test fixture plus two made-up rows (one
  with markup characters and a placeholder name, one with a 60-character name and no
  custom ID). Run from the repository root:

  ```bash
  git checkout stage && git pull
  QA_DIR=$(mktemp -d)
  QA_DIR="$QA_DIR" PYTHONPATH=.:layers/common/python .venv/bin/python - <<'EOF'
  import json, os, pathlib
  from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as lf

  out = pathlib.Path(os.environ["QA_DIR"])
  fixture = pathlib.Path("functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/fixtures/clickup_dropofftasks_response.json")
  tasks = json.loads(fixture.read_text(encoding="utf-8"))["tasks"]
  for i, task in enumerate(tasks):
      task["date_created"] = str(1704067200000 + i * 1000)
  tasks.append({"id": "qa-escape", "custom_id": "KO-<i>&\"'", "name": "<b>Not bold</b> & \"quoted\" __RELOAD_TEXT__", "date_created": "1704067300000"})
  tasks.append({"id": "qa-long-name", "custom_id": None, "name": "W" * 60, "date_created": "1704067400000"})
  tasks.sort(key=lambda t: int(t["date_created"]), reverse=True)
  (out / "list.html").write_text(lf.generate_html_page(tasks), encoding="utf-8")
  (out / "empty.html").write_text(lf.generate_html_page([]), encoding="utf-8")
  (out / "error.html").write_text(lf.generate_error_page(), encoding="utf-8")
  print("Pages written to", out)
  EOF
  ```

  Open them with `open "$QA_DIR/list.html"` (macOS) or your browser's File > Open. A local
  file has no response headers, so the Content-Security-Policy is checked on stage only.

---

## #133: Kiln drop-off page: ceramics colours and icon, Asmbly logo and type, readable on a phone (phase 1)

1. Fetch the stage page's headers.

   ```bash
   curl -sS -D - -o /dev/null "$PAGE_URL"
   ```

   Then print the policy the merged code should send, from your `stage` checkout:

   ```bash
   PYTHONPATH=.:layers/common/python .venv/bin/python -c "from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as lf; print(lf.RESPONSE_HEADERS['Content-Security-Policy'])"
   ```

   **Expect:** status `200` (a `502` means the function failed as it started; see step 3).
   Among the headers: `content-type: text/html; charset=utf-8`,
   `x-content-type-options: nosniff`, `cache-control: no-store`, and
   `content-security-policy: default-src 'none'; style-src 'sha256-<hash>'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
   character for character the same as the local command's output. The policy has no
   `'unsafe-inline'`, no `font-src`, no `img-src` and no `https://asmbly.org`.
2. Check the page source and size.

   ```bash
   curl -sS "$PAGE_URL" | grep -c -i -e '<script' -e ' style=' -e 'asmbly.org'
   curl -sS -o /dev/null -w '%{http_code} %{size_download} bytes\n' "$PAGE_URL"
   ```

   **Expect:** the first command prints `0` (no script, no `style` attribute, nothing from
   asmbly.org). The second prints `200` and a size under 61440 bytes (60 KB) while the list
   has 50 drop-offs or fewer; the page with no rows is about 13 KB.
3. Look at the log of the requests from steps 1 and 2.

   ```bash
   aws logs tail /asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-stage --since 15m --region us-east-2
   ```

   **Expect:** for each request, `Loaded ClickUp list ID ...`, `Fetching tasks created
   after ...` and `Retrieved N tasks from ClickUp`. No `ERROR` line, no traceback, and no
   `page.html must have exactly one <style> block`. No member names appear in the log.
4. Open `$PAGE_URL` in desktop Chrome or Firefox, window about 1280px wide, zoom 100%.
   **Expect:**
   - A full-width header band in the ceramics colour (pink-purple, #b34a9a) holding only
     the white ceramics pot icon and, beside it, the bold title "Recent Kiln Drop-Offs" in
     Asmbly White. The pot is cut out of a square, so the band colour shows through it.
   - On the off-white page below, in a centred column at most 800px wide: "Showing drop
     offs received in the last 24 hours", then "Please write your Name and your ID from
     the list below to a slip for each of your pieces.", then the table with the columns
     Drop-Off ID, Name and Time Submitted, newest first. The header row has a light
     ceramics tint; the IDs are bold monospace in a darker ceramics shade, each on one line.
   - "If your ID is not showing in the list, wait 1-2 minutes and refresh." above a
     Refresh button in the darker ceramics shade.
   - In the footer, the Asmbly logo (icon and "asmbly makerspace") in Asmbly Purple.
   - None of the old look: no white card with a shadow, no green Refresh button, no blue
     IDs, no grey table header, no pure white or black anywhere.
5. In the DevTools console of that tab (the console is not limited by the page's policy),
   read the computed colours and sizes:

   ```js
   const cs = (s) => { const e = document.querySelector(s); return e ? getComputedStyle(e) : {}; };
   console.table({
     band: cs('.brand-band').backgroundColor, title: cs('.brand-band h1').color,
     titleSize: cs('.brand-band h1').fontSize, titleWeight: cs('.brand-band h1').fontWeight,
     page: cs('body').backgroundColor, text: cs('body').color, bodySize: cs('body').fontSize,
     tableHead: cs('th').backgroundColor, id: cs('.task-id').color,
     idWeight: cs('.task-id').fontWeight, idSize: cs('.task-id').fontSize,
     refresh: cs('.reload-button').backgroundColor, logo: cs('.logo').color,
     logoHeight: document.querySelector('.logo').getBoundingClientRect().height,
   });
   ```

   **Expect:** band `rgb(179, 74, 154)`; title `rgb(242, 244, 239)`, `28px`, `700`; page
   `rgb(242, 244, 239)`; text `rgb(23, 29, 26)`; body `16px`; tableHead
   `rgb(229, 210, 222)`; id `rgb(148, 65, 128)`, `700`, `18px`; refresh
   `rgb(148, 65, 128)`; logo `rgb(41, 45, 106)`; logoHeight `56`. If the stage list is
   empty, the three `id` values are blank; read them on the local list page instead.
6. DevTools, Network tab open, reload the page.
   **Expect:** one request for the document (`KilnOpsDropoffRecentEntriesViewer`, status
   200) and at most the browser's own `/favicon.ico`. No font, image or script requests,
   nothing from asmbly.org. Select the document request: its Response Headers show the
   same `Content-Security-Policy` as step 1. In the Console: no Content-Security-Policy
   violation and no "Refused to apply inline style" message. The one expected message is
   `/favicon.ico` blocked by `default-src 'none'` (Firefox) or answered with a 403.
7. Click **Refresh**. Then press Tab until the button has focus and press Enter. With a
   mouse, hover over the button and over a table row.
   **Expect:** each time the same URL reloads (a new document request, status 200). With
   keyboard focus the button shows a 3px outline in the darker ceramics shade, a little
   outside the button. On hover the button turns darker and the row gets a light ceramics
   tint.
8. In DevTools' device toolbar (responsive mode), set the width to **320px**, then
   **768px**, then **1280px**. At each width run in the console:

   ```js
   [document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    document.querySelector('.reload-button').getBoundingClientRect()]
   ```

   **Expect:** `true` (no horizontal scroll) and a button `width` and `height` of at least
   44 at every width. The band spans the full width; all three columns are visible; IDs
   stay on one line (the time may wrap at its space at 320px). Turn the device toolbar off
   afterwards.
9. In a desktop window about 1280px wide, zoom to **200%**, then **400%**
   (Ctrl/Cmd and +), and run the step 8 snippet at each.
   **Expect:** `true` at both (the page scrolls only vertically), the three columns stay
   visible, the title stays in the band, and the pot icon and the Asmbly logo stay sharp,
   with no blur or pixelation. Reset the zoom afterwards.
10. Open `$PAGE_URL` on a phone, if you have one.
    **Expect:** the same page as step 4 in one column; the IDs are readable without
    zooming; the page doesn't move sideways; Refresh is easy to tap and reloads the list.
    A tapped row doesn't stay tinted.
11. Check the names screen readers hear. Chrome: Elements panel, select the `svg` in the
    band, then the Accessibility pane; Firefox: the Accessibility inspector. Repeat for the
    `svg` in the footer. (Or listen with VoiceOver or NVDA.)
    **Expect:** the band icon is an image named "Ceramics"; the footer logo is an image
    named "Asmbly Makerspace".
12. Open the local `$QA_DIR/list.html` (Prerequisites), first at full width, then at 320px
    in the device toolbar.
    **Expect:** the two made-up rows come first (the `qa-long-name` row, then the
    `KO-<i>&"'` row), then the fixture rows from "Customer J" down. The second row shows,
    as plain text and not bold, `<b>Not bold</b> & "quoted" __RELOAD_TEXT__`, and its ID
    reads `KO-<i>&"'` as text. The hint above Refresh reads "If your ID is not showing in
    the list, wait 1-2 minutes and refresh." exactly once, and the name cell still shows
    `__RELOAD_TEXT__`. The first row's ID is its task ID, `qa-long-name`, and its
    60 W's wrap inside the Name column at 320px; the step 8 snippet returns `true`. This
    page holds only fake names, so it can be screenshotted.
13. Open the local `$QA_DIR/empty.html`. If nobody has dropped anything off in the last
    24 hours, the stage page shows the same; check it there too.
    **Expect:** the same band, subtitle, instructions and table header as step 4, and one
    row reading "No submissions found in the last 24 hours. Please try refreshing.", then
    the hint, the Refresh button and the logo. No error box.

## #134: Kiln drop-off page: the error page carries the same ceramics styling (phase 1)

On stage the error page appears only when ClickUp, SSM or Secrets Manager fails, or a
setting is missing. It can't be caused without changing the function's configuration,
which is never done by hand, so these steps cause it locally. The tests cover each
failure path on the deployed code (`test_lambda_handler_error_pages_show_no_list`,
`test_csp_style_hash_matches_served_style`).

14. Run the handler from your `stage` checkout with its settings missing (it stops before
    any AWS or ClickUp call):

    ```bash
    env -u SECRET_NAME -u CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME PYTHONPATH=.:layers/common/python .venv/bin/python -c '
    import json
    from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as lf
    r = lf.lambda_handler({}, None)
    print(r["statusCode"]); print(json.dumps(r["headers"], indent=2))
    print("error message:", "Could not retrieve the list of submissions." in r["body"], "| list:", "<table" in r["body"], "| empty line:", "No submissions found" in r["body"])
    '
    ```

    **Expect:** the log line `SECRET_NAME environment variable not set`, then `500`, then
    the same four headers as step 1, with the `Content-Security-Policy` character for
    character the one stage served, then
    `error message: True | list: False | empty line: False`.
15. Open the local `$QA_DIR/error.html` at full width.
    **Expect:** the same header band, icon, title, Refresh button and footer logo as step 4.
    No subtitle, no instructions, no table, no "No submissions found" line, and no error
    details, exception text, list ID or token. A box with a light red tint and a 4px darker
    red edge on its left holds the heading "✕ An Error Occurred" (the ✕ in the edge's
    colour; iOS Safari before 17.4 and Firefox before 128 show no ✕, the edge and heading
    still do) and "Could not retrieve the list of submissions.". Below it, "Please wait 1-2
    minutes and refresh." and the Refresh button. In the console:

    ```js
    const b = getComputedStyle(document.querySelector('.error-box'));
    [b.backgroundColor, b.borderLeftColor, b.borderLeftWidth, b.color]
    ```

    returns `rgb(236, 208, 205)`, `rgb(173, 55, 59)`, `4px`, `rgb(23, 29, 26)`: none of
    the old `#fbeae5`, `#e74c3c` or `#c0392b`.
16. Same page at **320px** in the device toolbar, and run the step 8 snippet.
    **Expect:** `true` (no horizontal scroll); the message box and the Refresh button fit
    the width; the button is at least 44 by 44. This page shows no member rows, so it is
    the one to screenshot for the pull request or the release.
17. If the stage page itself ever shows the error page during these steps, read the log
    group from step 3.
    **Expect:** an `ERROR` line (`Failed to load kiln drop-offs` with a traceback,
    `ClickUp API token missing from secret`, or `<NAME> environment variable not set`),
    while the page shows only the message from step 15. The
    page and its headers look as in steps 14 to 16, and the console shows no CSP violation
    other than `/favicon.ico`.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
