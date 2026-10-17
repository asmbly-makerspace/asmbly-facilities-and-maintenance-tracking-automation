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

> **Status:** [ ] Pending

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

### lambda

**Messages** (module constants; `GITHUB_ERROR` is removed, README Decision 10):

```python
GITHUB_NOTHING_CHANGED_ERROR = "Couldn't open the pull request. Nothing was changed on GitHub. Try again in a minute."
GITHUB_UNFINISHED_ERROR = (
    "Couldn't finish the pull request on GitHub. Submit the same class again: "
    "it finishes the same pull request instead of opening a second one."
)
```

**`handle_submit()`**, in today's order (parse, decode the photo, class, GitHub):

1. `parse_submission` and `decode_photo` unchanged (a bad photo still never reaches the
   cache, Neon or GitHub).
2. The class list:

   ```python
   service = class_list_service()
   result = service.for_request()
   logger.info("Class list from %s (age %d s): %d classes", result.served_from, service.age_seconds(result), len(result.names))
   classes = result.names
   ```

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
5. GitHub, with a flag that says whether writing has started:

   ```python
   writing = False
   try:
       token = github_app.installation_token(...)          # unchanged arguments
       repo = github_app.GitHubRepo(...)
       plan = submission.plan_submission(repo, config, class_name, classes, username)
       left = remaining_ms(context)
       if dry_run:
           result = submission.dry_run_result(plan)
           logger.info("Dry run for class %s: %s on branch %s", class_name, result.action, plan.branch)
           if left is not None:
               logger.info("Time left after planning (dry run): %d ms", left)
       else:
           if left is not None and left < WRITE_MIN_REMAINING_MS:
               logger.error("Not enough time left to write: %d ms", left)
               raise Refusal(502, GITHUB_NOTHING_CHANGED_ERROR, "time")
           if left is not None:
               logger.info("Time left before the GitHub writes: %d ms", left)
           writing = True
           started = time.monotonic()
           result = submission.apply_submission(...)          # unchanged arguments
           logger.info("GitHub writes took %d ms", round((time.monotonic() - started) * 1000))
   except submission.SubmissionConflict:
       ...                                                    # unchanged: 409 CONFLICT_ERROR
   except GitHubError as e:
       logger.error("GitHub %s failed for class %s: status %s (%s)", e.operation, class_name, e.status,
                    "during the writes" if writing else "before any write")
       if writing:
           raise Refusal(502, GITHUB_UNFINISHED_ERROR, "github_write") from None
       raise Refusal(502, GITHUB_NOTHING_CHANGED_ERROR, "github_read") from None
   ```

   A dry run never sets `writing`, so every GitHub failure on stage says nothing was
   changed. The `Refusal("time")` raised inside the `try` is not a `GitHubError` and
   passes through. A `GitHubConflict` from `apply_submission` (a 422 on the pull request)
   is a `GitHubError` raised while writing, so it gets the "submit again" message, which
   is right: the next submission finds the branch and opens or updates its pull request.
6. `load_classes()` is deleted (no caller is left); `grep -n load_classes` finds nothing
   in the function or its tests.

**Logs** (new): `Class list from %s (age %d s): %d classes` on submit;
`Time left before the GitHub writes: %d ms`; `Time left after planning (dry run): %d ms`;
`GitHub writes took %d ms`; the GitHub failure line gains "during the writes" / "before any
write". The prod figure for #118 criterion 3 is the first of these (README Admin
actions 3). No username, token, photo or body in any of them.

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
- "Responses": the three rows above replace the old GitHub row and the Neon row; the
  sentence under the table says the "nothing was changed" message means a retry starts
  clean, and the "submit again" message means a retry finishes the same pull request.
- "Limits", "Time": with a warm cache a submission spends no time in Neon; the log line
  "Time left before the GitHub writes" records the margin on prod.
- Remove the phase 1 note that submit still reads Neon live.

## Tests

In `tests/test_lambda_function.py` (all with phase 1's `fake_cache` fixture; a helper
`put_cache(names, age_seconds=0)` puts a `ClassListRecord` into the fake):

- `test_submit_uses_cached_list_without_neon`: cache holds `CLASS_NAME` and two others →
  200; `mocks.neon` not called; `plan_submission` received the cached names as
  `all_classes` (#118 AC1, #114 "submit validation against it").
- `test_submit_works_while_neon_is_down_with_cache`: fresh cache, Neon raises
  `NeonCRMError` → 200 (#118 AC1).
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
  in the body (#118 AC6, server part).
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

_Filled in when the phase is done._ Phase 3 can rely on: the submit route's two GitHub
messages (shown by the page as given, like every server message); `NEON_ERROR`,
`GENERIC_ERROR` and `FORBIDDEN_ERROR` unchanged; a dry run never answers the "submit
again" message.
