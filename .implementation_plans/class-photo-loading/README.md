---
plan: class-photo-loading
epic: 114
---

# Class photo loading: implementation plan

**Created:** 2026-10-16

## Overview

The class photo upload page (`https://facilities.asmbly.org/class-photo-upload`, epic #73,
restyled by #111) waits on Neon twice and shows almost nothing while it waits. Measured on
stage on 2026-10-17: `GET /class-photo-upload/classes` took 8.6 s (about 7.5 s of it
Neon) and a dry-run `POST /class-photo-upload/submit` 10.2 s (about 5.8 s Neon). Both call
`load_classes()` in `functions/classes/class_photo_upload_api/lambda_function.py`, which
runs a full `POST /v2/events/search` (4-month lookback, up to 8 pages of 200, 4 s a
page). On prod the submit's Neon read eats into the 25 s the function has for the GitHub
writes (it refuses to start writing with less than 8 s left, `WRITE_MIN_REMAINING_MS`).

This plan:

1. caches the class list per stage in a small DynamoDB table, refreshed in the background
   by an EventBridge schedule that invokes the existing API function, so the class list
   answers in well under 2 s and Neon's time is logged on every read (phase 1);
2. makes Submit validate against that cache instead of a second full Neon search, logs
   the time left before the GitHub writes, and makes the server's GitHub failure messages
   say whether anything was written (phase 2);
3. gives the page a real busy state, a "still loading" message, **Try again**, submission
   steps with elapsed time, disabled controls while submitting, and plain timeout messages
   that say whether a pull request may have been opened (phase 3).

The spec is #114's body (the owner's). Where this plan adds detail, it is under
**Decisions**.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #116 | Class photo upload: the class list loads from a cache in under 2 seconds | 1 |
| #117 | Class photo upload page: a clear busy state while classes load, and Try again | 3 |
| #118 | Class photo upload: Submit checks against the cached list and shows its progress | 2, 3 |

The pull request that lands phase 1 says `Closes #116`; phase 2's says `Refs #118`;
phase 3's says `Closes #117`, `Closes #118` and, once every box in #114's "Done when" is
ticked (the prod measurement is the last), `Closes #114`. Inside `/offshore` all phases
land in one pull request, which says `Closes #116`, `Closes #117`, `Closes #118` and
`Refs #114` (the prod measurement in #114's "Done when" happens after the prod deploy;
see Admin actions 3).

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Class-list cache, scheduled refresh and Neon timing](phase-1-class-list-cache.md) | lambda, infra, docs | L | [ ] Pending |
| 2 | [Submit against the cache, time left and what was written](phase-2-submit-against-cache.md) | lambda, docs | M | [ ] Pending |
| 3 | [Page busy state, progress, retry and timeout messages](phase-3-page-loading-and-progress.md) | lambda, docs | L | [ ] Pending |

## Dependencies

**Outside this plan**

