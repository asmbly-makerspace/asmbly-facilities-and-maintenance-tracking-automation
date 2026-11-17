---
phase_id: 6
title: ClickUp comment naming who ticked it
epic: 7
implements: [165]
depends_on: [5]
domain: [lambda, layer, infra, docs]
estimated_size: S
---

# Phase 6: ClickUp comment naming who ticked it

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's `README.md` (Decision 1, Security).
- `functions/facilities/pm_reminder_reaction/lambda_function.py` after phase 5 (the
  success path and `_austin_date`).
- `common/clickup.py`: `_make_clickup_request` (raises `ValueError` with a safe
  message), `update_task`; `layers/common/tests/test_clickup.py` (how
  `requests.request` is patched).
- `common/slack.py`: `get_slack_user_info` (raises on HTTP errors; returns Slack's
  JSON, which can be `ok: false`), `get_slack_post_url`.
- `SLACK_WORKSPACE_URL` in `templates/purchase_request.yaml` and
  `templates/problem_report.yaml`.
- ClickUp API v2, Create Task Comment: `POST /task/{task_id}/comment` with
  `comment_text` and `notify_all`.

## Goal

Each completion from Slack leaves one comment on the ClickUp task: who marked it done,
when (Austin time), and a link to the reminder. Duplicates, stale ✅s and dry runs leave
none. A comment failure never undoes the completion.

## Files to create

None.

## Files to modify

- `layers/common/python/common/clickup.py`: `create_task_comment`.
- `layers/common/tests/test_clickup.py`: its tests.
- `functions/facilities/pm_reminder_reaction/lambda_function.py`: the comment on the
  success path.
- `functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`
- `functions/facilities/pm_reminder_reaction/README.md`: "What ClickUp shows".
- `templates/facilities.yaml`: `SLACK_WORKSPACE_URL`.
- `docs/README.md`: one clause in the handler's entry.

## Implementation details

### layer: `common/clickup.py`

```python
def create_task_comment(api_token: str, task_id: str, comment_text: str) -> Any:
    """Adds a comment to a ClickUp task without notifying watchers. Raises ValueError on failure."""
    return _make_clickup_request(
        api_token, "POST", f"task/{task_id}/comment",
        json={"comment_text": comment_text, "notify_all": False},
    )
```

Errors come from `_make_clickup_request`, which logs the method, endpoint shape, status
and `ECODE` only.

### lambda: the comment

On the `completed` outcome only (including phase 3's "update reported an error but
landed" case), after the completion record is `done` and before the thread reply:

1. **Who.** `info = slack.get_slack_user_info(slack_token, user)`. Name =
   `info["user"]["profile"]["display_name"]`, else `["real_name"]`, else
   `f"Slack user {user}"` when either is empty, `ok` is false, or the call raises
   (`requests.exceptions.RequestException`; log `logger.warning("Could not look up
   Slack user %s", user)`).
2. **When.** `_austin_datetime(now) -> str`: `f"{d:%a %b} {d.day}, {d.year}
   {d:%I:%M %p %Z}"` with the hour's leading zero dropped, e.g. `Mon Nov 16, 2026 3:04
   PM CST`.
3. **Link.** `slack.get_slack_post_url(os.environ.get("SLACK_WORKSPACE_URL"), channel,
   ts)`; when it returns `None` the comment has no link.
4. **Comment.** `Marked done from Slack by <name> on <when>.` followed by
   `\nReminder: <link>` when there is one. `clickup.create_task_comment(clickup_token,
   task_id, text)`; a `ValueError` → `logger.error("Could not comment on task %s",
   task_id)`, outcome stays `completed`. Success → `logger.info("Commented on task %s",
   task_id)`.

The name goes to ClickUp only. Never log it, or the comment text, or `info`.
`SLACK_WORKSPACE_URL` is optional (no link without it); it is not added to the
required list.

### infra: `templates/facilities.yaml`

`PMReminderReactionFunction` → `Environment.Variables`:

```yaml
          SLACK_WORKSPACE_URL: 'https://asmbly-makerspace.slack.com'
```

No IAM change (Slack and ClickUp tokens already granted). No deploy-role change.

### docs

- Function README, "What ClickUp shows": the status change, ClickUp's recurrence, and
  the comment (format, no notifications, not on duplicates or stale ✅s); the Slack
  scope it needs (`users:read`) and what happens without it (`Slack user U…`).
- `docs/README.md`, handler entry: "and adds a ClickUp comment naming who marked it done
  and when".

## Tests

`layers/common/tests/test_clickup.py`:

- `test_create_task_comment_posts_text_without_notifying`: method `POST`, URL ends
  `task/abc123/comment`, JSON `{"comment_text": "hi", "notify_all": false}`,
  `Authorization` header set.
- `test_create_task_comment_http_error_raises_safe_message`: a 401 with a body holding a
  marker → `ValueError`; the marker and token are not in the message or the log.

`functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`:

- `test_completion_adds_one_comment_with_name_time_and_link`: asserts the exact text
  (`Marked done from Slack by Jamie on Mon Nov 16, 2026 3:04 PM CST.\nReminder:
  https://asmbly-makerspace.slack.com/archives/C0CJAK1D725/p1763100000000100`) and one
  call (#165 criterion 1); `Jamie` is not in the logs.
- `test_comment_falls_back_to_real_name_then_user_id`: empty `display_name` → real
  name; `ok: false` or a raised `RequestException` → `Slack user U_REACTOR`.
- `test_duplicate_and_stale_add_no_comment` (#165 criterion 2), and
  `test_dry_run_adds_no_comment`.
- `test_comment_failure_keeps_completion`: `create_task_comment` raises → outcome
  `completed`, item `done`, the thread reply still sent, error logged with the task ID
  (#165 criterion 3).
- `test_comment_without_workspace_url_has_no_link`.

## Acceptance criteria

1. Each completion from Slack adds one comment: `Marked done from Slack by <display
   name> on <date, Austin time>.` with a link to the reminder (#165 criterion 1).
2. Duplicate or stale ✅s, and dry runs, add no comment (#165 criterion 2).
3. If the comment fails, the task is still completed and the failure is logged with the
   task ID (#165 criterion 3).
4. The display name is never logged.

## Verification

```bash
.venv/bin/python -m pytest layers/common/tests/test_clickup.py functions/facilities/pm_reminder_reaction
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

On prod after the first real ✅: the ClickUp task's activity shows one comment with the
person's Slack display name, the Austin time, and a link that opens the reminder.

## Admin actions

Confirm the Maintenance Bot has `users:read` (README admin action 3). Without it the
comment names the Slack user ID instead.

## Hand-off

_Filled in when the phase is done._ The plan is complete: `/write-docs` and the
integration gate check the docs and the whole flow.
