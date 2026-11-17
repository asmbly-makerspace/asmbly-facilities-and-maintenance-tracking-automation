# PM Reminder Reaction Handler

`PMReminderReactionFunction-<stage>` (`templates/facilities.yaml`)

## Table of Contents
- [Purpose](#purpose)
- [How it is triggered](#how-it-is-triggered)
- [What it checks, in order](#what-it-checks-in-order)
- [Outcomes](#outcomes)
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
reactions in the channels listed in `pm_channels` in `configs/router_config.json`. That
routing is added in phase 4 of the `pm-reminder-checkmark-complete` plan; until then
nothing invokes the function except a manual test.

It has no URL of its own.

## What it checks, in order

Each failed check ends the run with an `Ignored event` log line and changes nothing,
except check 8, which logs `Task <id> is already closed`. A Slack or ClickUp failure logs
`Could not ...` instead.

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

Then it sets the task's status to `complete_status`.

## Outcomes

The function is invoked asynchronously, so its answer reaches no one. The outcome is in
the log and in the answer's `result`:

| Result | Meaning |
| --- | --- |
| `completed` | The task was set to `complete_status`. |
| `would_complete` | Stage (`DRY_RUN=true`): every check passed, nothing was written. |
| `already_closed` | The task is already closed in ClickUp. |
| `ignored` | A check failed; the log line says which. |
| `failed` | Slack or ClickUp failed. After a failed update the task's state is unknown: a timed-out request may still have been applied. |
| `misconfigured` | An environment variable, `list_id` or `complete_status` is missing (HTTP 500). |
| `error` | An unexpected error, logged with its traceback (HTTP 500). |

It never raises, so an error doesn't make Lambda retry it. A run that hits the 90-second
timeout is retried by Lambda (up to twice), and a retry after an update that ClickUp
already applied would complete the task again; phase 3's completion claim makes that
retry harmless. If a ✅ seems to do nothing (Slack or ClickUp was down, or rate-limited),
remove the ✅ and add it again.

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
| `DRY_RUN` | `true` on stage, `false` on prod | On stage, log what would be completed and write nothing. Only the exact value `false` writes to ClickUp; unset or anything else is a dry run. |

## AWS infrastructure

- **Role** `PMReminderReactionLambdaRole`: writes logs to its own log group only;
  `ssm:GetParameter` on the two parameters above; `secretsmanager:GetSecretValue` on the
  two secrets above.
- **Log group** `/asmbly/lambda/PMReminderReactionFunction-<stage>`, kept 14 days.
- **Timeout** 90 seconds: up to four Slack and ClickUp calls, each with an 8-second
  connect and an 8-second read timeout (64 seconds at worst), plus SSM and Secrets
  Manager.
- **Output** `PMReminderReactionFunctionArn` of the Facilities stack, used by the router.

The Maintenance Bot needs `channels:history` (and `groups:history` for a private
channel) and must be a member of each PM channel.

## Logs

The log lines to look for:

- `Completed task <id> from reminder <ts> in <channel> for user <user>`
- `Dry run: would complete task <id> ...` (stage)
- `Ignored event '<event_id>': <reason>`
- `Could not read reminder ...`, `Could not read task ...`, `Could not complete task ...`
- `Task <id> is already closed`
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
3. With AWS access, in the Lambda console test the stage function `PMReminderReactionFunction-stage` with
   `tests/fixtures/reaction_added_event.json`, after setting `channel`, `ts` and `user`.
4. The log group `/asmbly/lambda/PMReminderReactionFunction-stage` shows
   `Dry run: would complete task <id>`. With `reaction` set to `eyes` it shows
   `Ignored event`.
