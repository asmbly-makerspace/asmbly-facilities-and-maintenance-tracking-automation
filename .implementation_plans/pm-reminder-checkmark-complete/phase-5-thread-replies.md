---
phase_id: 5
title: Thread replies in Slack
epic: 7
implements: [164]
depends_on: [3]
domain: [lambda, docs]
estimated_size: M
---

# Phase 5: Thread replies in Slack

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's `README.md` (Decision 11).
- `functions/facilities/pm_reminder_reaction/lambda_function.py` after phase 3, and its
  outcomes.
- `common/slack.py`, `send_slack_message` (`thread_ts`, `dry_run`, returns
  `{"ok": False, ...}` instead of raising).
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py`: Austin time
  with `ZoneInfo("America/Chicago")`, and its `requirements.txt` (`tzdata`).
- `PMReminderBotFunction`'s `BOT_NAME` and `BOT_ICON_EMOJI` in `templates/facilities.yaml`.
- Story #164's acceptance criteria (exact reply texts).

## Goal

The person who added ✅ sees one short reply in the reminder's thread saying the task
was marked done (with its next due date, or that it doesn't repeat), that it was already
done, or that ClickUp failed. Ignored and duplicate cases get no reply. Stage replies
nothing.

## Files to create

- `functions/facilities/pm_reminder_reaction/requirements.txt`: `tzdata` (the Lambda
  image may lack the system time zone database; the kiln viewer does the same).

## Files to modify

- `functions/facilities/pm_reminder_reaction/lambda_function.py`
- `functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`
- `functions/facilities/pm_reminder_reaction/README.md`: "What the person sees".
- `templates/facilities.yaml`: two environment variables.
- `docs/README.md`: the handler's "What it does" mentions the thread reply.

## Implementation details

### lambda: replies

Reply texts, exactly as in #164:

| Outcome | Reply in the reminder's thread |
| --- | --- |
| `completed`, task recurs | `Marked done in ClickUp. Next due <date>` |
| `completed`, task doesn't recur | `Marked done in ClickUp. This task doesn't repeat, so it's now closed.` |
| `stale` (and `already_closed` for a different reminder) | `Already marked done on <date>; nothing changed.`, once per reminder |
| `failed` after the message was confirmed as a reminder | `Couldn't mark this done in ClickUp. Try again later.` |
| `ignored`, `duplicate`, `misconfigured`, `error`, any dry run | no reply |

`<date>` is an Austin date: `_austin_date(epoch_seconds: float) -> str` returns
`f"{d:%a %b} {d.day}"` for `d = datetime.fromtimestamp(epoch_seconds,
ZoneInfo("America/Chicago"))`, e.g. `Wed Nov 25`.

`_reply(slack_token: str, channel: str, ts: str, text: str) -> None` calls
`slack.send_slack_message(slack_token, channel, text, BOT_NAME, BOT_ICON_EMOJI,
thread_ts=ts)`. A response without `ok` is logged (`logger.warning("Could not reply in
the thread of %s in %s", ts, channel)`) and otherwise ignored: a reply failure never
changes the outcome. Never `reply_broadcast`, so the reply stays in the thread. In a dry
run, `_reply` is not called; log `logger.info("Dry run: would reply %s to %s", outcome,
ts)`.

New environment variables, read in the handler with defaults: `BOT_NAME` (default
`PM Bot`), `BOT_ICON_EMOJI` (default `:hammer_and_wrench:`).