- The `class-photo-upload` plan (epic #73) and the `photo-upload-branding` plan (epic
  #111): complete and on `stage` (merge `a1479e6`, pull request #115). Phase 3 builds on
  #111's design tokens and its token tests, which must keep passing without wider
  allowlists.
- Admin action 1 (deploy-role redeploy) before the plan's pull request reaches `stage`.
- `node` on the test machine for phase 3's page-script tests: present on GitHub's
  `ubuntu-latest` runners (preinstalled) and on the maintainer's Mac (v24). No npm
  package is added (Decision 12).

**Between phases** (direct predecessors)

| Phase | depends_on | Why |
| --- | --- | --- |
| 1 | — | |
| 2 | 1 | Submit reads the list through phase 1's `class_cache.get_class_list` |
| 3 | 1 | The page shows phase 1's `refreshed_at` and `stale` fields from `/classes` |

## Parallelism

| Pair | Verdict | Deciding paths |
| --- | --- | --- |
| 2 and 3 | Parallel-safe | No shared path: phase 2 changes `functions/classes/class_photo_upload_api/` (code, tests, README); phase 3 changes `functions/classes/class_photo_upload_page/` (page, tests, README). Neither touches `docs/README.md`, a template or `template-cicd.yaml`. |

Phase 1 is a predecessor of both. Inside `/offshore` the phases run in order 1, 2, 3.

## Admin actions

1. **Before the plan's pull request reaches `stage` (the stage deploy fails otherwise):**
   redeploy the deploy role, `AsmblyFacilitiesMaintTrackingStack-cicd`
   (`docs/Deploying.md`, "CI/CD Infrastructure (The Deployer Role)"). Phase 1 adds to
   both `GitHubDeployPolicystage` and `GitHubDeployPolicyprod`: the DynamoDB table
   `ClassPhotoClassListCache-{stage,prod}` and the EventBridge rule
   `class-photo-class-list-refresh-{stage,prod}` (with tagging on that rule only).
2. **After the stage deploy (nothing to configure):** the cache is empty until the first
   scheduled refresh (within 60 minutes on stage, 15 on prod) or the first visit, which
   reads Neon live and fills it. To check: open the stage page twice; the second load is
   under 2 s and the log `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` says
   `Class list from cache`.
3. **After the prod deploy, the owner or an admin:** make one real submission on prod and
   record, on #114, the "Time left before the GitHub writes" figure from
   `/asmbly/lambda/ClassPhotoUploadApiFunction-prod` (#114 "Done when", #118 criterion 3).
   Then close #114.

No secret, SSM parameter, app client, webhook or GitHub App setting changes.

## Related work

- **Plans `class-photo-upload` (#73) and `photo-upload-branding` (#111)**, both complete:
  built and restyled the page and API this plan changes. #111's README hands loading,
  progress and retry to #114 (its Decisions 2 and 10) and froze the `<script>`, which
  phase 3 now changes.
- **#95** (shared helpers' exception text): this plan doesn't change
  `layers/common/python/common/neoncrm.py` (Decision 8), so no overlap.
- **#92** (scope the SAM-generated roles to their own log groups): phase 1 adds a
  statement to `ClassPhotoUploadApiFunction`'s generated role; #92 can scope that role
  later without conflict.
- **#79** (check who calls each public route): no new route; the scheduled refresh is not
  reachable over HTTP (Security).
- **Pull request #68** (lint step, open, from a fork) changes
  `.github/workflows/python-tests.yml`, `requirements-dev.txt`, `template.yaml` and
  `docs/Deploying.md`. This plan changes none of those (phase 3 runs `node` from pytest
  without a workflow change, Decision 12).

## Out of scope

- A "refresh now" button, or a per-submit Neon lookup for a class created since the last
  refresh (#114 epic, "Out of scope"). A new class appears within 20 minutes on prod.
- Changing the 4-month rule, the class-name and file-name rules, the photo checks, the
  pull request flow, the dry run or sign-in.
- Speeding up or retrying GitHub's calls; the function's timeout, memory or concurrency.
- Parallel Neon page reads or a different page size (Decision 8).
- Changing `layers/common/python/common/neoncrm.py`.
- A CloudWatch alarm on failed refreshes (the logs carry a warning; Decision 6).
- Restyling the 400/500 error pages, a dark theme, PP Gosha (#111's decisions stand).

## Security

- **Who can call.** No new route. `GET /class-photo-upload/classes` and
  `POST /class-photo-upload/submit` keep the staff Cognito authorizer and the handler's
  `aud`/`token_use` check. The scheduled refresh is recognised before that check only for
  an event whose top level has `source: aws.events` and `detail-type: Scheduled Event`
  and no `httpMethod` or `requestContext`. API Gateway's proxy integration always sends
  `httpMethod` and `requestContext` and puts the caller's request in `body`, so an HTTP
  caller can't produce that shape. Only the rule may invoke the function for it
  (`AWS::Lambda::Permission`, principal `events.amazonaws.com`, `SourceArn` the rule's
  ARN). The refresh reads Neon (read-only) and writes one cache item; it never reads the
  GitHub App secret or calls GitHub. A test proves an HTTP event with the scheduled keys
  added still goes through the claims check.
- **IAM.** The function gets `dynamodb:GetItem` and `dynamodb:PutItem` on its own table's
  ARN only (not `DynamoDBCrudPolicy`, which adds Scan, Query, Delete and Update). The
  deploy role gets the table and the rule by exact name in both policies; the rule's
  tagging actions sit in their own statement on that rule's ARN. No wildcard, no new
  trust subject.
- **Data in the cache.** One item: class names (the part of each event name before
  " w/ ", so no instructor names), the time they were read, a count and a schema version.
  No event IDs, no personal data. Class names are already public on classes.asmbly.org.
- **Server-side validation is unchanged in strength.** Submit still refuses a class that
  isn't in the server's list (now the cached list, at most 3 hours old before a live read
  is tried) and a name that can't be a file name. The page's list is never trusted.
- **The page.** The Content-Security-Policy is unchanged (`test_csp_header` is not
  edited). No inline handlers, no `style=`, no `innerHTML`, no outside host; the busy
  indicator is a native `<progress>` element (no CSS animation). Messages are set with
  `textContent`.
- **Logs.** Neon time, page and class counts, cache age and the time left before the
  GitHub writes. Never a token, the `Authorization` header, a request body, a username or
  an instructor name.

## Decisions

Made without asking, inside `/offshore` (2026-10-16).

1. **#114 is the epic.** It is the owner's bug with a detailed spec and no sub-issues; it
   was labeled `epic` (keeping `bug`) and given stories #116, #117 and #118. Its body was
   kept word for word, with `## Stories`, `## Decided`, `## Out of scope` and
   `## Open questions` appended. Alternative: a new epic with #114 as a story, which would
   duplicate the owner's text.
2. **Cache design: a stage-named DynamoDB item, refreshed by a stage-named EventBridge
   schedule that invokes the existing API function; a request reads the cache and falls
   back to Neon only on a miss or an entry over 3 hours old; Neon failing while a copy
   exists serves the copy, marked stale.** Weighed against:
   - *Warm-container TTL* (no new resources): the page is used now and then, so most
     visits land on a cold container and still pay 8.6 s; `/classes` and `/submit` can
     land on different containers (up to 3 run at once), so Submit isn't guaranteed to hit
     it either. Fails "Submit no longer waits on a full Neon search".
   - *Single-event lookup on submit*: `submission.plan_submission` needs the whole list for
     the shared-photo warning (`fuzzy_collisions`), so this would drop a warning the pull
     request carries, and it does nothing for the class list.
   - *Stale-while-revalidate by async self-invoke* (no rule, but `lambda:InvokeFunction`
     on itself): the first visit after a quiet week serves a week-old list, and a new class
     appears only after someone has loaded the page once. A schedule bounds the age.
   - *SSM parameter*: the list (84 names today, JSON) is close to the 4 KB standard-tier
     limit; advanced tier costs money and the function would need `ssm:PutParameter`.
   - *S3 object*: a bucket is a heavier resource (public-access block, policy, lifecycle)
     for one small object.
   DynamoDB is one on-demand table with one item (pennies a month), with precedents in this
   repository for both the table (`SlackReorderStateTable-${Stage}`) and the rule
   (`pm-reminder-bot-schedule-${Stage}`). It adds two named resources, so the deploy role
   must be redeployed first (Admin actions 1). Smallest design that meets every "Done
   when".
3. **The refresh runs in the existing API function**, not a new function: no new function,
   log group or role, and the Neon read code is the same one the routes use. Alternative:
   a separate refresh function, which adds a function, a log group and two more deploy-role
   names.
4. **Schedule: every 15 minutes on prod, every 60 minutes on other stages**
   (`!If [IsProd, ...]` inside `templates/classes.yaml`, no new root parameter). Every
   stack reads the same prod Neon account (`prod/neon_token`), so stage and any dev stack
   refresh less often. About 2 Neon pages per refresh: about 190 requests a day from prod
   and 50 from stage. A new class shows within about 20 minutes on prod, 75 on stage.
5. **Maximum age 3 hours** (`MAX_AGE_SECONDS = 10800`), three missed stage refreshes or
   twelve on prod. Older: the request tries a live read (and writes it); if Neon fails, it
   serves the old copy with `stale: true`, which the page shows as "may be out of date".
   Well under a day, so the 4-month window (which moves with the date) is never more than
   3 hours behind before a live read is tried.
6. **A failed refresh logs a warning (with the cached copy's age, or "no cached list") and
   returns normally**, so Lambda doesn't retry the async invoke and add Neon load during an
   outage. A refresh that times out (25 s) is retried by Lambda up to twice, which is
   bounded. No alarm in this plan (Out of scope).
7. **Cache reads and writes fail soft.** A DynamoDB error on read is a miss (live read);
   on write, a warning (the live list is still answered). DynamoDB calls use a 2 s connect
   and read timeout with 2 attempts, so a DynamoDB problem can't eat the request's budget.
8. **No change to the Neon search or to `common/neoncrm.py`.** The search already asks for
   only `Event ID` and `Event Name` with one date filter; the page size stays 200 (the
   largest this code has used against Neon; not changed without a measurement). Phase 1's
   log line records the time, the events and the pages (events ÷ 200, rounded up) of every
   read, so the next measurement needs no REPORT arithmetic. Parallel page reads would
   need a helper change (overlapping #95) and Neon's rate limits aren't documented here;
   with the cache, the search runs off the request path.
9. **The `/classes` answer gains `refreshed_at` (ISO 8601, UTC, `Z`) and `stale`
   (boolean)**; the page shows "Class list from Neon at HH:MM." and, when `stale`, that it
   may be out of date. Existing fields are unchanged.
10. **GitHub failure messages say whether anything was written** (phase 2). Two messages
    replace `GITHUB_ERROR`: one for failures before any write (the installation token, the
    read-only planning calls, too little time left, and every failure on a dry run): "Couldn't
    open the pull request. Nothing was changed on GitHub. Try again in a minute."; and one
    for a failure during the writes: "Couldn't finish the pull request on GitHub. Submit
    the same class again: it finishes the same pull request instead of opening a second
    one." The old text is pinned only by the API's own tests, which phase 2 updates; the
    page never pinned it. Reason: #114 "a timeout message says whether a pull request was
    opened".
11. **Progress names only steps the page can see.** The page sends the submission with
    `XMLHttpRequest` (same origin, same headers, `connect-src 'self'` unchanged) so that
    `upload.onload` tells it when the photo has been sent: "Preparing the photo…" →
    "Sending the photo…" → "Waiting for the server to check it and open the pull request…"
    (on a dry run: "…check it and plan the pull request…"), with the seconds elapsed beside
    it. The server's own steps aren't guessed at. Alternative: `fetch`, which can't tell
    sending from waiting, or timed fake steps, which would mislead.
12. **The page's script gets automated tests, run by pytest through `node`** (no npm
    package, no workflow change). A harness (`tests/page_script_harness.mjs`) runs the
    page's own `<script>` in `node:vm` with a small fake DOM, fake timers and scripted
    answers, one scenario per test. pytest skips the tests when `node` is missing on a
    developer's machine and fails them when `CI` is set, so CI can't pass by skipping.
    Alternative: keep #73's Decision 19 (no JavaScript tests) and rely on reading and
    manual QA, which wouldn't meet "tests cover … the page's loading and retry states".
    Alternative: `actions/setup-node` in the workflow, which overlaps open pull request #68.
13. **The busy indicator is a native, indeterminate `<progress>`** coloured with
    `accent-color` from a token, plus `aria-busy` on the control and the existing
    `role="status"` live regions. No CSS animation: an animation needs time units and
    keywords (`s`, `infinite`, `linear`) that the token tests don't allow, and widening
    those allowlists is ruled out by the owner. The browser's own indeterminate animation
    follows the device's reduced-motion setting where the platform supports it.
14. **Elapsed seconds are not announced.** They sit in an element with `aria-hidden="true"`
    beside the step text; only step changes (and the "still loading" change) go to the live
    regions, so a screen reader hears each once.
15. **Timeouts on the page:** the page gives up on `/classes` and `/submit` after 35 s
    (API Gateway answers 504 at 29 s; 35 s covers a stalled connection). "Still loading
    classes from Neon…" appears after 5 s.
16. **Unconfirmed submission message** (502, 504 or another non-JSON answer, a dropped
    connection, or the page's own timeout, after the request was sent): on prod, "The
    server didn't confirm the result in time. A pull request may or may not have been
    opened on GitHub. Submitting the same class again is safe: it updates the same pull
    request instead of opening a second one."; on a dry run, "The server didn't answer in
    time. This is a dry run, so nothing was opened on GitHub. Try again." The page's
    existing messages stay word for word, and `GENERIC_ERROR` stays in the page (pinned by
    `test_page_messages_match_server_messages`) for other answers without a message.
17. **Focus.** Pressing **Try again** keeps focus on it (it is disabled, not hidden, while
    loading); when the list arrives it is hidden and focus moves to the class list, so
    focus is never lost. On a first load focus isn't moved.
18. **Phase 2 and 3 run in order inside `/offshore`** although they are parallel-safe, so
    the page's tests see phase 2's server messages when they are written.
