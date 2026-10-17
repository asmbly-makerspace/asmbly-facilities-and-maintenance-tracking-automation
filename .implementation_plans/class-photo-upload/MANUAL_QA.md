# Manual QA: Class photo upload

Acceptance steps for `claude/inspiring-bell-o4i5t9` (the plan's feature branch), by
story, so each check maps back to #104, #105, #106, #107, #108, #109 (epic #73).

Run steps 1–29 on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`. Steps 30–37 are marked
**post-promote**: run them on prod after `stage` reaches `main` and the prod deploy is
green. Stage is a dry run: it shows the file name, the files it would remove and the
pull request it would open or update, and opens nothing on GitHub.

> Automated checks already passed on the branch: pytest 1499 passed, cfn-lint 4 W3005
> warnings (`template.yaml` custom-domain `DependsOn`, the same on `origin/stage`), sam
> validate pass, sam build pass. The page's JavaScript has no test in CI (plan Decision
> 19); in headless Chromium during phase 6 it matched the server's photo checks on 5,062
> photos and passed 54 end-to-end checks under its CSP. These steps cover what a person
> should see in a browser, on GitHub and in CloudWatch.

## Prerequisites

- The admin actions in [docs/Deploying.md, "One-Time Admin Setup: Class Photo
  Upload"](../../docs/Deploying.md#one-time-admin-setup-class-photo-upload) (plan README,
  "Admin actions" 1–5), done in this order:
  1. The Cognito app client `class-photo-upload` in the staff pool (AsmblyMCPs): public
     client, authorization code grant with PKCE, scope `openid`. Its callback URLs **and**
     sign-out URLs are both `https://facilities.asmbly.org/class-photo-upload` and
     `<stage FacilitiesApiUrl>/class-photo-upload`, exactly.
  2. The three SSM `String` parameters in us-east-2: `/config/cognito/staff/user-pool-id`,
     `/config/cognito/staff/auth-domain` (host only, no `https://`),
     `/config/cognito/staff/class-photo-app-client-id`.
  3. The GitHub App `Asmbly Class Photos Upload` (Contents RW, Pull requests RW, Metadata R,
     webhook off), installed on `asmbly-classes` only.
  4. The secret `github/class-photo-upload-app` (`app_id`, `installation_id`,
     `private_key`, all strings). Stage reads it too: it asks GitHub for a read-only
     token, so without the secret every stage submission answers 500.
  5. The deploy role `AsmblyFacilitiesMaintTrackingStack-cicd` redeployed from the branch
     before the merge (the `stage` deploy fails otherwise).
- The stage API address and the stage page:

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  echo "$STAGE_API_URL/class-photo-upload"
  ```

  The printed page address must be one of the app client's callback and sign-out URLs,
  character for character.
- Access to: an account in the staff sign-in pool; a desktop browser with DevTools;
  CloudWatch log groups `/asmbly/lambda/ClassPhotoUploadPageFunction-stage` and
  `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` (and the `-prod` ones for the
  post-promote steps); `https://github.com/asmbly-makerspace/asmbly-classes` (public;
  for steps 36–37, permission to close pull requests and delete branches there).
- Tools: `curl`, `jq`, ImageMagick (`magick`, or `convert` on ImageMagick 6), `exiftool`,
  and this repository's `.venv`.
- Test files. Run from the repository root:

  ```bash
  QA=~/class-photo-qa; mkdir -p "$QA"
  magick -size 1500x1000 xc:skyblue "$QA/good-3x2.jpg"          # acceptable
  magick -size 2000x1500 xc:skyblue "$QA/four-three.jpg"        # 4:3
  magick -size 1000x1500 xc:skyblue "$QA/portrait.jpg"          # 2:3 portrait
  magick -size 3000x2000 xc: +noise Random -quality 95 "$QA/big.jpg"   # ~12 MB, 3:2
  magick -size 1500x1000 xc:skyblue "$QA/real.png" && cp "$QA/real.png" "$QA/not-a-jpeg.jpg"
  cp "$QA/good-3x2.jpg" "$QA/gps.jpg"
  exiftool -overwrite_original -GPSLatitude=30.2672 -GPSLatitudeRef=N \
    -GPSLongitude=97.7431 -GPSLongitudeRef=W "$QA/gps.jpg"
  cp "$QA/good-3x2.jpg" "$QA/place-name.jpg"
  exiftool -overwrite_original -City=Austin -XMP-photoshop:City=Austin "$QA/place-name.jpg"
  # Header-only JPEGs from the test builder (the server reads only headers):
  .venv/bin/python - "$QA" <<'EOF'
  import sys
  from functions.classes.class_photo_upload_api.tests.jpeg_builder import make_jpeg
  qa = sys.argv[1]
  open(f"{qa}/gps-header-only.jpg", "wb").write(make_jpeg(1500, 1000, exif_gps=True))
  open(f"{qa}/bad-exif.jpg", "wb").write(make_jpeg(1500, 1000, orientation=1, byte_order="XX"))
  EOF
  ```

  A phone photo taken with location on, cropped to 3:2, is a good extra case for step 15.