**Next due date.** After a successful completion (phase 3's step 11), decide which
`completed` reply to send:

1. From `update_task`'s returned task: if `status.type` is not in
   `CLOSED_STATUS_TYPES` and `due_date` is later than `due_before`, the task recurred:
   next due = that `due_date`.
2. Otherwise wait 2 seconds (`time.sleep`, patched in tests) and `get_task` again:
   `status.type` in `CLOSED_STATUS_TYPES` → doesn't recur; open with a later `due_date`
   → next due = that date.
3. Still neither, or the read fails: reply `Marked done in ClickUp.` and log
   `logger.warning("Task %s: could not tell whether it recurred", task_id)`. (README
   admin action 5 checks the real behavior on the first prod ✅.)

The completion record is written before the reply, so a reply problem can't cause a
second completion.

**Already marked done, once per reminder.** For a `stale` outcome, write a marker before
replying: `PutItem` `{"pk": f"reply#{channel}#{ts}", "expires_at": now + 60 * 86400}`
with `ConditionExpression: attribute_not_exists(pk)`. Reply only if the put succeeds; a
`ConditionalCheckFailedException` means this reminder already got that reply (no reply,
log at info); any other `ClientError` is logged and no reply is sent. The date is the
record's `completed_at`, or, for the ClickUp-side check (phase 3 step 8a), the
`date_done`/`date_closed` that triggered it.

`already_closed` (phase 2 step 8, a non-recurring task already closed): read the
`task#<id>` record; if it is `done` with `reminder_ts == ts`, it is a duplicate (no
reply); otherwise treat it as `stale` with the date from the record's `completed_at` or
the task's `date_closed`, and use the marker as above.

**Failure reply, once per event.** Only after the message was confirmed as a PM Bot
reminder (a Slack read failure gets no reply: the handler doesn't know it's a
reminder). Write marker `reply#failed#<event_id>` (same TTL, same condition) and reply
if it succeeds; if the marker write fails for a reason other than the condition (for
example the table is the thing that failed), reply anyway. A redelivered failed event
then adds no second reply. Without an `event_id`, reply without a marker.

`_reply` and markers sit at the end of the flow, one place per outcome, so the outcome
returned is unchanged from phase 3.

Logged: outcome, task ID, channel ID, `ts`. The reply texts hold no personal data.

### infra: `templates/facilities.yaml`

`PMReminderReactionFunction` → `Environment.Variables`:

```yaml
          BOT_NAME: 'PM Bot'
          BOT_ICON_EMOJI: ':hammer_and_wrench:'
```

IAM (phase 3 hand-off): add `dynamodb:PutItem` on `PMReminderCompletionsTable` to `PMReminderReactionPolicy`; the Slack token is already granted. No
deploy-role change.

### docs

- Function README, "What the person sees": the reply table above, the once-only rules,
  and that stage replies nothing.
- `docs/README.md`, handler entry: add "and replies in the reminder's thread with the
  next due date, or why nothing changed".

## Tests

All with Slack patched (`slack.send_slack_message` asserting `thread_ts=ts` and the
channel), moto for the table, `time.sleep` patched.

- `test_completed_recurring_task_replies_next_due_date`: `update_task` returns an open
  task with a later `due_date` → one reply `Marked done in ClickUp. Next due Wed Nov
  25` (date chosen to test Austin vs UTC: a due time of 03:00 UTC is the previous day in
  Austin).
- `test_completed_task_recurrence_seen_on_reread`: `update_task` returns closed, the
  re-read is open with a later due date → next-due reply; `time.sleep(2)` called once.
- `test_completed_non_recurring_task_replies_closed`: closed on re-read → the "doesn't
  repeat" text.
- `test_unknown_recurrence_replies_plain_marked_done`: re-read unchanged (and re-read
  raising) → `Marked done in ClickUp.` and a warning with the task ID.
- `test_stale_reminder_replies_once`: two ✅s on an older reminder → exactly one
  `Already marked done on <date>; nothing changed.` reply; the marker exists with
  `expires_at`.
- `test_already_closed_task_on_other_reminder_replies_already_done`.
- `test_already_closed_task_on_same_reminder_is_silent`.
- `test_duplicate_checkmark_adds_no_reply`: the second ✅ on the completed reminder → no
  second reply (#164 criterion 5).
- `test_clickup_failure_replies_couldnt_mark` (update fails, task unchanged) and
  `test_clickup_read_failure_replies_couldnt_mark` (`get_task` fails): reply text exact,
  no error details; a redelivery of the same `event_id` adds no second reply.
- `test_slack_read_failure_replies_nothing`.
- `test_ignored_cases_reply_nothing`: other emoji, unlisted channel, thread reply,
  person's message, task in another list → `send_slack_message` never called (#164
  criterion 4).
- `test_reply_failure_keeps_outcome`: `send_slack_message` returns `{"ok": False}` →
  outcome still `completed`, item `done`, warning logged.
- `test_dry_run_replies_nothing`.
- `test_reply_uses_bot_name_and_icon_from_env`.

## Acceptance criteria

1. After a completion the bot replies once in the reminder's thread with the next due
   date (Austin) or the "doesn't repeat" text (#164 criterion 1).
2. A ✅ on an older reminder gets one `Already marked done on <date>; nothing changed.`
   reply, however many times it is ticked (#164 criterion 2).
3. A ClickUp failure gets `Couldn't mark this done in ClickUp. Try again later.` with no
   error details (#164 criterion 3).
4. Ignored cases get no reply (#164 criterion 4).
5. Replies are thread replies only; a duplicate event or a second ✅ on a completed
   reminder adds no reply (#164 criterion 5).
6. A failed reply never changes whether the task was completed.

## Verification

```bash
.venv/bin/python -m pytest functions/facilities/pm_reminder_reaction
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

(`sam build` because of the new `requirements.txt`.)

On stage: the hand invocation from phase 2 logs `Dry run: would reply completed to
<ts>` and posts nothing. On prod, after the first real ✅: one thread reply with the next
due date, matching ClickUp; a second ✅ adds nothing; a ✅ on last week's reminder gets
the "Already marked done" reply once.

## Admin actions

None (the Maintenance Bot already has `chat:write`; README admin action 3 confirms it).

## Hand-off

_Filled in when the phase is done._ Phase 6 relies on: the success path (completion
recorded, then reply) as the one place a comment is added; `_austin_date`; the
`BOT_NAME` environment pattern.
