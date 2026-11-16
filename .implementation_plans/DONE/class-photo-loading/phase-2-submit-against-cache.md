---
phase_id: 2
title: Submit against the cache, time left and what was written
epic: 114
implements: [118]
depends_on: [1]
domain: [lambda, docs]
estimated_size: M
---

# Phase 2: Submit against the cache, time left and what was written

> **Status:** [x] Complete — 2026-10-16 on branch feature/class-photo-loading

## Required reading

- This plan's README (Decisions 2, 5, 10; Security, "Server-side validation").
- #118's acceptance criteria 1, 2, 3 and 6 (this phase delivers the server's part; phase 3
  the page's).
- Phase 1's hand-off: `class_list_service()` and `ClassListService.for_request()`,
  `ClassListResult`, `service.age_seconds(result)`, `read_classes_from_neon()`, the
  `fake_cache` fixture (`InMemoryClassListCache`), and the README's **Design** (the
  handler uses the service, never the cache's implementation). The phase 1 prep
  amendments (owner Decisions 19–22) renamed the hand-off; this document was updated to
  match.
- `functions/classes/class_photo_upload_api/lambda_function.py`: `handle_submit()`,
  `remaining_ms()`, `WRITE_MIN_REMAINING_MS`, the `Refusal` reasons.
- `functions/classes/class_photo_upload_api/submission.py`: `plan_submission(repo, config,
  class_name, all_classes, username)` (read calls only; uses `all_classes` for the
  shared-photo warning) and `apply_submission(...)` (the writes: blob, tree, commit, ref,
  pull request).
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`:
  `test_submit_*`, especially `test_submit_github_error_502_without_details` and
  `test_submit_with_too_little_time_left_writes_nothing`.

## Goal

`POST /class-photo-upload/submit` checks the class against the cached list from phase 1,
so with a warm cache it never waits on Neon (and works while Neon is down). It still
refuses a class that isn't in the server's list, or whose name can't be a file name. The
log records how much of the function's time was left before the GitHub writes (and, on a
dry run, after planning). A GitHub failure answers one of two messages, saying whether
anything was changed on GitHub.

## Files to create

None.

## Files to modify

- `functions/classes/class_photo_upload_api/lambda_function.py`: `handle_submit()` reads
  the cached list; the two GitHub messages replace `GITHUB_ERROR`; the time-left log;
  `load_classes()` removed.
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`: new and updated
  submit tests.
- `functions/classes/class_photo_upload_api/README.md`: "How It Works" (step 3), the
  "Responses" table, "Limits" ("Time").

## Implementation details

Prep (2026-10-16, inside `/offshore`) amended this section: the service is injected into
`handle_submit`; one shared class-list log helper; `class_list` instead of a reused
`result`; two GitHub `try` blocks instead of a `writing` flag; the elapsed time on a
write failure; reuse of `cached_copy` in tests; more README rows. Marked "prep amendment"
below.

### lambda

**Messages** (module constants; `GITHUB_ERROR` is removed, README Decision 10):

```python
GITHUB_NOTHING_CHANGED_ERROR = "Couldn't open the pull request. Nothing was changed on GitHub. Try again in a minute."
GITHUB_UNFINISHED_ERROR = (
    "Couldn't finish the pull request on GitHub. Submit the same class again: "
    "it finishes the same pull request instead of opening a second one."
)
```

**`handle_submit(event, context, username, dry_run, service: ClassListService)`**, in
today's order (parse, decode the photo, class, GitHub). The service is injected the way
`handle_classes` gets it: `lambda_handler` passes `class_list_service()` (prep amendment:
one wiring style, the composition root alone builds the service).

1. `parse_submission` and `decode_photo` unchanged (a bad photo still never reaches the
   cache, Neon or GitHub).
