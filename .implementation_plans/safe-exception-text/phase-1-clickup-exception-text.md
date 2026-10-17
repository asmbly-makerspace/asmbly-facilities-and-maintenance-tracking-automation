---
phase_id: 1
title: ClickUp exception text and payload log lines
epic: 141
implements: [142]
depends_on: []
domain: [layer, lambda]
estimated_size: M
---

# Phase 1: ClickUp exception text and payload log lines

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md` ("Rules", "Done means verified").
- `layers/common/python/common/clickup.py`: `_make_clickup_request` (lines 49–73),
  `update_task` (lines 89–115), and the safe-log helpers `_ecode_for_log` and
  `_task_id_for_log` (lines 16–33), which PR #96 added.
- `layers/common/python/common/neoncrm.py` `_post_search` (lines 128–143): the model for
  a status-only exception message raised `from None`.
- `layers/common/tests/test_clickup.py`: the tests that pin today's text (lines 55–69,
  143–322) and the helpers `_http_error_response` and `_clickup_errors`.
- The four handlers below and their tests.
- Story #142 and its acceptance criteria.

## Goal

The `ValueError`s that `common.clickup` raises carry no ClickUp response body, no task
JSON and no `requests` exception text, in their message or in their chained traceback.
The four handlers this plan touches stop logging whole payloads and log IDs instead.
Status codes, return values and the exception types don't change.

## Files to create

None.

## Files to modify

| Path | Change |
| --- | --- |
| `layers/common/python/common/clickup.py` | Build both `ValueError` messages in `_make_clickup_request` and the one in `update_task` from safe fields; raise the two in `_make_clickup_request` `from None`. |
| `layers/common/tests/test_clickup.py` | Update the seven assertions that pin the old text; add tests that no body, task field, URL or query string reaches `str(exc)` or the formatted traceback. |
| `functions/purchase_request/slack_reaction_webhook/lambda_function.py` | Line 14: log the event's type, reaction, channel, message ts and event ID instead of the whole event. |
| `functions/purchase_request/slack_reaction_webhook/tests/test_slack_reaction_webhook.py` | Test for the new log line. |
| `functions/problem_report/slack_reaction_webhook/lambda_function.py` | Line 13: as above. Line 99: log the Discourse reply's post ID, not the whole response. |
| `functions/problem_report/slack_reaction_webhook/tests/test_slack_reaction_webhook.py` | Tests for both log lines. |
| `functions/purchase_request/slack_slash_reorder/lambda_function.py` | Line 172: log the view ID, HTTP status and Slack's `ok` flag, not `api_response.text`. |
| `functions/purchase_request/slack_slash_reorder/tests/test_slack_slash_reorder_lambda_function.py` | Test for the failed `views.update` log line. |
| `functions/purchase_request/new_purchase_request_received/lambda_function.py` | Line 122: delete the `print` of `json.dumps(update_response)` (line 123 already says the task was updated, with its ID). |
| `functions/purchase_request/new_purchase_request_received/tests/test_lambda_function.py` | Assert stdout doesn't contain the update response. |

Not modified: `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`
(README Decision 6). Its error-page test builds its own marker and keeps passing.

## Implementation details

### layer: `common/clickup.py`

`_make_clickup_request(api_token: str, method: str, endpoint: str, **kwargs: Any) -> Any`
keeps its signature and its log lines. Only the raised messages change:

- **HTTP error.** Remove the `error_message += " - Details: …"` and
  `" - Response body: …"` lines. Keep parsing `e.response.json()` into `error_details`
  (for the ECODE; a `ValueError` from `.json()` leaves it `None`). Raise:

  ```python
  raise ValueError(
      f"ClickUp API HTTP Error: {e.response.status_code} {e.response.reason} - "
      f"{method} {endpoint} (ECODE={_ecode_for_log(error_details)})"
  ) from None
  ```

  `endpoint` holds IDs only (query parameters go through `params=`, PR #96). ECODE is
  `None`, the validated code, or `<invalid>`.

- **Network error** (`requests.exceptions.RequestException`, which includes timeouts):

  ```python
  raise ValueError(
      f"Network error during ClickUp API request: {method} {endpoint} ({type(e).__name__})"
  ) from None
  ```

`update_task(api_token: str, task_id: str, payload: dict[str, Any]) -> Any`: replace the
message built from `json.dumps(response_data)` and `response_data['err']` with one built
from the IDs the log line already uses:

- no returned ID (including a non-dict response):
  `f"ClickUp task update for {task_id} returned 200 OK but no task ID (ECODE={ecode})"`
- another ID:
  `f"ClickUp task update for {task_id} returned 200 OK but task ID {_task_id_for_log(returned_id)} (ECODE={ecode})"`

where `ecode = _ecode_for_log(response_data)`. Build the message and the log line from
the same values, so they can't drift. Drop the `'err'` suffix (vendor text). The
`update_task` raise isn't inside an `except`, so it needs no `from None`. `task_id` is
the caller's own ID, not vendor content.

No other function in `clickup.py` changes. No logging setup, no `exc_info`.

### lambda: payload log lines

- **Both reaction functions, "Received event"** (`purchase_request/...:14`,
  `problem_report/...:13`). The router passes Slack's event body, which carries Slack's
  verification `token`, the team and user IDs. Replace with a lazy line built from
  `event.get("event", {})` (guard non-dict values):

  ```python
  logger.info(
      "Received event: type=%s reaction=%s channel=%s ts=%s event_id=%s",
      inner.get("type"), inner.get("reaction"), item.get("channel"), item.get("ts"), event.get("event_id"),
  )
  ```

  where `inner = event.get("event") if isinstance(event.get("event"), dict) else {}` and
  `item = inner.get("item") if isinstance(inner.get("item"), dict) else {}`. A
  `url_verification` challenge event logs `type=None …`, which is fine. Guard `event`
  itself not being a dict (log `Received event: not a dict`) so the log line can't raise
  before the `try`.

- **Problem-report reaction, Discourse reply** (`:99`): replace
  `logger.info(f"Discourse reply response: {reply_response}")` with
  `logger.info("Discourse reply posted: post_id=%s", reply_response.get("id") if isinstance(reply_response, dict) else None)`.
  The reply body holds the post text and the bot's user record.

- **`/reorder`, failed `views.update`** (`handle_block_actions`, `:172`): replace
  `logger.error("Error updating Slack view: %s", api_response.text)` with
  `logger.error("Error updating Slack view %s: HTTP %s, ok=%s", view_id, api_response.status_code, ok)`,
  where `ok` is `api_response.json().get("ok")` when the body parses as a dict, else
  `None`. Compute it once and reuse it in the `if` (today's `if` calls `.json()` without a
  guard; keep the same branch outcome). Don't log Slack's error code (README Decision 8).

- **New purchase request** (`:122`): delete the `print` of the update response. Line 123
  (`Successfully updated task {task_id} …`) stays; phase 3 converts it to `logger`.

Leave every other line in these handlers alone; phase 2 changes their error replies and
phase 3 their `print`s.

## Tests

`layers/common/tests/test_clickup.py` (update; don't delete any test):

- `test_fetch_clickup_tasks_page_http_error`: the `match="ClickUp API HTTP Error: 401 Unauthorized"` stays and still passes.
- `test_make_clickup_request_http_error_logs_status_not_body`: `str(excinfo.value)` is
  exactly `ClickUp API HTTP Error: 401 Unauthorized - GET <endpoint> (ECODE=OAUTH_025)`;
  `pk_BODY_MARKER` is not in it; `excinfo.value.__cause__ is None` and
  `excinfo.value.__suppress_context__ is True`.
- `test_make_clickup_request_http_error_non_json_body_not_logged`: the message ends
  `(ECODE=None)` and has no `<html>` or `pk_BODY_MARKER`.
- `test_make_clickup_request_network_error_logs_type_only`: the message is
  `Network error during ClickUp API request: GET <endpoint> (ConnectionError)`; it doesn't
  contain `str(err)` or the planted URL / query string.
- `test_update_task_mismatch_logs_ids_not_task_body`: the message is
  `ClickUp task update for t1 returned 200 OK but task ID other (ECODE=None)`; `Jane Member`
  and `bad` are not in it.
- `test_update_task_list_response_raises_same_value_error`: the message is
  `… for t1 returned 200 OK but no task ID (ECODE=None)`.
- `test_update_task_missing_id_logs_no_task_id`: the message ends
  `no task ID (ECODE=OAUTH_027)`; `Team not authorized` is not in it.
- `test_update_task_mismatch_with_non_id_value_not_logged`: the message says
  `task ID <invalid>`.

New:

- `test_make_clickup_request_http_error_traceback_has_no_body_or_url`: an `HTTPError`
  whose `str()` is a URL with `?token=pk_URL_MARKER` and whose body has a planted email
  and phone number; `"".join(traceback.format_exception(excinfo.value))` contains none of
  them.
- `test_make_clickup_request_network_error_traceback_has_no_url`: same for a
  `ConnectionError("…?q=pk_URL_MARKER")`.
- `test_update_task_message_has_no_task_fields`: a returned task with `assignees`
  (name, email), `creator`, and a `description` holding a phone number; the message
  holds none of them and names both IDs.

Handler tests:

- `purchase_request/.../test_received_event_log_omits_token_and_body`: an event with
  `"token": "pk_VERIFY_MARKER"` and an `event.item` with channel `C123`, ts `123.456`;
  `caplog` contains `C123` and `123.456` and not `pk_VERIFY_MARKER`.
- `problem_report/.../test_received_event_log_omits_token_and_body`: as above.
- `problem_report/.../test_discourse_reply_log_has_post_id_only`: `discourse.post_reply`
  returns `{"id": 987, "raw": "pk_REPLY_MARKER", "username": "facilities-bot"}`; the log
  has `987` and no `pk_REPLY_MARKER`.
- `slack_slash_reorder/.../test_block_actions_failed_update_logs_status_not_body`: the
  mocked session's `post` returns `ok=False`, `status_code=400`, `text="pk_SLACK_MARKER"`,
  `json()` → `{"ok": False, "error": "invalid_blocks", "response_metadata": {"messages": ["pk_SLACK_MARKER"]}}`;
  the ERROR record holds the view ID and `400`, not `pk_SLACK_MARKER`; the handler still
  answers 200 with an empty body.
- `new_purchase_request_received/.../test_lambda_handler_success` (extend, or a new
  `test_update_response_not_printed`): `clickup.set_custom_field_value` returns a task
  with a planted `pk_TASK_MARKER` name; `capsys` stdout doesn't contain it.

Patch where used (`functions.<area>.<name>.lambda_function.<module>`), no network.

## Acceptance criteria

1. For a ClickUp 4xx/5xx with a JSON or HTML body containing a name, an email or a phone
   number, neither the raised message nor its formatted traceback contains any of the
   body (#142 AC1).
2. The HTTP-error message is `ClickUp API HTTP Error: <status> <reason> - <METHOD>
   <endpoint> (ECODE=<code|None|<invalid>>)` (#142 AC1, AC4).
3. A `update_task` mismatch message names the requested and returned task IDs (or "no
   task ID") and the ECODE, and none of the task's fields (#142 AC2).
4. A network failure's message is `Network error during ClickUp API request: <METHOD>
   <endpoint> (<ExceptionClass>)`, with no URL or query string in it or its traceback
   (#142 AC3).
5. Neither reaction function logs the Slack event's `token` or body; the problem-report
   function doesn't log the Discourse reply body; `/reorder` doesn't log a Slack
   response's text; new purchase request doesn't print the update response (#142 AC5).
6. Every function's status codes and return values are unchanged; the whole suite passes
   (#142 AC4).
7. No template, route or deploy-role file changes (#142 AC6).

## Verification

```bash
.venv/bin/python -m pytest layers/common/tests/test_clickup.py functions/purchase_request functions/problem_report
.venv/bin/python -m pytest
sam build
```

`cfn-lint` and `sam validate` aren't needed (no template change). `sam build` is (layer
change).

On the stage stack after deploy: run `/reorder`, pick an item, and in the
`SlackSlashReorderFunction-stage` log group see the normal lines. To see the new error
text without breaking anything, react with a configured emoji to a message in the
problem-report channel whose ClickUp task was deleted: the
`ProblemReport-ReactionFunction-stage` log shows `ClickUp API HTTP Error: 404 Not Found -
PUT task/<id> (ECODE=…)` and no task or body text, and the `Received event` line shows
type, reaction, channel, ts and event ID only.

## Admin actions

None.

## Hand-off

- `common.clickup` raises `ValueError` with the messages above, `from None`. Phase 2 can
  log any caught ClickUp exception with `logger.exception` safely.
- The reaction functions, `/reorder` and new purchase request log IDs, not payloads.
- No change to responses yet: phase 2 changes them.
