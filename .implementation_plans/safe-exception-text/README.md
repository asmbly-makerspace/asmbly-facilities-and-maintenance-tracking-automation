---
plan: safe-exception-text
epic: 141
---

# Safe exception text: implementation plan

**Created:** 2026-10-17

## Overview

Bug #95, the follow-up to #86 (PR #96). PR #96 made the shared helpers' own log lines
safe but deliberately kept the text of the exceptions they raise. That text still
carries vendor content:

- `layers/common/python/common/clickup.py` `_make_clickup_request` raises a `ValueError`
  whose message holds the whole ClickUp error body (`json.dumps(e.response.json())` or
  `e.response.text`), or `str(e)` from `requests` (the full URL and query string). The
  `raise` inside `except` also chains the `requests` exception, so a traceback
  (`logger.exception`, `exc_info=True`, `traceback.print_exc()`) prints the URL again.
- `update_task` raises a `ValueError` holding the whole task JSON ClickUp returned:
  assignee and creator names and emails, and the description, which for problem reports
  holds the reporter's contact details.
- Seven functions log that text, and four routes plus the `/reorder` modal hand an
  exception's text to whoever called them: `/purchase-request/new` (#83),
  `/problem-report/slack-reaction`, `/purchase-request/slack-reaction` (and the same
  functions when the router invokes them), the PM reminder's 500 result, and the
  `/reorder` error modal. `slack.send_slack_message` returns `error_message: str(e)`.
- Around those, the functions this plan touches log whole payloads (the Slack event,
  which carries Slack's verification token; the Discourse reply; a Slack response's
  text; the ClickUp task returned by an update), `neoncrm.py` sets the root logger to
  INFO on import and logs a Neon response body, `discourse.py` logs Discourse's response
  body and the full URL, `print` is still used in two handlers, and the ClickUp, Slack
  and Neon calls have no `requests` timeout.

