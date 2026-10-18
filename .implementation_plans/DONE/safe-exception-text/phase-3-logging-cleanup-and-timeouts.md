---
phase_id: 3
title: Logging cleanup and request timeouts
epic: 141
implements: [144, 145]
depends_on: [2]
domain: [layer, lambda, docs]
estimated_size: L
---

# Phase 3: Logging cleanup and request timeouts

> **Status:** [x] Complete — 2026-10-17 on branch feature/safe-exception-text

## Required reading

- `CLAUDE.md` ("Rules": lazy `logging`, no personal data or bodies in logs).
- `layers/common/python/common/neoncrm.py`: the root-logger lines 6–7,
  `get_account_by_email` (lines 40–70, already safe, README Decision 13),
  `update_account_custom_field` (lines 72–94), `_post_search` (the safe model).
- `layers/common/python/common/discourse.py` `_make_discourse_request` (lines 8–23).
- `layers/common/python/common/clickup.py` `_make_clickup_request`;
  `layers/common/python/common/slack.py` `send_slack_message` and `get_slack_user_info`;
  `layers/common/python/common/github_app.py` (`DEFAULT_TIMEOUT`, the precedent).
- `functions/facilities/pm_bot_reminder/lambda_function.py` and
  `functions/purchase_request/new_purchase_request_received/lambda_function.py` (all
  `print` calls) and their tests.
- The Neon callers' tests: `functions/administrative/new_waiver_completed/tests/test_lambda_function.py`
  (`assertLogs(level="DEBUG")`, `neoncrm.requests.post/patch` patched) and
  `functions/classes/class_photo_upload_api/tests/`.
- Stories #144 and #145. Phase 2's hand-off.

## Goal

