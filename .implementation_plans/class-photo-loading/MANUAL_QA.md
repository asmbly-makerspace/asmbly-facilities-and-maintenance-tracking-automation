# Manual QA: Class photo loading

Acceptance steps for `feature/class-photo-loading`, by story, so each check maps back to
#116, #117 and #118 (epic #114).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`. Stage is a dry run:
nothing is opened on GitHub. The prod steps at the end run after `/promote`.

> Automated checks already passed on the branch (integration gate): pytest 1701 passed
> (including 27 page-script scenarios run under node 24, which fail rather than skip in
> CI), cfn-lint clean apart from 4 W3005 warnings already on `stage`, sam validate pass,
> sam build pass. These steps cover what a person should see in the browser, in
> CloudWatch and in DynamoDB.

## Prerequisites

- **Admin action 1 done:** the deploy role `AsmblyFacilitiesMaintTrackingStack-cicd`
  redeployed from this branch's `template-cicd.yaml` before the merge (this time the
  orchestrator does it, with the owner's approval). Without it the stage deploy fails on
  the new table.
- The stage page:
  `https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage/class-photo-upload`.
  Sign-in goes through `login.mcp.asmbly.org` with a staff account.

  ```bash
  STAGE_API_URL="https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage"
  ```

- A desktop Chrome (or Edge) with DevTools, and a phone or DevTools' device toolbar.
- A 3:2 landscape JPEG to submit (any photo cropped 3:2; stage is a dry run).
- Read-only AWS access with `AWS_PROFILE=asmbly`, region `us-east-2`. Every AWS command
  below only reads. To follow the API log while you test:

  ```bash
  AWS_PROFILE=asmbly aws logs tail /asmbly/lambda/ClassPhotoUploadApiFunction-stage \
    --region us-east-2 --since 15m --follow
  ```

- Nobody else testing the stage page at the same time (the cache is one item per stage).

---

## #116: The class list loads from a cache in under 2 seconds (phase 1)

1. **Stage has no scheduled refresh.**

   ```bash
   AWS_PROFILE=asmbly aws events describe-rule \
     --name class-photo-class-list-refresh-stage --region us-east-2
   ```

   **Expect:** the command fails with `ResourceNotFoundException` (the rule exists only on
   prod, `Condition: IsProd`).
2. **The cache table exists and starts empty.**

   ```bash
   AWS_PROFILE=asmbly aws dynamodb get-item --region us-east-2 \
     --table-name ClassPhotoClassListCache-stage \
     --key '{"cache_key": {"S": "class-list"}}' --consistent-read
   ```

   **Expect:** no `Item` in the output (an empty answer) if nobody has opened the page since
   the deploy. If there is an item already, note its `refreshed_at`: someone visited first,
   and step 3 becomes a cache hit. To see a cache miss anyway, wait for step 9 (a manual
   refresh) or ask an admin to delete the item (`functions/classes/class_photo_upload_api/README.md`,
   "clear the cache"); don't delete it yourself unless you're the admin.