2. The class list, logged by one helper that `handle_classes` also uses (prep amendment:
   the three-line log call isn't duplicated):

   ```python
   def log_class_list(service: ClassListService, class_list: ClassListResult) -> None:
       logger.info("Class list from %s (age %d s): %d classes",
                   class_list.served_from, service.age_seconds(class_list), len(class_list.names))

   class_list = service.for_request()
   log_class_list(service, class_list)
   classes = class_list.names
   ```

   The variable is `class_list`, not `result` (prep amendment: `result` is the
   `SubmissionResult` later in the same function).

   Same rule as `/classes`: a copy under 26 hours old is used without Neon; a miss or an
   older copy reads Neon live (and writes the cache); Neon failing with a copy uses the
   copy; no copy and Neon failing → `Refusal(502, NEON_ERROR, …)` as today. A class added
   in Neon since the last refresh is refused ("Pick a class from the list.") until someone
   presses **Refresh class list** (owner Decision 21), which rewrites the same cache.
3. `class_name not in classes` → `Refusal(400, NOT_IN_LIST_ERROR, "class_not_in_list")`;
   then `file_name_problem` → `Refusal(400, problem, "file_name")`. Unchanged, now against
   the cached list. `plan_submission` gets the same `classes` for its shared-photo
   warning.
4. `load_github_settings()` unchanged.
5. GitHub, in two `try` blocks, one before the writes and one around them (prep
   amendment: no mutable `writing` flag; which block failed says whether anything was
   written). The shape, not the exact code:

   ```python
   try:
       token = github_app.installation_token(...)          # unchanged arguments
       repo = github_app.GitHubRepo(...)
       plan = submission.plan_submission(repo, config, class_name, classes, username)
   except GitHubError as e:
       logger.error("GitHub %s failed for class %s: status %s (before any write)", e.operation, class_name, e.status)
       raise Refusal(502, GITHUB_NOTHING_CHANGED_ERROR, "github_read") from None
   left = remaining_ms(context)
   if dry_run:
       result = submission.dry_run_result(plan)             # pure: no GitHub call
       logger.info("Dry run for class %s: %s on branch %s", class_name, result.action, plan.branch)
       if left is not None:
           logger.info("Time left after planning (dry run): %d ms", left)
       return _response(200, submission_payload(result, dry_run))
   if left is not None and left < WRITE_MIN_REMAINING_MS:
       logger.error("Not enough time left to write: %d ms", left)
       raise Refusal(502, GITHUB_NOTHING_CHANGED_ERROR, "time")
   if left is not None:
       logger.info("Time left before the GitHub writes: %d ms", left)
   started = time.monotonic()
   try:
       result = submission.apply_submission(...)            # unchanged arguments
   except submission.SubmissionConflict:
       ...                                                  # unchanged: 409 CONFLICT_ERROR
   except GitHubError as e:
       logger.error("GitHub %s failed for class %s: status %s (during the writes, after %d ms)",
                    e.operation, class_name, e.status, elapsed_ms(started))
       raise Refusal(502, GITHUB_UNFINISHED_ERROR, "github_write") from None
   logger.info("GitHub writes took %d ms", elapsed_ms(started))
   ```

   A dry run never reaches the second block, so every GitHub failure on stage says nothing
   was changed. `plan_submission` never raises `SubmissionConflict` (only `_move_branch`
   inside `apply_submission` does), so the first block doesn't catch it. A `GitHubConflict`
   from `apply_submission` (a 422 on the pull request) is a `GitHubError` raised while
   writing, so it gets the "submit again" message, which is right: the next submission
   finds the branch and opens or updates its pull request. The first write is
   `create_blob`; a failure in the blob, tree or commit moves no ref, so nothing visible
   changed, but "submit again" is still right advice there (accepted; the README says
   so). The failure line during the writes carries the elapsed ms (prep amendment), so a
   slow GitHub can be told from a fast failure.
6. `load_classes()` is deleted (no caller is left); `grep -n load_classes` finds nothing
   in the function or its tests.

**Logs** (new): `Class list from %s (age %d s): %d classes` on submit;
`Time left before the GitHub writes: %d ms`; `Time left after planning (dry run): %d ms`;
`GitHub writes took %d ms`; the GitHub failure line gains "before any write" / "during the
writes, after %d ms". The prod figure for #118 criterion 3 is the `Time left before the
GitHub writes` line, taken from a request whose log also says `Class list from cache`
(a live read's figure includes Neon's time; README Admin actions 3). No username, token,
photo or body in any of them.

**Responses** (changed rows only):

| Status | Message | When |
| --- | --- | --- |
| 502 | `Couldn't open the pull request. Nothing was changed on GitHub. Try again in a minute.` | The installation token, a read-only planning call, or any GitHub call on a dry run failed; or too little time was left to write |
| 502 | `Couldn't finish the pull request on GitHub. Submit the same class again: it finishes the same pull request instead of opening a second one.` | A GitHub call failed after the writes began (prod only) |
| 502 | `Couldn't load the class list. Try again in a minute.` | No cached list, and Neon or the Neon secret failed (was: Neon failed) |

### docs

API `README.md`:

- "How It Works", submission step 3: "Read the class list from the cache (phase 1's rule:
  under 26 hours old without Neon; otherwise Neon live, falling back to the cached copy);
  refuse a class that isn't in it, or whose name can't be a file name."