- For the `curl` steps, your ID token: after signing in on the stage page (step 1), open
  DevTools → Application → Session Storage → the page's origin, and copy the value of
  `classPhoto.idToken` into `TOKEN='...'` in your shell. It expires after about an hour;
  don't paste it anywhere else.

The two API routes check their caller with the `StaffCognitoAuthorizer` plus the token's
`aud`/`token_use`; the page route `GET /class-photo-upload` has no authorizer by design
(plan Decision 7). No third-party webhooks are involved.

---

## #104: Sign in and pick the class from Neon (phases 1, 5, 6)

1. In a fresh private window, open `$STAGE_API_URL/class-photo-upload`.
   **Expect:** the title "Class photo upload" and "Signing in…" only, then the staff
   pool's hosted sign-in page. Sign in. **Expect:** back on the page; the address bar shows
   the page address without `?code=…&state=…`; a **Sign out** button; the banner "Stage:
   dry run. Submitting checks the photo and shows what would happen; nothing is opened on
   GitHub."; DevTools Console has no Content-Security-Policy violation and no error.
2. Open the **Class** list. **Expect:** "Loading classes…" briefly, then one entry per
   class name, sorted case-insensitively, each name as the site shows it (the Neon event
   name up to ` w/ `), covering classes whose event ended no more than 4 months ago or is
   still to come. A class you know ran more than 4 months ago and not since is absent.
3. The class list from the API:

   ```bash
   curl -s -H "Authorization: $TOKEN" "$STAGE_API_URL/class-photo-upload/classes" \
     | jq '{dry_run, count: (.classes | length), problems: [.classes[] | select(.problem) | .name],
            warnings: [.classes[] | select(.warning) | {name, warning}]}'
   ```

   **Expect:** `"dry_run": true` and the same count as the page's list. In
   `/asmbly/lambda/ClassPhotoUploadApiFunction-stage`: `GET /class-photo-upload/classes
   from sub <uuid> (dry run: True)` and `Answered <n> classes`, with the `sub` (a UUID),
   never your username or email.