After this plan, the helpers' exception messages are built only from the method, the
endpoint path, the HTTP status and reason, ClickUp's validated `ECODE` and task IDs, with
no chained `requests` exception; callers get a fixed plain message; the payload log lines
log IDs; and the cleanup and timeouts follow. Status codes don't change. No template,
route, IAM or deploy-role change, and no route gets a caller check (that is #79).

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #142 | ClickUp failures are logged without vendor bodies or personal data | 1 |
| #143 | Error replies and the /reorder error screen show a plain message | 2 |
| #144 | Neon, Discourse and handler logs carry no member emails or vendor bodies | 3 |
| #145 | A hung ClickUp, Slack or Neon call fails within 8 seconds | 3 |

`/offshore` lands all three phases in one pull request to `stage`. That pull request
says `Closes #142`, `Closes #143`, `Closes #144`, `Closes #145`, `Closes #141` (the
epic), `Closes #95` (the bug the epic fixes) and `Closes #83` (the same line as #143's
`/purchase-request/new` criterion). If the phases go out in separate pull requests,
each says `Closes` only for its own row's stories and `Refs #95`; only the pull request
that lands phase 3 says `Closes #141` and `Closes #95`, and phase 2's says `Closes #83`.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [ClickUp exception text and payload log lines](phase-1-clickup-exception-text.md) | layer, lambda | M | [ ] Pending |
| 2 | [Plain error replies and /reorder error modal](phase-2-plain-error-replies.md) | lambda, layer, docs | M | [ ] Pending |
| 3 | [Logging cleanup and request timeouts](phase-3-logging-cleanup-and-timeouts.md) | layer, lambda, docs | L | [ ] Pending |

## Dependencies

- Phase 2 depends on phase 1: both edit the two Slack reaction functions,
  `new_purchase_request_received` and `slack_slash_reorder`, and phase 2's "the error is
  still logged" is only safe once phase 1 has made the ClickUp text safe.
- Phase 3 depends on phase 2: both edit `new_purchase_request_received`,
  `pm_bot_reminder` and `layers/common/python/common/slack.py`, and phase 3 also edits
  `clickup.py`, which phase 1 changes.
- No other plan, secret or third-party setup is needed.

## Parallelism

Every pair of phases is sequential-only (and each is already ordered by `depends_on`):

| Pair | Shared paths |
| --- | --- |
| 1 and 2 | `functions/{problem_report,purchase_request}/slack_reaction_webhook/lambda_function.py` and tests, `functions/purchase_request/new_purchase_request_received/lambda_function.py` and tests, `functions/purchase_request/slack_slash_reorder/lambda_function.py` and tests |
| 1 and 3 | `layers/common/python/common/clickup.py`, `layers/common/tests/test_clickup.py`, `functions/purchase_request/new_purchase_request_received/lambda_function.py` |
| 2 and 3 | `layers/common/python/common/slack.py`, `layers/common/tests/test_slack.py`, `functions/facilities/pm_bot_reminder/*`, `functions/purchase_request/new_purchase_request_received/*` |

Don't build any phase at the same time as #137, which refactors
`functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py`.
This plan doesn't edit that file (Decision 6), so the two only need to not run at once
in case a test there turns out to need a change.

## Admin actions

None. No named resource, secret, SSM parameter, route, schedule or deploy-role change;
`template-cicd.yaml` is not touched, and no Slack or ClickUp setting changes. The layer
change reaches every function that uses `CommonLayer` on the normal deploy.

## Related work

- **#86 / PR #96** (merged): made the helpers' log lines safe and kept exception text,
  return values and the Slack dry-run `print` on purpose. This plan changes the first
  two and keeps the dry-run preview.
- **#83** (open): `/purchase-request/new` returns the exception's text. Phase 2 fixes the
  same line; the final pull request closes it.
- **#79** (open): caller checks on public routes. Shares the reaction functions, the
  router and `/reorder`; this plan adds no check. Sequential with any #79 work on those
  files.
- **#99** (open): `NeonCRM.update_account_custom_field` swallows failures. Phase 3
  changes only that method's log lines and adds a timeout; whichever lands second
  rebases. The return behavior stays #99's.
- **#137** (open, epic #136): refactors the kiln viewer's test file; see Parallelism.
- Open pull request #68 (templates and CI) shares no file.

## Out of scope

- Caller authentication for any route (#79). CLAUDE.md: don't add checks to an existing
  route as a side effect.
- `/reorder`'s own direct `views.open` / `views.update` calls through `requests.Session`,
  which have no timeout (a possible follow-up; listed in the briefing).
- Discourse request timeouts: #145 names ClickUp, Slack and Neon only (Decision 11).
- `NeonCRM.update_account_custom_field` reporting failure to its caller (#99).
- The Slack helper's dry-run `print` preview (kept, as PR #96 decided).
- `new_purchase_request_received`'s missing-environment-variable 500 body, which names
  the missing variables (configuration names, not exception text or personal data).
- `new_problem_report_request_received` line 100, which logs the report's summary
  (reporter-written text); its other `logger.error("...: %s", e)` lines become safe with
  phase 1 and are left as they are.
- f-strings and other style problems in log lines this plan doesn't otherwise touch.
- `docs/README.md`: no service's trigger, URL or caller configuration changes
  (Decision 12).

## Security

- **Exception text** from `common.clickup` holds only the method, endpoint path (IDs, no
  query string), HTTP status and reason, the `ECODE` validated by `_ecode_for_log`, the
  requested task ID and the returned task ID validated by `_task_id_for_log`, or the
  `requests` exception class name. Raised `from None`, so no traceback carries the
  `requests` exception (URL, query string).
- **Responses** never contain exception text: fixed bodies on every 500, fixed text in
  the `/reorder` error modal, and no `error_message` in `send_slack_message`'s result.
  Status codes stay the same, so ClickUp's webhook failure counting and Lambda's async
  retry behavior don't change.
- **Logs** carry IDs (event ID, channel, message ts, view ID, task ID, Discourse post ID,
  Neon account ID), status codes and vendor error codes, never a whole Slack event
  (verification token), Discourse body, Neon body, ClickUp task or email address.
- **Logging setup:** the layer configures no logger level (neoncrm's root `setLevel`
  goes); handlers keep setting their own level.
- **Timeouts** (phase 3): 8 seconds per request for ClickUp, Slack and Neon, under the
  shortest affected function's 10-second limit.
- No IAM, secret, route or caller-check change.

## Decisions

Made without asking, inside `/offshore` (2026-10-17).

1. **#95 became epic #141 with stories #142–#145.** #95 is a bug issue, not an epic;
   `/plan-product` wrote the epic with "Fixes the bug in #95" so the final pull request
   says `Closes #95` along with the stories and the epic. Alternative: plan legacy-mode
   against #95 directly. Reason: the orchestrator asked for stories with testable
   criteria; the stories make each phase's target explicit.
2. **#83 is closed by this work, not planned separately.** #143's
   `/purchase-request/new` criterion is #83's fix on the same line. Alternative: leave
   #83 for its own pull request. Reason: two pull requests editing one line conflict.
3. **Three phases, data leak first.** Phase 1 the exception text and payload log lines
   (#142), phase 2 the replies (#143), phase 3 the cleanup and timeouts (#144, #145).
   Alternative: phases 1 and 2 as one M/L phase, or four phases with timeouts alone.
   Reason: the orchestrator asked for 2–3 reviewable phases with the leak first; the
   timeouts are about 120 lines and share `clickup.py` / `slack.py` with the cleanup.
   Phase 3 is L (estimated 450–550 lines, mostly tests), under the 800 ceiling.
4. **The ClickUp exception messages change** (unlike #86, which kept them), but keep the
   `ClickUp API HTTP Error: <status> <reason>` and `Network error during ClickUp API
   request` prefixes. Nothing in production code parses the text (domain brief); only
   `layers/common/tests/test_clickup.py` pins it, and those assertions are updated, not
   deleted.
5. **`raise ... from None`** for both ClickUp `ValueError`s raised inside `except`.
   Alternative: keep the implicit chain. Reason: `logger.exception` (kiln viewer),
   `exc_info=True` (`/reorder`) and `traceback.print_exc()` (PM reminder) print the
   chained `requests.HTTPError`, whose text is the full URL with the query string.
   `common.neoncrm._post_search` already does this.
6. **The kiln viewer's test file is not edited.** Its
   `test_lambda_handler_error_page_hides_exception_text` builds its own marker and
   patches `get_all_clickup_tasks`, so it keeps passing. #137 refactors that file later.
7. **Payload log lines in the touched handlers are in phase 1 (#142).** Both reaction
   functions' `Received event: {event}` (the Slack event carries Slack's verification
   `token`), the Discourse reply response, `/reorder`'s `api_response.text`, and
   `new_purchase_request_received`'s print of the update response. Reason: the same leak
   in the same files; #142's criterion 5 names them.
8. **`/reorder`'s failed `views.update` log line keeps the view ID, the HTTP status and
   Slack's `ok` flag, not Slack's error code.** Alternative: make
   `common.slack._slack_error_for_log` public and log the validated code. Reason: keeps
   phase 1 out of `slack.py`; the error code is a nice-to-have for this one line.
9. **Status codes and log levels stay; only bodies, text and log arguments change.**
   Fixed bodies: `"Internal server error."` for both reaction functions, `"An error
   occurred while processing the purchase request."` for `/purchase-request/new`,
   `"Error: the PM reminder run failed."` for the PM reminder. Each phase document gives
   the exact strings so tests can pin them.
10. **Timeout is 8 seconds** as a module constant per helper (`DEFAULT_TIMEOUT_SECONDS`
    in `clickup.py`, `slack.py`, `neoncrm.py`), applied with `kwargs.setdefault` in
    `_make_clickup_request` so a caller can still pass its own. Alternative: 10 s like
    `github_app` and `neoncrm.search_events`. Reason: the shortest affected function
    (`/reorder`, the purchase-request reaction function, the kiln viewer) has a
    10-second limit; 8 s leaves time to log and answer. `search_events` keeps 10 s
    (#145 says so; its only caller runs for 25 s).
11. **Discourse gets no timeout here.** #145 lists ClickUp, Slack and Neon; the issue
    names `clickup.py` and `slack.py`. Alternative: add it in phase 3 too. Reason: keep
    to the stories; listed in the briefing as a follow-up.
12. **`docs/README.md` doesn't change.** No service's trigger, URL or caller
    configuration changes. The function READMEs that describe what a caller sees on
    failure (`/reorder`, new purchase request, PM reminder) and the shared helpers'
    timeout get a line each.
13. **#95's Neon email items are already fixed on `stage`.** `get_account_by_email` logs
    neither the email (`No NeonCRM account matches the searched email`) nor the
    exception text (`type(e).__name__`). The code wins: phase 3 pins that with a test
    and changes the root-logger `setLevel`, the f-strings and the response body in
    `update_account_custom_field`, which are still there.
14. **The two new handler loggers follow the handlers' pattern**
    (`logger = logging.getLogger()` and `logger.setLevel(logging.INFO)`, as
    `dynamic_dns_update` does), so their INFO lines still reach CloudWatch (Lambda's
    root default is WARNING). The layer modules use `logging.getLogger(__name__)` and set
    no level.
