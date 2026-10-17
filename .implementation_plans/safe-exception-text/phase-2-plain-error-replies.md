---
phase_id: 2
title: Plain error replies and /reorder error modal
epic: 141
implements: [143]
depends_on: [1]
domain: [lambda, layer, docs]
estimated_size: M
---

# Phase 2: Plain error replies and /reorder error modal

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`: "Send an exception's text to the caller" (Never) and "Don't add checks to
  an existing route as a side effect of other work".
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py` lines
  181–183: the model (`logger.exception`, then a fixed message).
- `functions/purchase_request/slack_slash_reorder/lambda_function.py`:
  `handle_process_submission` (error modal at line 243), `handle_load_data_and_update_view`
  (line 279), and the sync catch at line 347 (already generic; unchanged).
- `functions/purchase_request/new_purchase_request_received/lambda_function.py` lines
  50–129, `functions/{problem_report,purchase_request}/slack_reaction_webhook/lambda_function.py`
  (the final `except`), `functions/facilities/pm_bot_reminder/lambda_function.py` lines
  173–177, `layers/common/python/common/slack.py` lines 81–91.
- Their tests, listed below. Issue #83, story #143.
- Phase 1's hand-off: ClickUp exception text is safe to log.

## Goal

No response, Slack modal or helper return value carries an exception's text. Each
failure still answers with today's status code and is still logged for the maintainer
with the IDs at hand. No route gets a caller check.

## Files to create

None.

## Files to modify

| Path | Change |
| --- | --- |
| `functions/purchase_request/slack_slash_reorder/lambda_function.py` | The two error modals show fixed text. |
| `functions/purchase_request/slack_slash_reorder/tests/test_slack_slash_reorder_lambda_function.py` | Two new tests. |
| `functions/purchase_request/new_purchase_request_received/lambda_function.py` | Fixed 500 body; add a module logger and log the exception with the task ID. |
| `functions/purchase_request/new_purchase_request_received/tests/test_lambda_function.py` | Invert the assertion in `test_lambda_handler_clickup_get_task_failure`; one new test. |
| `functions/problem_report/slack_reaction_webhook/lambda_function.py` | Fixed 500 body; `logger.exception` with IDs. |
| `functions/problem_report/slack_reaction_webhook/tests/test_slack_reaction_webhook.py` | Invert `test_handler_general_exception`. |
| `functions/purchase_request/slack_reaction_webhook/lambda_function.py` | As above. |
| `functions/purchase_request/slack_reaction_webhook/tests/test_slack_reaction_webhook.py` | Tighten `test_lambda_handler_general_exception`. |
| `functions/facilities/pm_bot_reminder/lambda_function.py` | Fixed 500 body (the `print`s stay until phase 3). |
| `functions/facilities/pm_bot_reminder/tests/test_pm_bot_reminder_lambda_function.py` | Invert the body assertion in `test_lambda_handler_fatal_error`. |
| `layers/common/python/common/slack.py` | `send_slack_message`'s exception result drops `error_message`. |
| `layers/common/tests/test_slack.py` | Update `test_send_slack_message_exception_logs_type_only`. |
| `functions/purchase_request/slack_slash_reorder/README.md` | A short "If something goes wrong" note: the two messages the user can see. |
| `functions/purchase_request/new_purchase_request_received/README.md` | Under "Usage" or "Step-by-Step Data Flow": what the route answers on failure. |

## Implementation details

Exact strings (README Decision 9); tests pin them.

### lambda: `/reorder` error modals

Both modals keep `"title": "Error"` and the `Close` button; only the section text
changes. Define the two views as module constants (or a small typed builder,
`def _error_view(text: str) -> dict[str, Any]:`):

- `handle_load_data_and_update_view` (`:279`):
  `"Couldn't load the items to reorder. Please try `/reorder` again in a few minutes."`
- `handle_process_submission` (`:243`):
  `"Your purchase request was not created. Please try again in a few minutes."`

The existing `logger.error("…view_id %s: %s", view_id, e, exc_info=True)` lines stay
(safe after phase 1). The modal is posted by the async self-invocation after Slack has
already been answered, so the 3-second limit doesn't apply. The sync catch at `:347`
already answers `{"error": "An internal server error occurred."}`; unchanged.

### lambda: `/purchase-request/new`

- Add `import logging`, `logger = logging.getLogger()`, `logger.setLevel(logging.INFO)`
  (README Decision 14).
- Set `task_id: str | None = None` before the `try`, so the `except` can name it.
- Replace the `except` body (`:127–129`):

  ```python
  except Exception:
      logger.exception("Failed to process purchase request for task %s", task_id)
      return {'statusCode': 500, 'body': json.dumps('An error occurred while processing the purchase request.')}
  ```

  The `print(f"An error occurred: {e}")` goes (the log record replaces it). Other `print`s
  stay until phase 3. Fixes #83.

### lambda: both reaction functions

Replace the final `except` in each:

```python
except Exception:
    logger.exception("Unexpected error processing reaction")
    return {"statusCode": 500, "body": json.dumps("Internal server error.")}
```