4. If step 3 lists a `problems` entry (a name with `/`, `\` or a control character), choose
   that class on the page. **Expect:** the class is listed; choosing it shows `The class
   name "<name>" contains "/", which can't be in a file name. Rename the class in Neon
   first.` (or the character's `U+XXXX` code), and **Submit** stays disabled even with
   `good-3x2.jpg` chosen. If there is none, note "no such class in Neon" and go on; step
   20 covers the server side.
5. If step 3 lists a `warnings` entry, choose that class. **Expect:** under the list,
   "Another class, "<other>", matches the same photo on the class list. Both classes will
   show this photo there." (or the plural form naming several classes).
6. The page route answers without a token, by design:
   `curl -s -D - -o /dev/null "$STAGE_API_URL/class-photo-upload"`. **Expect:** `200`,
   `Content-Type: text/html; charset=utf-8`, `Cache-Control: no-store`, and a
   `Content-Security-Policy` that starts `default-src 'none'; script-src 'nonce-…'` and
   allows `connect-src 'self' https://<auth domain>`. In
   `/asmbly/lambda/ClassPhotoUploadPageFunction-stage`: `Served class photo page
   (dry_run=True)`, and no line anywhere carries a query string or `code=`.
7. Stale token: in DevTools → Session Storage, change one character in the middle of
   `classPhoto.idToken`, then choose `good-3x2.jpg` and click **Submit**. **Expect:** the
   API answers 401 and the page signs in again once (through the hosted sign-in, which may
   return at once if its session is still active); back on the page, choose the photo
   again. It must not loop between the page and the sign-in.
8. Click **Sign out**. **Expect:** straight back to the hosted sign-in form, with no
   "signed out" screen in between. That is expected: the app client's sign-out URL is the
   page itself, which starts a new sign-in at once.

## #105: Check the photo at once and say how to fix it (phases 2, 5, 6)

9. Choose a class, then drag `good-3x2.jpg` onto the photo box. **Expect:** a preview, the
   file's size, "This photo can be used.", **Submit** enabled, and directly above Submit:
   "When you submit, this photo becomes public on GitHub right away, before anyone reviews
   it. It stays visible in the pull request even if the pull request is never merged."
   Repeat with **Choose a photo** instead of dragging: same result.
10. Choose `not-a-jpeg.jpg` (a PNG renamed `.jpg`). **Expect:** "This file isn't a JPEG
    photo. Save or export it as a JPEG (.jpg) and try again." and Submit disabled.
11. Choose `four-three.jpg`. **Expect:** "This photo is 2000×1500, which is 4:3. Class
    photos must be 3:2, for example 1500×1000. Crop it and try again." and Submit
    disabled.
12. Choose `portrait.jpg`. **Expect:** "This photo is 1000×1500, which is 2:3 and not
    landscape. Class photos must be 3:2 landscape, for example 1500×1000. Crop it and try
    again."
13. Choose `big.jpg` (over 4 MB, that is over 4,194,304 bytes). **Expect:** "This photo is
    <n.n> MB. Class photos must be 4 MB or less. Export it at a smaller size and try
    again.", with the size rounded up to one decimal (about 11–12 MB for this file), and
    nothing sent (DevTools → Network shows no `submit` request).
14. Malformed EXIF is refused as unreadable (phase 2 hand-off): choose `bad-exif.jpg`.
    **Expect:** "This JPEG couldn't be read. Export it again as a JPEG and try again."
    The same happens to a real photo whose EXIF block is damaged even though a browser
    shows it, and to a file with more than 16 embedded JPEGs; re-exporting it fixes it.
    That is a known limit, not a bug.

## #106: Remove location data before the photo leaves the device (phases 2, 5, 6)

15. Choose `gps.jpg` (and, if you have one, the 3:2 phone photo with location).
    **Expect:** the preview, "Location data was removed from this photo.", and Submit
    enabled. A photo whose location the page can't remove shows "This photo has location
    data the page can't remove. Export it again as a JPEG without location and try
    again." instead.
16. Check that the bytes sent have no location: with DevTools → Network open, click
    **Submit**, select the `submit` request → Payload → view source, and save the JSON as
    `$QA/sent.json` (it contains only the class name and the photo). Then:

    ```bash
    jq -r .photo_base64 "$QA/sent.json" | base64 -d > "$QA/sent.jpg"
    exiftool -gps:all "$QA/sent.jpg"            # prints nothing
    .venv/bin/python -c "import sys; from functions.classes.class_photo_upload_api.photo_checks import read_jpeg_info; print(read_jpeg_info(open(sys.argv[1],'rb').read()).has_location)" "$QA/sent.jpg"
    exiftool -Orientation "$QA/sent.jpg"; exiftool -Orientation "$QA/gps.jpg"   # the same
    ```

    **Expect:** no GPS tags, `False`, the orientation unchanged, and the dry-run result
    on the page (the server accepted it). Delete `sent.json` afterwards.
17. Place names are not checked (plan Decision 25): choose `place-name.jpg` (City set, no
    GPS). **Expect:** accepted with "This photo can be used." and no "Location data was
    removed" line; `exiftool -City` on the sent bytes (as in step 16) still shows
    `Austin`. Expected behavior, not a bug.
18. The server refuses GPS from a caller that skips the page:

    ```bash
    CLASS='<a class name exactly as in the list>'
    base64 < "$QA/gps-header-only.jpg" | tr -d '\n' > "$QA/photo.b64"
    jq -n --arg class_name "$CLASS" --rawfile photo_base64 "$QA/photo.b64" \
      '{class_name: $class_name, photo_base64: $photo_base64}' > "$QA/body.json"
    curl -s -w '\n%{http_code}\n' -X POST "$STAGE_API_URL/class-photo-upload/submit" \
      -H "Authorization: $TOKEN" -H 'Content-Type: application/json' -d @"$QA/body.json"
    ```

    **Expect:** `{"error": "This photo still has location data. Use the upload page,
    which removes it."}` and `400`. API log: `Answered 400: photo:location`, no request
    body, photo or token in the log.
19. The same request without a token: drop the `-H "Authorization: $TOKEN"` line.
    **Expect:** `401` from API Gateway, and no new line in
    `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` (the function doesn't run). With a
    token whose characters you changed: `401` too. If you have an ID token from another
    app client of the staff pool: `403` with `{"error": "You're not allowed to use this
    page."}` and the log line `Rejected caller: audience`.

## #107: Submit opens a pull request on asmbly-classes with the right file name (phases 1, 4, 5, 6)

On stage these steps check the plan the dry run shows; the real pull request is step 30.

20. A class whose name has `/`, sent past the page:

    ```bash
    base64 < "$QA/good-3x2.jpg" | tr -d '\n' > "$QA/photo.b64"
    jq -n --arg class_name '<the class from step 4>' --rawfile photo_base64 "$QA/photo.b64" \
      '{class_name: $class_name, photo_base64: $photo_base64}' > "$QA/body.json"
    curl -s -w '\n%{http_code}\n' -X POST "$STAGE_API_URL/class-photo-upload/submit" \
      -H "Authorization: $TOKEN" -H 'Content-Type: application/json' -d @"$QA/body.json"
    ```

    **Expect:** `400` with `The class name "<name>" contains "/", which can't be in a file
    name. Rename the class in Neon first.` (log `Answered 400: file_name`). With a name
    that isn't in the list, for example `Not A Class/Test`: `400` with `Pick a class from
    the list.` (log `Answered 400: class_not_in_list`).
21. Pick a class whose photo already exists on `asmbly-classes` under a different name
    (browse `app/src/lib/images/` on `main`). Submit `good-3x2.jpg` on the page.
    **Expect:** "Dry run: nothing was opened", then "Would add" (or "Would replace", when
    the exact name already exists) `app/src/lib/images/<file>`, where `<file>` is the
    class name with each run of spaces and each `:` turned into `_`, plus `.jpg`
    (`Ceramics: Glazing Workshop` → `Ceramics__Glazing_Workshop.jpg`); "Files it would
    remove:" listing the other images in `app/src/lib/images/` that the class list matches
    for this class (names that equal the class name once both are lowercased, stripped of
    spaces, `:`, `-` and `_`, and the first `&` read as `and`, with one of the lowercase
    extensions `avif, gif, heif, jpeg, jpg, png, tiff, webp`), or "none".
22. In the same result: **Expect** "Title: Class photo: <class name>" and a description
    starting "Class photo for `<class name>`, submitted from the class photo upload
    page.", with **File** (added or replaced), **Removed**, **Requested by** `<your
    username>`, a collision warning when step 5 applies, and the closing lines "The photo
    was checked before upload: JPEG, 3:2 landscape, 4 MB or less, no location data." and
    "Merge to use it on classes.asmbly.org, or close this pull request to discard it."
    Class names with markup (`<`, `&`) show as text, not formatting.
23. API log for step 21: `POST /class-photo-upload/submit from sub <uuid> (dry run: True)`,
    `Class photo submitted for class <name>`, `Dry run for class <name>: would_open on
    branch class-photo/<slug>-<8 hex>`. The username appears nowhere in the log.
24. Class names starting with `.` (phase 1 and 5 hand-offs): if the list has one, submit
    it on stage. **Expect:** accepted, with a file name like `app/src/lib/images/.Foo.jpg`.
    Known limit: the site's image glob never loads a dotfile, so that photo would not show
    on classes.asmbly.org. Don't submit it on prod; raise it with the class's owner.

## #108: A second photo for the same class updates the open pull request (phases 4, 5, 6)

25. On stage, submit a photo for the class from step 21 again. **Expect:** the same dry
    run as step 21: "Would open a new pull request" (the first dry run opened nothing), the
    same file and the same `class-photo/…` branch in the log. If that class already has an
    open pull request on `asmbly-classes` from its `class-photo/` branch (after step 30),
    the result says "Would update open pull request #N" with a link instead.

The real update is post-promote step 33.

## #109: Stage is a dry run that shows what it would do (phases 4, 5, 6)

26. After steps 21 and 25, open
    `https://github.com/asmbly-makerspace/asmbly-classes/pulls` and
    `https://github.com/asmbly-makerspace/asmbly-classes/branches/all?query=class-photo`.
    **Expect:** no new pull request and no new `class-photo/` branch from the stage runs.
27. Every stage result so far began "Dry run: nothing was opened", and the banner from step
    1 is on the page. The step 18 `curl` with `good-3x2.jpg` instead of the GPS file
    answers `200` with `"dry_run": true`, `"action": "would_open"` (or `"would_update"`)
    and `"pull_request": null` for `would_open`.
28. In `/asmbly/lambda/ClassPhotoUploadApiFunction-stage`, every submit line says
    `(dry run: True)` and every success logs `Dry run for class …`; there is no line about
    writing a commit or a branch, and no `Not enough time left to write`.
29. Logs hold no personal data or secrets: search both stage log groups for your username,
    your email, `Bearer`, `eyJ` (the start of a token) and `photo_base64`. **Expect:** no
    matches.

---

## Post-promote: prod

Run these after `/promote` merges `stage` to `main` and the prod deploy is green. Prod
opens real pull requests on `asmbly-classes`; each photo becomes public there at once.
Use a photo the class's owner wants, and decide with them whether to merge.

30. **#104, custom domain path.** Open `https://facilities.asmbly.org/class-photo-upload`.
    **Expect:** sign-in as in step 1, but no dry-run banner. If you get a plain 400 page,
    `/asmbly/lambda/ClassPhotoUploadPageFunction-prod` shows `Refused the class photo page
    for an unexpected host or path`: `requestContext.path` on the custom domain isn't
    `/class-photo-upload` (unconfirmed until now, phase 6 hand-off). Stop and report it.
    Opening prod through its own execute-api address fails at sign-in (not a registered
    callback URL); that is by design.
31. **#107, the first real pull request.** Choose the class and its photo (ideally one
    taken with location on, so step 32 means something) and click **Submit**.
    **Expect:** "Opened pull request #N" with a link. On GitHub, pull request #N on
    `asmbly-classes`: opened by `asmbly-class-photos-upload[bot]`, from
    `class-photo/<slug>-<8 hex>` into `main`, title `Class photo: <class name>`, the
    description as in step 22 with your username under **Requested by**; **Files changed**
    adds or replaces `app/src/lib/images/<file>` and deletes exactly the files listed as
    **Removed**; the commit message is `Class photo: <class name>` / `Requested by
    <username>.` API log (`-prod`): `(dry run: False)` and no `Dry run for class` line.
32. **#106, no location in the committed file.** Download the committed image (Files
    changed → the image → "View file" → download, or):

    ```bash
    BRANCH='class-photo/<slug>-<hash8>'; FILE='<file>.jpg'
    curl -sL -o "$QA/committed.jpg" \
      "https://raw.githubusercontent.com/asmbly-makerspace/asmbly-classes/refs/heads/$BRANCH/app/src/lib/images/$FILE"
    exiftool -gps:all "$QA/committed.jpg"
    .venv/bin/python -c "import sys; from functions.classes.class_photo_upload_api.photo_checks import read_jpeg_info; print(read_jpeg_info(open(sys.argv[1],'rb').read()).has_location)" "$QA/committed.jpg"
    ```

    **Expect:** `exiftool` prints nothing and Python prints `False`. If either shows GPS,
    close the pull request at once (step 36) and report it.