The Neon and Discourse helpers log through their own named loggers, set no level, and
log no email, body or full URL. The PM reminder and new purchase request log through
`logging` instead of `print`. Every request the ClickUp, Slack and Neon helpers send has
an 8-second timeout (Neon's events search keeps 10 s), and a timeout is handled like any
other failure of that service.

## Files to create

None. (Prep amendment: the Neon and Discourse helpers' tests already live in
`layers/common/python/tests/`. Neither layer test folder has an `__init__.py`, so a
second `test_neoncrm.py` or `test_discourse.py` under `layers/common/tests/` would stop
pytest with "import file mismatch". The new tests go into the existing files.)

## Files to modify

| Path | Change |
| --- | --- |
| `layers/common/python/common/neoncrm.py` | `logging.getLogger(__name__)`, no `setLevel`; lazy, body-free log lines in `update_account_custom_field`; the HTTP status in `get_account_by_email`'s failure line; `DEFAULT_TIMEOUT_SECONDS = 8.0` on the account search and the account update. |
| `layers/common/python/common/discourse.py` | `logging.getLogger(__name__)`; failure log line with method, path and status (or exception class), no body, no full URL; type hints on `_make_discourse_request`. |
| `layers/common/python/common/clickup.py` | `DEFAULT_TIMEOUT_SECONDS = 8.0`; `kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)` in `_make_clickup_request`. |
| `layers/common/python/common/slack.py` | `DEFAULT_TIMEOUT_SECONDS = 8.0`; `timeout=` on `requests.post` in `send_slack_message` and `session.get` in `get_slack_user_info`; `get_slack_user_info` logs a failed request (service, endpoint, exception class) and re-raises. |
| `layers/common/python/tests/test_neoncrm.py` | The Neon tests below; add `timeout=8.0` to the two existing `assert_called_once_with` calls (lines 52 and 142). |
| `layers/common/python/tests/test_discourse.py` | The Discourse tests below. |
| `layers/common/tests/test_clickup.py` | Timeout tests. |
| `layers/common/tests/test_slack.py` | Timeout tests; add `timeout=8.0` to the `assert_called_once_with` in `test_get_slack_user_info` (line 120); a user-lookup failure test. |
| `functions/facilities/pm_bot_reminder/lambda_function.py` | Root `logger` at INFO; every `print` becomes a lazy `logger` call; `traceback.print_exc()` becomes `logger.exception`; drop the inline `traceback` import. |
| `functions/facilities/pm_bot_reminder/tests/test_pm_bot_reminder_lambda_function.py` | `test_lambda_handler_fatal_error` asserts on `caplog` instead of `capsys`; a new test for the INFO lines. |
| `functions/purchase_request/new_purchase_request_received/lambda_function.py` | Every remaining `print` becomes a lazy `logger` call (phase 2 added the logger). |
| `functions/purchase_request/new_purchase_request_received/tests/test_lambda_function.py` | A test that the handler prints nothing and logs its INFO lines. |
| `functions/facilities/pm_bot_reminder/README.md` | One line: progress and errors are log records in `/asmbly/lambda/PMReminderBotFunction-<stage>`. |
| `docs/README.md` | Nothing (README Decision 12), unless `/write-docs` finds a sentence about the layer that the timeout makes wrong. |

## Implementation details

### layer: `common/neoncrm.py`

- Replace `logger = logging.getLogger()` and `logger.setLevel(logging.INFO)` with
  `logger = logging.getLogger(__name__)`. The layer does no logging setup (PR #96's rule).
  Its callers (`new_waiver_completed`, `class_photo_upload_api`) set INFO themselves
  (domain brief), so their INFO lines stay.
- `DEFAULT_TIMEOUT_SECONDS = 8.0`. `get_account_by_email(self, email: str, timeout: float = DEFAULT_TIMEOUT_SECONDS)`
  passes `timeout=timeout` to `requests.post`. `update_account_custom_field(self, account_id: str, field_id: str, field_value: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None`
  passes it to `requests.patch`. `search_events` keeps its `timeout: float = 10.0`.
- `update_account_custom_field` log lines:
  - success: `logger.info("Updated custom field %s for NeonCRM account %s", field_id, account_id)`
  - failure: `status = e.response.status_code if e.response is not None else "no response"`;
    `logger.error("Error updating NeonCRM account %s: %s (status %s)", account_id, type(e).__name__, status)`.
    No `e`, no `e.response.text`.
  - The method still returns `None` on failure; changing that is #99.
- `get_account_by_email` keeps its found and not-found lines; a test pins that the email
  isn't in them. Its failure line gains the status (#144 AC2 asks for it; prep
  amendment), built the same way:
  `logger.error("Error searching for NeonCRM account: %s (status %s)", type(e).__name__, status)`.
  The method still returns `None` on failure (a Neon outage then looks like "no account"
  to `new_waiver_completed`; that is pre-existing and goes in the briefing next to #99).
- Each `DEFAULT_TIMEOUT_SECONDS` (here, in `clickup.py` and in `slack.py`) gets a
  one-line comment: seconds per request (to connect, and between bytes of the answer),
  under the 10-second limit of the shortest function that uses the helper. This is the
  "line each" for the helpers' timeout in README Decision 12; there is no layer README.

### layer: `common/discourse.py`

- `logger = logging.getLogger(__name__)`.
- `def _make_discourse_request(method: str, url: str, api_key: str, api_username: str, **kwargs: Any) -> Any:`
- Failure: `path = urllib.parse.urlsplit(url).path`; if `e.response is not None`,
  `logger.error("Discourse %s %s failed with HTTP %s", method, path, e.response.status_code)`,
  else `logger.error("Discourse %s %s failed: %s", method, path, type(e).__name__)`.
  Re-raise as today (`raise`): callers (`new_problem_report_request_received`, the
  problem-report reaction function) catch it, and their own `%s`-of-`e` lines carry only
  `requests`' text (`<status> Client Error: <reason> for url: https://yo.asmbly.org/posts.json`,
  no query string, no body). No timeout here (README Decision 11).
- The `logger.error("Could not construct Discourse URL from response.")` line stays.

### layer: timeouts in `clickup.py` and `slack.py`

- `clickup.py`: `DEFAULT_TIMEOUT_SECONDS = 8.0`; in `_make_clickup_request`, before the
  call, `kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)`. A
  `requests.exceptions.Timeout` is a `RequestException`, so it is logged as
  `ClickUp GET … request failed: ReadTimeout` and raised as
  `Network error during ClickUp API request: GET … (ReadTimeout)` (phase 1's form).
  The callers already handle that `ValueError` (the `/reorder` error modal, new purchase
  request's 500, the reaction functions' 500, the PM reminder's 500, the kiln viewer's
  error page, new problem report's logged step failure).
- `slack.py`: `DEFAULT_TIMEOUT_SECONDS = 8.0`; `requests.post(..., timeout=DEFAULT_TIMEOUT_SECONDS)`
  in `send_slack_message` (a timeout lands in the existing `except Exception`, logs
  `ReadTimeout` and returns `{"ok": False, "error": "script_error"}`);
  `session.get(..., timeout=DEFAULT_TIMEOUT_SECONDS)` in `get_slack_user_info` (the
  exception propagates as today; `/reorder` catches it and shows its submission-failure
  modal). The dry-run branch is unchanged.
- `get_slack_user_info` (prep amendment, #145 AC2): wrap the `get` and
  `raise_for_status` in `try`/`except requests.exceptions.RequestException as e:`, log
  `logger.error("Slack users.info failed: %s", type(e).__name__)` and `raise` (the same
  exception, so `/reorder` behaves as today). Without it a timeout is logged only by
  `/reorder`, as `requests`' text, which names no endpoint. Type the signature:
  `get_slack_user_info(api_token: str, user_id: str, http_session: requests.Session | None = None) -> Any`.
- The timeout is per request (README Decision 10). It doesn't cap a function's total
  time: `/reorder`'s submission makes three calls in a 10-second function, so a slow
  ClickUp can still run it out of time. And a write that ClickUp or Slack commits after
  the 8 seconds now counts as a failure (see Decision below). Both are accepted for this
  phase and listed in the briefing.

### lambda: `pm_bot_reminder`

- `import logging`; `logger = logging.getLogger()`; `logger.setLevel(logging.INFO)`
  (README Decision 14).
- Each `print` becomes `logger.info` with lazy arguments, keeping its words, for example
  `logger.info("Found %d overdue tasks.", len(overdue_tasks))`. The SSM lines keep the
  parameter name (configuration, not secret). The per-channel line keeps the channel
  name; the threaded-reply line keeps the task ID and channel ID.
- The fatal handler: `logger.exception("PM reminder run failed")` replaces the `print`
  and `traceback.print_exc()`; the 500 body is phase 2's.
- There is no `requests` import any more (phase 2 removed it); nothing to drop.
- The handler is already typed (`event: Any`, phase 2); leave it.

### lambda: `new_purchase_request_received`

- Each remaining `print` becomes `logger.info` / `logger.warning` / `logger.error`:
  - `SLACK_WORKSPACE_URL … not set` → `logger.warning`.
  - missing environment variables → `logger.error("Missing required environment variables: %s", ", ".join(missing_vars))`
    (the 500 body naming them is unchanged; out of scope).
  - the ClickUp test webhook → `logger.info`.
  - Slack failure → `logger.error("Failed to send Slack message for task %r", task_id)`
    (the helper already logged Slack's validated error code).
  - permalink, custom field, success → `logger.info` with the task ID and field ID.
  - The task ID comes from an unauthenticated request body, so every line that logs it
    uses `%r`, as phase 2's ERROR line does (prep amendment: `repr` escapes newlines).
- The handler is already typed (phase 2); add hints to `get_slack_post_url(channel_id: str, message_ts: str) -> str | None`.

## Tests

`layers/common/python/tests/test_neoncrm.py` (existing; add these; patch
`common.neoncrm.requests.post` / `.patch`):

- `test_get_account_by_email_found` and `test_update_account_custom_field_success`
  (update): their `assert_called_once_with` gains `timeout=8.0`.
- `test_import_sets_no_log_level`: import `common.neoncrm` in a fresh interpreter
  (`subprocess.run([sys.executable, "-c", ...])` with `PYTHONPATH` set to
  `layers/common/python`) that first sets the root logger to WARNING, and print the root
  level and `logging.getLogger("common.neoncrm").level`; assert WARNING and NOTSET. Prep
  amendment: don't `importlib.reload` the module. A reload rebinds `NeonCRM` and
  `NeonCRMError`, so tests that imported them earlier (`pytest.raises(NeonCRMError)` here
  and in `functions/classes/class_photo_upload_api/tests/`) fail depending on the order.
- `test_get_account_by_email_logs_no_email`: found, not found and `ConnectionError`
  cases; `caplog.text` never holds the planted `pk_member@example.com`.
- `test_get_account_by_email_http_error_logs_status`: an `HTTPError` whose response has
  `status_code=401` and a body marker; the ERROR record holds `HTTPError` and `401`, not
  the marker or the email.
- `test_update_account_custom_field_failure_logs_status_not_body`: an `HTTPError` whose
  response has `status_code=400`, `text="pk_NEON_BODY jane@example.com"`; the ERROR
  record holds the account ID, `HTTPError` and `400`, not the body or email; the method
  returns `None`.
- `test_update_account_custom_field_network_error_logs_type`: `ConnectionError("pk_URL")`
  → `ConnectionError` and `no response` logged, `pk_URL` not.
- `test_account_calls_pass_timeout`: `requests.post` and `requests.patch` are called with
  `timeout=8.0`.
- `test_search_events_keeps_ten_second_timeout`: `requests.post` gets `timeout=10.0` by
  default.

`layers/common/python/tests/test_discourse.py` (existing; add these; patch
`common.discourse.requests.request`):

- `test_http_error_logs_method_path_status_not_body`: an `HTTPError` with
  `status_code=422`, `text="pk_DISCOURSE_BODY reporter@example.com"`, URL
  `https://yo.asmbly.org/posts.json?api_key=pk_QUERY`; the ERROR record is
  `Discourse POST /posts.json failed with HTTP 422`; none of the markers appear; the
  `HTTPError` is re-raised.
- `test_network_error_logs_type_only`: `ConnectionError("pk_URL")` → the record names
  `ConnectionError`, not `pk_URL`; re-raised.
- `test_logger_is_named`: records come from `common.discourse`, and the root level is
  unchanged by importing the module (the same fresh-interpreter check as Neon's; no
  reload).

`layers/common/tests/test_clickup.py`:

- `test_make_clickup_request_passes_default_timeout`: `requests.request` gets
  `timeout=8.0`.
- `test_make_clickup_request_caller_timeout_wins`: `_make_clickup_request(..., timeout=3)`
  passes `timeout=3`.
- `test_make_clickup_request_timeout_raises_network_error`: `requests.exceptions.ReadTimeout`
  → `ValueError` `Network error during ClickUp API request: GET <endpoint> (ReadTimeout)`
  and one ERROR record naming `ReadTimeout`.

`layers/common/tests/test_slack.py`:

- `test_send_slack_message_passes_timeout`: `requests.post` gets `timeout=8.0`.
- `test_send_slack_message_timeout_returns_script_error`: `ReadTimeout` →
  `{"ok": False, "error": "script_error"}` and an ERROR record naming `ReadTimeout`.
- `test_get_slack_user_info` (update): `assert_called_once_with` includes `timeout=8.0`.
- `test_get_slack_user_info_timeout_logs_and_reraises`: the session's `get` raises
  `ReadTimeout("pk_URL")`; the same exception propagates, and one ERROR record from
  `common.slack` reads `Slack users.info failed: ReadTimeout`, without `pk_URL` or the
  token.

Handlers:

- `pm_bot_reminder/.../test_lambda_handler_fatal_error` (update): `capsys` stdout and
  stderr are empty of `FATAL ERROR` and `Traceback`; an ERROR record from the handler has
  `exc_info`. The phase 2 body assertion stays.
- `pm_bot_reminder/.../test_lambda_handler_logs_progress_at_info`: with the no-tasks
  mocks, `caplog` at INFO holds `Found 0 overdue tasks.` and the handler wrote nothing to
  stdout (the dry-run test's stdout assertions stay: the Slack dry-run `print` is kept).
- `new_purchase_request_received/.../test_handler_logs_instead_of_printing`: the success
  path writes nothing to stdout and `caplog` at INFO holds the task ID.

Before finishing: run the whole suite. Removing neoncrm's root `setLevel` can expose a
test elsewhere that relied on the import side effect to see INFO records; fix such a test
by setting the level it needs (`caplog.set_level` / `assertLogs(level=...)`), never by
deleting or skipping it.

## Acceptance criteria

1. Importing `common.neoncrm` changes no logger's level; the waiver and class photo
   upload tests that read INFO lines still pass (#144 AC1, AC6).
2. A failed or empty Neon account search logs no email and no response body (#144 AC2).
3. A failed Neon account update logs the operation, account ID and HTTP status (or "no
   response"), and no body (#144 AC3).
4. A failed Discourse call logs the method, the URL path and the HTTP status (or the
   exception class), with no body or query string (#144 AC4).
5. The PM reminder and new purchase request call no `print`; their INFO lines are log
   records (#144 AC5).
6. The ClickUp, Slack (post, user lookup) and Neon (account search, update) requests have
   an 8-second timeout; Neon's events search keeps 10 s (#145 AC1).
7. A timeout is logged with the service, endpoint and `ReadTimeout`/`ConnectTimeout`,
   and the caller handles it as any other failure of that service (#145 AC2).
8. A request that answers in time behaves exactly as before: the whole suite passes
   (#145 AC3, #144 AC6).
9. No template file changes; no function's `Timeout` changes (#145 AC4).

## Verification

```bash
.venv/bin/python -m pytest layers/common/tests layers/common/python/tests functions/facilities functions/purchase_request functions/administrative functions/classes functions/problem_report
.venv/bin/python -m pytest
sam build
```

On the stage stack after deploy:

- After the next scheduled PM reminder run on stage (weekly, Saturdays 04:30 UTC), the
  `/asmbly/lambda/PMReminderBotFunction-stage` log shows `[INFO]` records (`Found N
  overdue tasks.`) and no `--- HANDLER STARTED ---` line. Stage runs with `DRY_RUN=true`,
  so the Slack helper's dry-run preview lines (`--- DRY RUN MODE ---`) still appear as
  plain stdout there; that is expected.
- Submit a waiver on stage (or replay the stage CleverWaiver test): the
  `NewWaiverCompletedFunction-stage` log still shows its INFO lines, with no email.
- React to a problem-report message on stage: the reaction completes as before.

## Admin actions

None.

## Decisions (prep, inside `/offshore`)

- **`/reorder`'s submission-failure text stays** ("Your purchase request was not created.
  Please try again in a few minutes."; phase 2's hand-off asked). With the 8-second
  timeout, a `create_task` that ClickUp commits after 8 seconds shows that text although
  the task exists, and a retry files a duplicate. Alternative: reword to "may not have
  been created; check ClickUp before trying again". Reason: #143 AC2 requires a message
  saying the request was not created; a create that takes over 8 seconds is rare, a
  duplicate purchase request is visible in ClickUp and cheap to close, and every other
  submission failure (HTTP errors, user lookup, item lookup) really did create nothing.
  The same applies to the other writes: new purchase request answers 500 after Slack
  posted (ClickUp may resend the webhook and post again), and new problem report says
  "Error creating task" for a task that exists. Listed in the briefing as a follow-up
  (tell a `ReadTimeout` on a write apart from other failures).
- **The timeout is per request, not per function** (corrects README Decision 10's "8 s
  leaves time to log and answer", which holds for one call). Listed in the briefing: a
  deadline from `context.get_remaining_time_in_millis()`, or `MaximumRetryAttempts: 0`
  on the async `/reorder` invocation so a Lambda timeout doesn't retry `create_task`.
- **`_make_clickup_request`'s caller timeout** is reachable only from inside
  `clickup.py`: the public helpers (`get_task`, `create_task`, …) don't pass `timeout`
  through. The `setdefault` keeps that door open; no public signature changes here.

## Hand-off

The plan is complete. The final pull request lists `Closes #142`, `#143`, `#144`,
`#145`, `#141`, `#95` and `#83`, and the follow-ups in the README's Out of scope
(`/reorder`'s direct Slack calls without a timeout, Discourse timeouts, #99) go in the
briefing, with this phase's decisions above (a write committed after the timeout, the
per-request limit) and `new_waiver_completed` treating a failed Neon search (now
including a timeout) as "no account" and answering 404, and a failed or timed-out
account update as success (200), because `update_account_custom_field` still returns
`None` either way (#99). Before the timeout, a hung Neon ran the function into its
30-second limit instead. Also: no async invocation sets `MaximumRetryAttempts`, so a
`/reorder` submission that runs out of time is retried by Lambda.

What this phase delivered (for the integration gate and the pull request):

- `DEFAULT_TIMEOUT_SECONDS = 8.0` in `common.clickup` (applied with
  `kwargs.setdefault("timeout", …)` in `_make_clickup_request`), `common.slack`
  (`send_slack_message`, `get_slack_user_info`) and `common.neoncrm`
  (`get_account_by_email(email, timeout=…)`, `update_account_custom_field(account_id,
  field_id, field_value, timeout=…)`). `search_events` keeps `timeout=10.0`.
- `get_slack_user_info` logs `Slack users.info failed: <ExceptionClass>` and re-raises the
  same exception; it is now typed.
- `common.neoncrm` and `common.discourse` log through `logging.getLogger(__name__)` and set
  no level. Neon failure lines: `Error searching for NeonCRM account: <Class> (status
  <code|no response>)`, `Error updating NeonCRM account <id>: <Class> (status …)`; success
  `Updated custom field <field> for NeonCRM account <id>`. Discourse: `Discourse <METHOD>
  <path> failed with HTTP <status>` or `… failed: <Class>`.
- The PM reminder and new purchase request call no `print`. The PM reminder's banners are
  now `PM reminder run started` and `PM reminder run finished: <n> tasks processed`, and a
  failure is `PM reminder run failed` with `exc_info`. New purchase request logs the task
  ID with `%r` on every line.
- The Neon and Discourse tests live in `layers/common/python/tests/` (prep amendment); the
  import-level checks run in a fresh interpreter.
- Deferred (style, from the independent review): `test_discourse.py` repeats the
  fresh-interpreter helper that `test_neoncrm.py` defines; a shared `conftest.py` could
  hold it.