- "Responses": the three rows above replace the old GitHub row and the Neon row (the
  Neon row loses its "or always (submit, which still reads Neon live)" clause); the
  `Pick a class from the list.` row says "the server's class list" instead of "the Neon
  list"; the sentence under the table ("Submitting again after a 409 or a 502…") says the
  "nothing was changed" message means a retry starts clean, and the "submit again"
  message means a retry finishes the same pull request (it can also follow a failed
  blob, tree or commit, which changed nothing visible: still safe to submit again).
- The "Logs" paragraph: add the submit lines (`Time left before the GitHub writes`,
  `Time left after planning (dry run)`, `GitHub writes took`, and "before any write" /
  "during the writes" on a GitHub failure).
- "Limits", "Time": with a warm cache a submission spends no time in Neon; the log line
  "Time left before the GitHub writes" records the margin on prod.
- "Limits", "Cache": when Neon fails, a submission is checked against the cached copy
  whatever its age (on stage, which has no schedule, it can be old), and a manual refresh
  whose cache write failed shows the page a list the server's copy doesn't have yet, so
  a class new in that list can answer "Pick a class from the list." until a refresh
  succeeds (prep audit, accepted).
- Remove the phase 1 note that submit still reads Neon live (step 3 and the Neon row).

## Tests

In `tests/test_lambda_function.py` (all with phase 1's `fake_cache` fixture; tests fill
it with phase 1's `cached_copy(age, source)` helper, which gains a keyword-only
`names: tuple[str, ...] = CACHED_NAMES` parameter, by setting `mocks.cache.record`; prep
amendment: no new `put_cache` helper. `CACHED_NAMES` already holds `CLASS_NAME`):