33. **#108, a repeat submission.** Submit a second photo for the same class.
    **Expect:** "Updated pull request #N", the same number as step 31; no new pull request
    on GitHub. On #N: a second commit on the same branch (no force-push notice), the
    description rewritten for the latest submission (its **File**, **Removed** and
    **Requested by**), and **Files changed** still one image added or replaced plus the
    removals.
34. **#108 and #109 together.** On the stage page, submit a photo for the same class.
    **Expect:** "Would update open pull request #N" linking to the prod pull request, and
    #N unchanged on GitHub.
35. **#109.** Confirm the prod banner is absent and the prod results never say "Dry run".
36. **Undo.** On GitHub, close #N without merging and, if you like, delete its
    `class-photo/…` branch. **Expect:** `main` unchanged; the photo stays visible in the
    closed pull request's history (removing it entirely needs GitHub support to purge the
    branch's commits).
37. **After an undo (optional, opens one more pull request).** Submit for the same class
    again. **Expect:** "Opened pull request #M", a new number; #N stays closed and is not
    reopened; #M's branch starts from the current `main`. Close #M the same way unless the
    class's owner wants it.

If GitHub misbehaves (for example the key leaks), suspend or uninstall the App on
`asmbly-classes` to stop new pull requests at once (docs/Deploying.md).

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