3. **First load: a cache miss reads Neon live.** Open the stage page in a fresh tab, sign
   in, and time how long the class list takes to fill (DevTools Network tab, the
   `classes` request).
   **Expect:** the list fills after several seconds (about 7 to 9 s measured before this
   change; Neon's share is logged). The API log shows, in order:
   - `Class list cache: empty`
   - `Neon read <N> events (<P> pages) in <ms> ms: <C> classes`: note `<ms>`, Neon's time;
   - `Class list from neon (age 0 s): <C> classes`.
   Under the list the page says `Class list from Neon at HH:MM.` (your local time).
4. **The DynamoDB item after the first load.** Run step 2's `get-item` again.
   **Expect:** one item with `cache_key` `class-list`, `version` `1`, `classes` (a JSON
   list of class names, no instructor names), `class_count` equal to `<C>` from step 3,
   `refreshed_at` the time of step 3 in UTC ending in `Z`, and `source` `live_read`.
   No event IDs, usernames or `sub`.
5. **Second load: a cache hit in under 2 seconds.** Reload the page (signed in already).
   **Expect:** the `classes` request finishes in under 2 s in the Network tab. The log says
   `Class list from cache (age <s> s): <C> classes` and has **no** `Neon read …` line for
   this request. The page shows the same `Class list from Neon at HH:MM.` time as step 3
   (the copy's time, not now).
6. **The route still checks its caller, including `?refresh=1`.**

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' "$STAGE_API_URL/class-photo-upload/classes"
   curl -s -o /dev/null -w '%{http_code}\n' "$STAGE_API_URL/class-photo-upload/classes?refresh=1"
   ```

   **Expect:** `401` twice (the staff Cognito authorizer answers before the function).
   No `Neon read` line in the log, and the item's `refreshed_at` doesn't change.
7. **A Neon failure (explain, not forced).** Stage can't be made to fail Neon without
   changing the Neon secret, which this QA must not do. How it would show, from the code
   (`class_list_service.py`, `lambda_function.py`) and its tests:
   - With a copy in the cache, a load that needs Neon (copy over 26 hours old) or a
     refresh logs `Couldn't read the class list from Neon after <ms> ms: <ErrorType>` and
     `Neon failed (<ErrorType>); serving the cached class list, <m> minutes old`, answers
     200 with the old copy and `stale: true`, and the page adds
     `Neon didn't answer the last refresh, so this list may be out of date.`
   - With no copy, the API answers 502 with `Couldn't load the class list. Try again in a
     minute.` and the page shows that message with **Try again** (step 12 shows the same
     controls with a blocked request).
   **Expect:** nothing to run; mark this step "explained" unless Neon happens to fail during
   testing, in which case check the lines above.

## #117: A clear busy state while classes load, and Try again (phase 3)

8. **The busy state on load.** In DevTools, Network tab, set throttling to "Slow 4G" (or
   a custom profile with 3 s latency), then reload the page.
   **Expect:** while `classes` is pending: a progress bar under the class list, the text
   `Loading classes…`, the class list disabled, and in the Elements panel
   `aria-busy="true"` on `#class-select`. If the wait passes 5 s, the text changes to
   `Still loading classes from Neon…`. When the list arrives the bar disappears,
   `aria-busy` is removed and the list is enabled. Set throttling back to "No throttling".
9. **Refresh class list: busy, then success.** Make sure the cache item is over a minute
   old (step 3 was more than 60 s ago). Press **Refresh class list**.
   **Expect:** while it runs: the progress bar, `Refreshing the class list from Neon…`,
   and the button stays focused but marked `aria-disabled="true"` (pressing it again does
   nothing). Then `Class list refreshed from Neon.` and a new `Class list from Neon at
   HH:MM.` time. The log shows a `Neon read …` line, `Class list refresh by sub <sub>:
   refreshed` (a `sub` UUID, no username or email) and `Class list from neon (age 0 s)`.
   Step 2's `get-item` now shows `source` `manual_refresh` and a new `refreshed_at`.
10. **Refresh within 60 s: "too soon".** Press **Refresh class list** again within a
    minute of step 9.
    **Expect:** `The class list was refreshed less than a minute ago, so this is that list.
    Try again in a minute.` The log shows `Class list refresh by sub <sub>: too_soon`
    and **no** `Neon read …` line; the item's `refreshed_at` is unchanged.
11. **Keyboard focus stays on Refresh.** Using only the keyboard (Tab to **Refresh class
    list**, press Enter or Space), wait over 60 s after step 10 and refresh again.
    **Expect:** focus stays on the button for the whole refresh (the focus ring doesn't
    jump to the top of the page; `document.activeElement` in the Console is
    `#class-refresh`). Screen reader (VoiceOver, Cmd+F5): the status text is read once
    when it changes; the progress bar is labelled "Loading classes".
12. **Try again after a failed load, and its focus.** In DevTools open the Network request
    blocking panel (Cmd+Shift+P, "Show Network request blocking"), add the pattern
    `*class-photo-upload/classes*`, enable it, and reload the page.
    **Expect:** `Couldn't reach the server. Check your connection and try again.` and a
    **Try again** button; no list. Tab to **Try again** and press Enter: the busy state
    shows again and focus stays on **Try again** (`aria-disabled="true"` while it runs)
    before failing again. Now disable the blocking pattern and press **Try again** with
    the keyboard once more.
    **Expect:** the list loads, **Try again** disappears, and focus moves to the class
    list (`document.activeElement` is `#class-select`), not to the page body.
13. **320 px width.** DevTools device toolbar, width 320 px, reload.
    **Expect:** no horizontal scroll; the class list, the progress bar, **Refresh class
    list**, **Try again** (repeat step 12's blocking to see it), the status texts and
    **Submit** fit the width and wrap, and every button is at least a thumb's height.
14. **No console or CSP errors.** With the Console open (filter: Errors and Warnings),
    repeat a load, a refresh and a submission (step 15).
    **Expect:** no errors, no `Refused to …` Content-Security-Policy violations, no
    requests to any host but the stage API and `login.mcp.asmbly.org`.

## #118: Submit checks against the cached list and shows its progress (phases 2, 3)

15. **Submit progress with elapsed time, and the dry-run result.** With the list loaded
    from a warm cache (step 5 within the last 26 hours), pick a class, choose the 3:2
    JPEG, and press **Submit** (by keyboard: Tab to it and press Enter).
    **Expect:** a progress bar and the steps `Preparing the photo…` → `Sending the
    photo…` → `Waiting for the server to check it and plan the pull request…`, with the
    seconds elapsed (`1 s`, `2 s`, …) beside them, counting up. While it runs, the class
    list and the photo picker are disabled, **Refresh class list** is
    `aria-disabled="true"`, and **Submit** keeps
    focus but is `aria-disabled="true"` (pressing again sends nothing; one `submit`
    request in the Network tab). Then the dry-run result: the exact file name, the files
    it would remove, and the pull request it would open; nothing appears on GitHub. The
    elapsed line disappears and focus is not lost to the page body.
16. **Submit used the cache, not Neon.** In the API log for step 15's request.
    **Expect:** `POST /class-photo-upload/submit from sub <sub> (dry run: True)`, then
    `Class list from cache (age <s> s): <C> classes` and **no** `Neon read …` line, then
    `Class photo submitted for class <name>`, `Dry run for class <name>: <action> on branch
    <branch>`, and `Time left after planning (dry run): <ms> ms`. Note `<ms>`; on stage it
    should be well over 8000 (the 8 s write minimum) now that Neon isn't read. The
    `Time left before the GitHub writes` line appears only on prod (step 22).
17. **A class that isn't in the list is still refused.**

    The page only sends names from its list, so send the request by hand. In DevTools,
    Network tab, right-click step 15's `submit` request → Copy → "Copy as cURL", paste it
    into a terminal (don't paste it anywhere else: it carries your token), change
    `"class_name":"<the class>"` in `--data-raw` to `"class_name":"Not A Real Class"`, and
    run it with `-s -w '\n%{http_code}\n'` added.
    **Expect:** `{"error": "Pick a class from the list."}` and `400`; the log shows
    `Class list from cache (age <s> s)` and `Answered 400: class_not_in_list`. The server
    never trusts the page's list.
18. **The "didn't confirm" message (a forced non-JSON answer).** In DevTools, Network tab,
    after one submission, right-click the `submit` request → "Override content", replace
    the body with `<html>Bad gateway</html>`, save, and submit again.
    **Expect:** on stage (a dry run) `The server didn't answer in time. This is a dry run,
    so nothing was opened on GitHub. Try again.` This is the same path an API Gateway
    502/504, a dropped connection after the upload, or the page's 35 s limit takes. On
    prod the same path shows `The server didn't confirm the result in time. A pull
    request may or may not have been opened on GitHub. Submitting the same class again is
    safe: it updates the same pull request instead of opening a second one.` (pinned by
    the page-script tests). Remove the override afterwards (Sources → Overrides, delete
    it).
19. **The server's two GitHub failure messages (explain).** They can't be caused on stage
    without breaking the GitHub App, so check they're in place:

    ```bash
    grep -n 'Nothing was changed on GitHub\|Submit the same class again' \
      functions/classes/class_photo_upload_api/lambda_function.py
    ```

    **Expect:** two messages. A failure before any write (the token, the read-only
    planning calls, too little time left, and every failure on a dry run) answers 502
    `Couldn't open the pull request. Nothing was changed on GitHub. Try again in a
    minute.` and logs `GitHub <operation> failed for class <name>: status <s> (before any
    write)`. A failure during the writes answers 502 `Couldn't finish the pull request on
    GitHub. Submit the same class again: it finishes the same pull request instead of
    opening a second one.` and logs `… (during the writes, after <ms> ms)`. The page shows
    the server's JSON message as it is. Covered by `tests/test_lambda_function.py` in the
    API.
20. **The 401 path for submit.**

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' -X POST \
      "$STAGE_API_URL/class-photo-upload/submit" -H 'Content-Type: application/json' -d '{}'
    ```

    **Expect:** `401`; no line in the API log (the authorizer refused it).

---

## After `/promote`: prod

Run after the prod deploy is green. Prod is not a dry run: step 23 opens a real pull
request on `asmbly-classes`.

21. **The prod rule exists, daily at 10:00 UTC, enabled.**

    ```bash
    AWS_PROFILE=asmbly aws events describe-rule \
      --name class-photo-class-list-refresh-prod --region us-east-2 \
      --query '{Schedule: ScheduleExpression, State: State}'
    AWS_PROFILE=asmbly aws events list-targets-by-rule \
      --rule class-photo-class-list-refresh-prod --region us-east-2 \
      --query 'Targets[].Arn'
    ```

    **Expect:** `cron(0 10 * * ? *)` and `ENABLED`; one target, the ARN of
    `ClassPhotoUploadApiFunction-prod`.
22. **The next day's scheduled refresh.** After 10:00 UTC the day after the deploy:

    ```bash
    AWS_PROFILE=asmbly aws logs filter-log-events --region us-east-2 \
      --log-group-name /asmbly/lambda/ClassPhotoUploadApiFunction-prod \
      --start-time $(( ($(date +%s) - 86400) * 1000 )) \
      --filter-pattern '"Scheduled class list refresh"' --query 'events[].message'
    AWS_PROFILE=asmbly aws dynamodb get-item --region us-east-2 \
      --table-name ClassPhotoClassListCache-prod \
      --key '{"cache_key": {"S": "class-list"}}' --consistent-read \
      --query 'Item.{source: source.S, refreshed_at: refreshed_at.S, count: class_count.N}'
    ```

    **Expect:** `Scheduled class list refresh: done` (not `kept the cached list`), and the
    item's `source` `schedule` with `refreshed_at` a little after 10:00 UTC that day.
23. **One real prod submission (Admin action 3).** On
    `https://facilities.asmbly.org/class-photo-upload`, load the page (the list arrives in
    under 2 s), submit a real class photo the owner wants, and check the progress steps
    end with `Waiting for the server to check it and open the pull request…` and the
    result links a pull request on `asmbly-classes`.
    **Expect:** in `/asmbly/lambda/ClassPhotoUploadApiFunction-prod` for that request,
    `Class list from cache (age <s> s)` with no `Neon read …` line, then `Time left
    before the GitHub writes: <ms> ms` and `GitHub writes took <ms> ms`. (If the log says
    `Class list from neon` instead, the figure includes Neon's time: submit again later
    from a warm cache for the measurement.)
24. **Record the figure on #114.** Comment on #114 with the `Time left before the GitHub
    writes` value from step 23 (and the `GitHub writes took` value), tick #114's last
    "Done when" box, and close #114.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