- `test_submit_uses_cached_list_without_neon`: cache holds `CLASS_NAME` and two others →
  200; `mocks.neon` and the Neon secret (`mocks.aws.get_secret`) not called;
  `plan_submission` received the cached names as `all_classes` (#118 AC1, #114 "submit
  validation against it").
- `test_submit_works_while_neon_is_down_with_cache`: fresh cache, Neon raises
  `NeonCRMError` → 200, and `search_events` and `mocks.aws.get_secret` were never called
  (#118 AC1; the assertions are what make this test differ from the one above).
- `test_submit_with_old_cache_and_neon_down_uses_the_copy`: copy over 26 hours old, Neon
  raises → 200, validated against the copy.
- `test_submit_class_not_in_cached_list_400`: cache without the class (Neon would have it)
  → 400 "Pick a class from the list.", Neon not called, `installation_token`,
  `plan_submission` and `apply_submission` not called (#118 AC2).
- `test_submit_forbidden_character_from_cache_400`: cache holds "AC/DC Basics", submit it
  → 400 with its file-name message, nothing on GitHub (#118 AC2).
- `test_submit_cache_miss_reads_neon_and_fills_cache`: empty cache → Neon called once, the
  item now holds the list, 200.
- The existing `test_submit_class_not_in_list_400`, `test_submit_forbidden_character_400`
  and `test_submit_neon_failure_returns_502` keep passing (empty cache → live read).
- `test_submit_logs_time_left_before_the_writes`: prod, `FakeContext(remaining_ms=20_000)`
  → log has `Time left before the GitHub writes: 20000 ms` and `GitHub writes took` (#118
  AC3).
- `test_submit_dry_run_logs_time_left_after_planning`: dry run → `Time left after planning
  (dry run): 20000 ms`; `apply_submission` not called.
- `test_submit_github_error_502_without_details` (updated, parametrized as today): the
  token and `plan_submission` failures answer `GITHUB_NOTHING_CHANGED_ERROR`; the two
  `apply_submission` failures answer `GITHUB_UNFINISHED_ERROR`; the operation name is never
  in the body (#118 AC6, server part). The log says "before any write" for the first two
  and "during the writes, after … ms" for the last two.
- `test_submit_dry_run_github_error_says_nothing_changed`: dry run, `plan_submission`
  raises `GitHubError` → `GITHUB_NOTHING_CHANGED_ERROR`.
- `test_submit_with_too_little_time_left_writes_nothing` (updated): the body is
  `GITHUB_NOTHING_CHANGED_ERROR`.
- `test_logs_hold_no_username_token_or_photo` keeps passing with a warm cache (add a
  variant that pre-fills the cache).

## Acceptance criteria

1. With a cached list under 26 hours old, a submission doesn't call Neon or read the Neon
   secret, and works while Neon is down (#118 AC1).
2. A class not in the server's list answers 400 "Pick a class from the list." and a class
   whose name can't be a file name answers its message; neither calls GitHub (#118 AC2).
3. A prod submission logs the milliseconds left before the GitHub writes and how long the
   writes took; a dry run logs the time left after planning (#118 AC3).
4. A GitHub failure before any write (and every GitHub failure on a dry run) answers
   "Couldn't open the pull request. Nothing was changed on GitHub. Try again in a minute.";
   a failure after the writes began answers "Couldn't finish the pull request on GitHub.
   Submit the same class again: it finishes the same pull request instead of opening a
   second one." Neither carries GitHub's operation, status or text (#118 AC6).
5. `load_classes` and `GITHUB_ERROR` no longer exist; the API README's Responses table
   lists the new messages.

## Verification

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_api
.venv/bin/python -m pytest
```

No template change, so `cfn-lint`, `sam validate` and `sam build` aren't required (run
them if phase 1 is in the same pull request).

After the stage deploy: open the stage page, wait for the list, choose a class and a 3:2
JPEG, and submit. The dry run answers in under 6 s (it took 10.2 s on 2026-10-17); the
log shows `Class list from cache` and `Time left after planning (dry run): … ms`, and no
`Neon read` line for that request.

## Admin actions

None for this phase. After the prod deploy, README Admin actions 3 (record the prod
"Time left before the GitHub writes" figure on #114).

## Hand-off

Done. Phase 3 can rely on: the submit route's two GitHub messages,
`lambda_function.GITHUB_NOTHING_CHANGED_ERROR` ("Couldn't open the pull request. Nothing
was changed on GitHub. Try again in a minute.") and `lambda_function.GITHUB_UNFINISHED_ERROR`
("Couldn't finish the pull request on GitHub. Submit the same class again: it finishes the
same pull request instead of opening a second one."), both answered as JSON 502
`{"error": ...}` and shown by the page as given, like every server message; `NEON_ERROR`,
`GENERIC_ERROR`, `FORBIDDEN_ERROR` and `CONFLICT_ERROR` unchanged; a dry run never answers
the "submit again" message. `GITHUB_ERROR` and `load_classes()` no longer exist.

As built, differences from the text above: `handle_submit` takes the service as a
parameter (`handle_submit(event, context, username, dry_run, service)`), and a small
`elapsed_ms(started)` helper replaces the inline arithmetic in the Neon read's failure
line too. `docs/README.md`'s class-photo entry gained one sentence (submit checks the same
cached copy). The full check set (cfn-lint, `sam validate`, `sam build`) was run because
phase 1's template change is in the same pull request: cfn-lint reports only the 4
`W3005` warnings that `stage` also has.

**Manual QA notes (for `/offshore`'s QA doc, #118):** on stage, with the cache warm (load
the page once), submit a 3:2 JPEG for a listed class: the dry run answers in under 6 s,
and the log `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` shows `Class list from
cache (age … s)` and `Time left after planning (dry run): … ms` for that request, and no
`Neon read` line. On prod, after the deploy, README Admin actions 3.
