# PM Reminder Reaction Handler

`PMReminderReactionFunction-<stage>` (`templates/facilities.yaml`)

## Table of Contents
- [Purpose](#purpose)
- [How it is triggered](#how-it-is-triggered)
- [What it checks, in order](#what-it-checks-in-order)
- [Completed once](#completed-once)
- [Outcomes](#outcomes)
- [What the person sees](#what-the-person-sees)
- [Configuration](#configuration)
- [AWS infrastructure](#aws-infrastructure)
- [Logs](#logs)
- [Testing](#testing)

## Purpose

Every Saturday the [PM Reminder Bot](../pm_bot_reminder/README.md) posts each overdue or
upcoming preventative-maintenance task to its workspace's Slack channel, as
`[OVERDUE] woodshop - <asset> - <task> - Frequency: <f> - ClickUp ID: <id>`. Its starter
message tells people to mark a task done with `:white_check_mark:`.

This function makes that work: when someone adds `:white_check_mark:` (exactly that
emoji; `:heavy_check_mark:` and `:ballot_box_with_check:` are ignored) to a PM Bot
reminder, it sets the task to "complete" in the ClickUp PM Schedule list. ClickUp's own
recurrence, configured on each task in ClickUp, then brings the task back as "to do" with
its next due date.

## How it is triggered

The **Slack Event Router** (`functions/routers/slack_event_subscriptions/`) invokes it
asynchronously (`InvocationType='Event'`) with the Slack `reaction_added` body, for
reactions in the channels listed in `pm_channels` in `configs/router_config.json`. The
router forwards every reaction in those channels; this function drops everything but a
✅ before any outside call. Each forward shows in the router's log group
(`/asmbly/lambda/facilities-slack-event-router-<stage>`) as `Invoking target Lambda:
…PMReminderReactionFunction-<stage>`.

If a ✅ seems to do nothing, check the router's log first: a reaction in a channel
missing from `pm_channels` shows as `No target function determined`, a missing target
as `PM_REMINDER_LAMBDA_ARN environment variable not set`, and a failed forward as
`An unexpected error occurred` (the router still answers Slack with 200, so
Slack doesn't retry). Then check this function's log.

If many ✅s land at once (someone clearing a backlog), Slack may rate-limit the reminder
lookups and some end as `Could not read reminder ...`. Remove that ✅ and add it again.

It has no URL of its own.

## What it checks, in order

Each failed check ends the run with an `Ignored event` log line and changes nothing,
except checks 8 to 10, which end as `already_closed`, `stale` or `duplicate` (see
[Outcomes](#outcomes)). A Slack, ClickUp or DynamoDB failure logs `Could not ...` instead.

1. The event is a `reaction_added` of `white_check_mark` on a message, with a well-formed
   channel ID, message `ts` and user ID. No outside call is made before this passes.
2. The channel is a key of `pm_channels` in the router's SSM parameter. No secret is read
   and no Slack or ClickUp call is made for any other channel.
3. Slack returns a top-level message at exactly that `ts` (`conversations.history`), so a
   reaction on the task description in the reminder's thread is ignored.
4. The message was posted by the Maintenance Bot itself (its `bot_id`, from `auth.test`,
   cached per container), not by a person or another bot.
5. The message carries a `:white_check_mark:` from the event's user. This stops a forged
   event (the router's URL doesn't check its caller yet, #79) from completing a task
   nobody ticked. If Slack shortens the list of users on a busy message, a ✅ with a
   larger count than the list is accepted.
6. The text is a PM Bot reminder, and the ClickUp ID is read from it.
7. ClickUp says the task is in the PM Schedule list (`list_id`).
8. The task isn't already closed (status type `closed` or `done`).
9. ClickUp's `date_done` or `date_closed` isn't later than the reminder (if it is, the
   task was completed after the reminder was posted: `stale`). This is best effort:
   ClickUp may return these as empty on a reopened recurring task, so the claim in
   check 10 is what stops a second completion from Slack. For a task completed by hand
   in ClickUp, this check is the only guard against a ✅ on the older reminder; if it
   names the reminder that completed the task (a second ✅), the answer is `duplicate`.
10. The task can be claimed in the completions table (see [Completed once](#completed-once)).

Then it sets the task's status to `complete_status`.

## Completed once

A task is completed once per reminder cycle. The table `PMReminderCompletions-<stage>`
(`templates/facilities.yaml`) holds one item per task, `pk = task#<task id>`:

| Attribute | Meaning |
| --- | --- |
| `state` | `pending` while a completion is in flight, `done` after it |
| `claim_id` | The invocation holding a `pending` claim (removed when `done`) |
| `claimed_at` | When the claim was made (epoch seconds) |
| `reminder_ts`, `channel` | The reminder that was (or is being) ticked |
| `due_before` | The task's ClickUp due date before the update (`""` if none) |
| `completed_at` | When the task was last completed (epoch seconds). A `pending` item keeps the previous completion's time until it is `done`. |

Before it calls ClickUp, the function claims the item with a conditional write. The claim
succeeds only when there is no item, the last completion is older than this reminder, or
a `pending` claim is more than 5 minutes old (`CLAIM_EXPIRY_SECONDS`, over three times
the 90-second timeout, so it belongs to a dead invocation) and any completion recorded
before it is older than this reminder. So:

- **A second ✅ on the same reminder, or the same event twice:** the item is `pending` or
  `done` for this reminder: `duplicate`, no ClickUp call. The due date moves one cycle.
- **A Lambda retry after a timeout:** the first arrives about 1 minute later and finds
  the `pending` claim (if the timed-out run got that far): `duplicate`. If the timed-out
  update didn't land, the task stays open until a ✅ is added again after 5 minutes.
- **Last week's reminder after this week's was ticked:** the completion is newer than the
  reminder: `stale`, no ClickUp call.
- **This week's reminder after last week's completion:** the claim succeeds.
- **ClickUp fails:** the function re-reads the task. If the update landed anyway (the
  task is closed, has `complete_status`, or its due date moved), it is recorded as
  `completed`. Otherwise the claim stays `pending` (a timed-out request can still land a
  moment later) and expires after 5 minutes. The next ✅ after that takes the claim over,
  and if the due date has moved since the claim, the earlier update landed: `duplicate`
  for the same reminder, `stale` for an older one, and a new completion for a reminder
  posted after that claim.

If a second person adds a ✅ while the first one's update is in flight and that update
then fails, the second ✅ is not retried; adding it again after 5 minutes works.

The takeover reads "the due date moved since the claim" as "the earlier update landed".
If someone changes the due date by hand while a failed claim sits expired, the next ✅ on
that reminder is recorded as done without completing the task; the next reminder
completes it as usual.

To clear a record by hand, an admin deletes the `task#<id>` item from the table. Reading
it is safe: `aws dynamodb get-item --table-name PMReminderCompletions-prod --key
'{"pk":{"S":"task#<id>"}}'`.

## Outcomes

The function is invoked asynchronously, so its answer reaches no one. The outcome is in
the log and in the answer's `result` (with `completed_at`, the last completion in epoch seconds, on
`duplicate` and `stale` when it is known):

| Result | Meaning |
| --- | --- |
| `completed` | The task was set to `complete_status`. |
| `would_complete` | Stage (`DRY_RUN=true`): every check passed, nothing was written. |
| `duplicate` | This reminder already completed the task, or another invocation is completing it. |
| `stale` | The task was completed after this reminder was posted. |
| `already_closed` | The task is already closed in ClickUp. |
| `ignored` | A check failed; the log line says which. |
| `failed` | Slack, ClickUp or DynamoDB failed. After a failed update the claim stays `pending` for 5 minutes. |
| `misconfigured` | An environment variable, `list_id` or `complete_status` is missing (HTTP 500). |
| `error` | An unexpected error, logged with its traceback (HTTP 500). |

It never raises, so an error doesn't make Lambda retry it. A run that hits the 90-second
timeout is retried by Lambda (up to twice); the first retry finds the completion claim
and answers `duplicate`, and a later one takes the claim over only after checking
whether the earlier update landed. If a ✅ seems to do nothing (Slack or ClickUp was down, or rate-limited),
remove the ✅ and add it again. If that still does nothing, wait 5 minutes (a claim left
`pending` by a failed update expires then) and try once more.

## What the person sees

The PM Bot replies in the reminder's thread (never as a new channel message), under the
name and icon in `BOT_NAME` and `BOT_ICON_EMOJI`. Dates are Austin (Central) dates, such
as `Wed Nov 25`.

| Outcome | Reply in the thread |
| --- | --- |
| `completed`, the task recurred | `Marked done in ClickUp. Next due <date>` |
| `completed`, the task closed and the reminder's `Frequency:` is `N/A` | `Marked done in ClickUp. This task doesn't repeat, so it's now closed.` |
| `completed`, anything else (closed although it has a frequency, or unclear) | `Marked done in ClickUp.` |
| `stale`, or `already_closed` when the completion record doesn't name this reminder (including a task closed by hand in ClickUp) | `Already marked done on <date>; nothing changed.` (without a known date: `Already marked done in ClickUp; nothing changed.`) |
| `failed`, after the message was confirmed as a PM reminder | `Couldn't mark this done in ClickUp. Try again later. Wait 5 minutes, then remove and add the :white_check_mark: again.` |
| `ignored`, `duplicate`, `misconfigured`, `error`, `would_complete`, a Slack read failure | No reply |

How the next due date is found: if ClickUp's answer to the update shows the task open with
a later due date, that is the next due date. Otherwise the function waits 2 seconds and
reads the task again. A task closed on that re-read gets the "doesn't repeat" reply only
when its reminder has no frequency; a closed task that has one may simply not have been
reopened yet, so it gets the plain reply (and a warning in the log). `Frequency:` is the
ClickUp custom field, not ClickUp's own recurrence setting: a recurring task with the field
unset that ClickUp hasn't reopened within 2 seconds would wrongly get "doesn't repeat".
Check this on the first prod ✅ of such a task.

Once only:

- **Completed:** the completion is recorded before the reply, so a reply problem can't
  complete the task twice. A second ✅ or a repeated event is a `duplicate`, with no
  reply. The completion also writes the reminder's `reply#<channel>#<ts>` marker, so a
  later ✅ on it that turns out stale adds no "Already marked done" under the "Marked done".
- **Already marked done:** one reply per reminder, however many times it is ticked. A
  marker item `reply#<channel>#<ts>` is written first (kept 60 days through the table's
  TTL); the reply is sent only if the marker was new.
- **Failure:** one reply per Slack event, through a marker `reply#failed#<event_id>`. If
  the marker can't be written (DynamoDB is what failed), the reply is sent anyway. An
  event without a well-formed `event_id` (`Ev` and up to 32 letters or digits) gets no
  failure reply. This limits, but doesn't prevent, forged failure replies: until the
  router checks Slack's signature (#79), a forged event with a fresh ID on a real ✅'d
  reminder still gets one while ClickUp or DynamoDB is failing.

A reply that fails (the bot isn't in the channel, Slack is down) is logged and changes
nothing. Known limits: because the marker is written before the reply, a failed post
means that reminder never gets its "Already marked done" or failure reply; an update that
reports an error but lands later is answered with the failure text, and re-adding the ✅
after that is a silent `duplicate`, so the thread's last word stays "Couldn't mark this
done" although ClickUp shows the task done; a run that times out after recording the
completion sends no reply (the retry is a silent duplicate); a date that can't be
formatted is left out of the reply; and a permanent ClickUp failure (a deleted task, a
revoked token) still gets "Try again later".

On stage (`DRY_RUN=true`) nothing is posted and no marker is written. For `stale`,
`already_closed` and `failed` the log shows `Dry run: would reply <outcome> to <ts>`; the
usual stage result, `would_complete`, logs no reply line (stage never completes, so it
never reaches the "Marked done" reply).

## Configuration

The JSON files in `configs/` are copied into AWS Systems Manager (SSM) Parameter Store
parameters at deploy time; the function reads those parameters, so a change to a file
takes effect on the next deploy.

| Where | Key | Purpose |
| --- | --- | --- |
| `configs/router_config.json` | `pm_channels` | `{channel_id: channel_name}` of the PM channels. Also used by the router. |
| `configs/clickup_cmms_pmSchedule.json` | `list_id` | The ClickUp PM Schedule list. A task in any other list is ignored. |
| `configs/clickup_cmms_pmSchedule.json` | `complete_status` | The status that marks a task done (`complete`). It must be a closed status of that list. |

### Environment variables

| Name | Value | Purpose |
| --- | --- | --- |
| `CLICKUP_SECRET_NAME` | `clickup/api/token` | Secret holding `CLICKUP_API_TOKEN`. |
| `SLACK_MAINTENANCE_BOT_SECRET_NAME` | `slack-maintenancebot-token` | Secret holding `SLACK_MAINTENANCE_BOT_TOKEN`. |
| `CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME` | `/<stage>/clickup/cmms/pmSchedule` | SSM parameter built from `configs/clickup_cmms_pmSchedule.json`. |
| `ROUTER_CONFIG_PARAMETER_NAME` | `/<stage>/config/router/slack-event-router` | SSM parameter built from `configs/router_config.json`. |
| `PM_COMPLETIONS_TABLE_NAME` | `PMReminderCompletions-<stage>` | The completions table. |
| `BOT_NAME` | `PM Bot` | The name the thread replies are posted under (default `PM Bot`). |
| `BOT_ICON_EMOJI` | `:hammer_and_wrench:` | The icon of the thread replies (default `:hammer_and_wrench:`). |
| `DRY_RUN` | `true` on stage, `false` on prod | On stage, log what would be completed and write nothing, to ClickUp or the table (it reads the table to report `duplicate` or `stale`). Only the exact value `false` writes; unset or anything else is a dry run. |

## AWS infrastructure

- **Role** `PMReminderReactionLambdaRole`: writes logs to its own log group only;
  `ssm:GetParameter` on the two parameters above; `secretsmanager:GetSecretValue` on the
  two secrets above; `dynamodb:GetItem`, `PutItem` (reply markers) and `UpdateItem` on
  the completions table.
- **Table** `PMReminderCompletions-<stage>`, pay per request, TTL on `expires_at`. It
  holds one `task#<id>` item per task and the short-lived `reply#…` markers.
- **Log group** `/asmbly/lambda/PMReminderReactionFunction-<stage>`, kept 14 days.
- **Timeout** 90 seconds. The worst case of every Slack, ClickUp and DynamoDB timeout
  added up is longer than that; a run cut off by the timeout leaves a `pending` claim,
  which the retry and takeover rules above handle.
- **Output** `PMReminderReactionFunctionArn` of the Facilities stack, used by the router.

The Maintenance Bot needs `channels:history` (and `groups:history` for a private
channel), `chat:write` and `chat:write.customize` (the replies use the PM Bot's name and
icon, as its reminders do), and must be a member of each PM channel.

## Logs

The log lines to look for:

- `Completed task <id> from reminder <ts> in <channel> for user <user>`
- `Dry run: would complete task <id> ...` (stage)
- `Ignored event '<event_id>': <reason>`
- `Could not read reminder ...`, `Could not read task ...`, `Could not complete task ...`
- `Task <id> is already closed`
- `Task <id>: duplicate for reminder <ts>`, `Task <id>: stale for reminder <ts>`
- `Reminder <ts> for task <id> is older than its last completion (date_done)`
- `Task <id> keeps its pending claim for up to 300 seconds` (after a failed update)
- `Task <id> was completed although the update reported an error`
- `Could not record completion of task <id>: <DynamoDB error code>`, `Could not record
  task <id> as done: ...`, `Could not read the completion record of task <id>: ...`,
  `Could not read the record that blocked the claim on task <id>`
- `The claim on task <id> was written but its response was lost` (an error; `failed`)
- `Could not re-read task <id> after its update failed`
- `Task <id>: an earlier claim landed before reminder <ts> was posted`
- `The claim on task <id> expired before it was recorded as done`
- `Task <id>: an earlier update landed but could not be recorded; check the record`
- `Dry run: task <id>: <duplicate or stale> for reminder <ts>` (stage)
- `Replied <outcome> for task <id> in the thread of <ts> in <channel>` (only when Slack
  accepted the reply)
- `Dry run: would reply <outcome> to <ts>` (stage; `stale`, `already_closed` or `failed` only)
- `Could not reply in the thread of <ts> in <channel>` (the reply failed; the outcome stands)
- `Could not write reply marker <pk>: <DynamoDB error code>`, `Reminder <ts> in <channel>
  already got an already-done reply`, `Event '<event_id>' already got a failure reply`
- `Task <id>: could not tell whether it recurred`, `Task <id>: closed after completion
  although its frequency says it repeats`, `Could not re-read task <id> after completing it`
- `No failure reply for reminder <ts>: the event has no usable event ID`
- `Could not turn timestamp <value> into a date` (the reply leaves the date out)
- `Could not reply for event ...` (with a traceback): the reply step failed unexpectedly;
  the outcome stands.
- `Missing environment variables: ...` and `PM schedule config is missing list_id or
  complete_status` (`misconfigured`)
- `Unexpected error handling event ...` (with a traceback): an AWS call (SSM, Secrets
  Manager) or anything else unexpected failed.

Only IDs are logged (event ID, channel ID, message `ts`, task ID, Slack user ID): never the
message text, a token, the event body or a person's name.

## Testing

```bash
.venv/bin/python -m pytest functions/facilities/pm_reminder_reaction
```

The tests build reminder text with the PM Bot's own `format_slack_message` and parse it,
so a change to the reminder format fails these tests instead of silently breaking
completion. They also parse a literal reminder posted before this function existed.

### By hand on stage

Stage is a dry run, so the stage function changes nothing in ClickUp. But Slack sends
reaction events to the prod router: once PM channels are routed in prod, the ✅ you add
in step 2 completes the task for real. Use a reminder for work that is actually done,
or add the ✅ and test before prod routing is live.

1. In Slack, copy the link of a current PM reminder. The `p…` part of the link is the
   message `ts` without its dot (`p1763100000000100` is `1763100000.000100`).
2. Add a ✅ to it yourself, and find your Slack user ID (profile → ⋯ → Copy member ID).
   The event's `user` must be the person whose ✅ is on that message; any other user ID
   ends as `Ignored event` (the ✅ check), not a dry run.
3. With AWS access, in the Lambda console test the stage function `PMReminderReactionFunction-stage` with
   `tests/fixtures/reaction_added_event.json`, after setting `channel`, `ts` and `user`.
4. The log group `/asmbly/lambda/PMReminderReactionFunction-stage` shows
   `Dry run: would complete task <id>`. With `reaction` set to `eyes` it shows
   `Ignored event`. The stage table stays empty.
5. To test the route through the router as well (its environment variable and invoke
   permission), test the stage router `facilities-slack-event-router-stage` instead,
   with an API Gateway-shaped event: `{"body": "<the same event, as a JSON string>"}`.
   The router's log group `/asmbly/lambda/facilities-slack-event-router-stage` shows
   `Invoking target Lambda: …PMReminderReactionFunction-stage`, and the handler's log
   shows the same `Dry run` line. A person with AWS access runs these tests; they invoke
   functions, so they aren't read-only.

### On the first prod ✅

Stage never writes to the table, so `duplicate` and `stale` first run for real on prod.
On the first prod ✅, add a second ✅ from another account to the same reminder and
check the log: one `Completed task` line and one `duplicate` line, and the task's due
date in ClickUp moved one cycle. Also check that the reopened task's `date_done` and
`date_closed` are not later than its next reminder; if ClickUp stamps them on reopening,
every later ✅ would be `stale`. This check is required before relying on the feature.

In Slack, the reminder's thread should hold exactly one `Marked done in ClickUp. Next due
<date>` reply (the PM Bot's own description reply may be there too), with the date matching the task's new due date in ClickUp; the second
✅ adds nothing. A ✅ on last week's reminder for the same task gets `Already marked done
on <date>; nothing changed.` once.
