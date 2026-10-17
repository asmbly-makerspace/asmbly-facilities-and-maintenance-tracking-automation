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

> **Status:** [ ] Pending

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

| Path | What |
| --- | --- |
| `layers/common/tests/test_neoncrm.py` | Tests for the Neon helper's logging and timeouts. |
| `layers/common/tests/test_discourse.py` | Tests for the Discourse helper's failure logging. |

## Files to modify

| Path | Change |
| --- | --- |
| `layers/common/python/common/neoncrm.py` | `logging.getLogger(__name__)`, no `setLevel`; lazy, body-free log lines in `update_account_custom_field`; `DEFAULT_TIMEOUT_SECONDS = 8.0` on the account search and the account update. |
| `layers/common/python/common/discourse.py` | `logging.getLogger(__name__)`; failure log line with method, path and status (or exception class), no body, no full URL; type hints on `_make_discourse_request`. |
| `layers/common/python/common/clickup.py` | `DEFAULT_TIMEOUT_SECONDS = 8.0`; `kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)` in `_make_clickup_request`. |
| `layers/common/python/common/slack.py` | `DEFAULT_TIMEOUT_SECONDS = 8.0`; `timeout=` on `requests.post` in `send_slack_message` and `session.get` in `get_slack_user_info`. |
| `layers/common/tests/test_clickup.py` | Timeout tests. |
| `layers/common/tests/test_slack.py` | Timeout tests; add `timeout=8.0` to the `assert_called_once_with` in `test_get_slack_user_info` (line 120). |
| `functions/facilities/pm_bot_reminder/lambda_function.py` | Root `logger` at INFO; every `print` becomes a lazy `logger` call; `traceback.print_exc()` becomes `logger.exception`; drop the `traceback` import. |
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
- `get_account_by_email` keeps its log lines; a test pins that the email isn't in them.

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

### lambda: `pm_bot_reminder`

- `import logging`; `logger = logging.getLogger()`; `logger.setLevel(logging.INFO)`
  (README Decision 14).
- Each `print` becomes `logger.info` with lazy arguments, keeping its words, for example
  `logger.info("Found %d overdue tasks.", len(overdue_tasks))`. The SSM lines keep the
  parameter name (configuration, not secret). The per-channel line keeps the channel
  name; the threaded-reply line keeps the task ID and channel ID.
- The fatal handler: `logger.exception("PM reminder run failed")` replaces the `print`
  and `traceback.print_exc()`; the 500 body is phase 2's.
- The `requests` import, if unused after this, goes; check with `grep`.
- Add type hints to `lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]`.

### lambda: `new_purchase_request_received`

- Each remaining `print` becomes `logger.info` / `logger.warning` / `logger.error`:
  - `SLACK_WORKSPACE_URL … not set` → `logger.warning`.
  - missing environment variables → `logger.error("Missing required environment variables: %s", ", ".join(missing_vars))`
    (the 500 body naming them is unchanged; out of scope).
  - the ClickUp test webhook → `logger.info`.
  - Slack failure → `logger.error("Failed to send Slack message for task %s", task_id)`
    (the helper already logged Slack's validated error code).
  - permalink, custom field, success → `logger.info` with the task ID and field ID.
- Add type hints to the handler and `get_slack_post_url`.

## Tests

`layers/common/tests/test_neoncrm.py` (new; patch `common.neoncrm.requests.post` /
`.patch`):

- `test_import_sets_no_log_level`: after `importlib.reload(common.neoncrm)` with the root
  logger set to WARNING, the root level is still WARNING and
  `logging.getLogger("common.neoncrm").level == logging.NOTSET`. Restore the root level
  in a `finally`.
- `test_get_account_by_email_logs_no_email`: found, not found and `ConnectionError`
  cases; `caplog.text` never holds the planted `pk_member@example.com`.
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

`layers/common/tests/test_discourse.py` (new; patch `common.discourse.requests.request`):

- `test_http_error_logs_method_path_status_not_body`: an `HTTPError` with
  `status_code=422`, `text="pk_DISCOURSE_BODY reporter@example.com"`, URL
  `https://yo.asmbly.org/posts.json?api_key=pk_QUERY`; the ERROR record is
  `Discourse POST /posts.json failed with HTTP 422`; none of the markers appear; the
  `HTTPError` is re-raised.
- `test_network_error_logs_type_only`: `ConnectionError("pk_URL")` → the record names
  `ConnectionError`, not `pk_URL`; re-raised.
- `test_logger_is_named`: records come from `common.discourse`, and the root level is
  unchanged by importing the module.

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
.venv/bin/python -m pytest layers/common/tests functions/facilities functions/purchase_request functions/administrative functions/classes functions/problem_report
.venv/bin/python -m pytest
sam build
```

On the stage stack after deploy:

- After the next scheduled PM reminder run on stage, the
  `/asmbly/lambda/PMReminderBotFunction-stage` log shows `[INFO]` records (`Found N
  overdue tasks.`) and no bare stdout lines.
- Submit a waiver on stage (or replay the stage CleverWaiver test): the
  `NewWaiverCompletedFunction-stage` log still shows its INFO lines, with no email.
- React to a problem-report message on stage: the reaction completes as before.

## Admin actions

None.

## Hand-off

The plan is complete. The final pull request lists `Closes #142`, `#143`, `#144`,
`#145`, `#141`, `#95` and `#83`, and the follow-ups in the README's Out of scope
(`/reorder`'s direct Slack calls without a timeout, Discourse timeouts, #99) go in the
briefing.