The phase 1 "Received event" line already logged the channel, ts and event ID for this
invocation. Status 500 stays: the router invokes these with `InvocationType='Event'`, so
the body is discarded there; on the public routes (no caller today, #79) the body was
the leak.

### lambda: PM reminder

`:177` becomes `return {"statusCode": 500, "body": json.dumps("Error: the PM reminder run failed.")}`.
The `print` and `traceback.print_exc()` above it stay until phase 3 (safe after phase 1).

### layer: `common.slack.send_slack_message`

Keep the `except Exception as e:` and its log line (`type(e).__name__`); return
`{"ok": False, "error": "script_error"}`. No caller reads `error_message` (domain brief);
`new_problem_report_request_received` and `new_purchase_request_received` read only
`error`. Update the return-type docstring if it mentions `error_message`.

### docs

- `/reorder` README: when loading fails the modal says the first message; when
  submitting fails, the second; details are in the `SlackSlashReorderFunction-<stage>`
  log group.
- New purchase request README: on any failure after validation the route answers 500
  with `An error occurred while processing the purchase request.`; the log has the task
  ID.

## Tests

- `slack_slash_reorder/.../test_load_data_failure_shows_plain_error_modal`: patch
  `get_all_clickup_tasks` to raise `ValueError("ClickUp API HTTP Error: 401 Unauthorized - GET list/pk_LIST_MARKER/task (ECODE=OAUTH_025)")`;
  the `views.update` call's JSON view has title `Error` and the exact load-failure text,
  and `json.dumps(view)` contains neither `pk_LIST_MARKER`, `401` nor `ClickUp`; an ERROR
  record names the view ID.
- `slack_slash_reorder/.../test_process_submission_failure_shows_plain_error_modal`:
  patch `create_task` to raise with a planted marker; the modal holds the exact
  submission-failure text and no marker.
- `new_purchase_request_received/.../test_lambda_handler_clickup_get_task_failure`
  (invert): 500, body is exactly `"An error occurred while processing the purchase request."`
  (JSON-encoded), `ClickUp API is down` not in it; Slack not called.
- `new_purchase_request_received/.../test_failure_logs_task_id`: an ERROR record from the
  handler names the payload's task ID and has `exc_info`.
- `problem_report/.../test_handler_general_exception` (invert): 500, body is
  `"Internal server error."`, `Something broke!` not in it; an ERROR record has
  `exc_info`.
- `purchase_request/.../test_lambda_handler_general_exception` (tighten): body is
  exactly `"Internal server error."` and contains no exception text.
- `pm_bot_reminder/.../test_lambda_handler_fatal_error` (invert the body line only):
  500, body is `"Error: the PM reminder run failed."`, `Something went terribly wrong`
  not in it. Its `capsys` assertions stay until phase 3.
- `layers/common/tests/test_slack.py::test_send_slack_message_exception_logs_type_only`:
  the return value is exactly `{"ok": False, "error": "script_error"}`; `pk_EXC_MARKER`
  is not in `str(response)`.

## Acceptance criteria

1. When loading `/reorder` items fails, the modal titled "Error" shows exactly the
   load-failure text and nothing from the exception (#143 AC1).
2. When a `/reorder` submission fails, the modal shows exactly the submission-failure
   text and nothing from the exception (#143 AC2).
3. `POST /purchase-request/new` answers 500 with the fixed body on any failure inside the
   `try`, ClickUp, Slack, Secrets Manager or SSM alike (#143 AC3, #83).
4. Both reaction functions answer 500 with `"Internal server error."` (#143 AC4).
5. The PM reminder's 500 body is `"Error: the PM reminder run failed."` (#143 AC5).
6. `send_slack_message`'s exception result is `{"ok": False, "error": "script_error"}`
   (#143 AC6).
7. Every status code is unchanged; each failure is logged with the view, task or
   event ID; no file under `templates/`, `template.yaml` or `template-cicd.yaml` changes,
   and no route gains a caller check (#143 AC7).

## Verification

```bash
.venv/bin/python -m pytest functions/purchase_request functions/problem_report functions/facilities layers/common/tests/test_slack.py
.venv/bin/python -m pytest
sam build
```

On the stage stack after deploy (stage API: the stage stack's `FacilitiesApiUrl`
output, `https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage` per
`docs/README.md`):

- `curl -s -X POST <FacilitiesApiUrl>/purchase-request/new -d '{"trigger_id":"x","payload":{"id":"doesnotexist"}}'`
  answers 500 `"An error occurred while processing the purchase request."` with no
  ClickUp text, and the `/asmbly/lambda/NewPurchaseRequestReceivedFunction-stage` log
  has an ERROR record naming task `doesnotexist` with a ClickUp line in phase 1's form.
- `/reorder` in the stage Slack workspace still opens, loads and submits as before. The
  error modals are covered by the tests; they can't be triggered on stage without
  breaking the stage ClickUp token, so no manual step forces them.

## Admin actions

None.

## Hand-off

- Every caller-facing reply is fixed text; tests pin the strings.
- `new_purchase_request_received` has a root `logger` at INFO; phase 3 converts its
  remaining `print`s to it.
- `send_slack_message` returns no `error_message`.
- The PM reminder still uses `print` and `traceback.print_exc()`; phase 3 converts them
  and updates `test_lambda_handler_fatal_error`'s `capsys` assertions.
