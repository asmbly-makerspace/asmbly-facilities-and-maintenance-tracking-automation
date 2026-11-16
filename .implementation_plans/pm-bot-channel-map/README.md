# PM bot channel map: implementation plan

**Created:** 2026-11-16

## Overview

The PM Reminder Bot (`PMReminderBotFunction`, weekly EventBridge schedule in
`templates/facilities.yaml`) posts each preventative-maintenance task to the Slack
channel named after the task's ClickUp **Workspace** value (`Woodshop` → `#woodshop`).
Facilities wants woodshop reminders in `#woodshop-maintenance` instead, and wants a
later channel rename to be a one-value change. This plan adds a
`workspace_channel_map` key to the PM bot's existing JSON configuration
(`configs/clickup_cmms_pmSchedule.json` → SSM `/${Stage}/clickup/cmms/pmSchedule`), and
the function uses it to send a workspace's reminders to the mapped channel.

## Stories

Legacy mode: no epic or story issues.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | Workspace channel map | lambda, infra, docs | S | [~] In progress |

## Dependencies

None. The SSM parameter, its IAM statement and its deploy-role entries already exist.

## Parallelism

One phase; nothing to run in parallel.

## Admin actions

- **Slack:** invite the Maintenance Bot (the app whose token is
  `slack-maintenancebot-token`) to `#woodshop-maintenance` before the first Saturday run
  after this reaches prod. Slack refuses `chat.postMessage` to a channel the bot isn't
  in (`not_in_channel`). Stage runs with `DRY_RUN=true` and posts nothing.
- No deploy-role redeploy: no new named resource.

## Related work

- Branch `fix/pm-bot-woodshop-maintenance-channel` has a first-pass draft that used a
  `WORKSPACE_CHANNEL_MAP` environment variable. The user chose the SSM configuration
  instead; phase 1 replaces the env var and reuses the draft's parsing and tests.
- No open issues touch the PM bot (`gh issue list --search "pm bot OR channel OR woodshop"`).

## Out of scope

- Changing the ClickUp Workspace field's options or other workspaces' channels.
- Editing the SSM parameter with the AWS CLI: the next deploy would overwrite it, and
  `CLAUDE.md` forbids AWS writes outside the deploy workflows.
- `STARTER_MESSAGE_TEXT`, `GENERAL_CHANNEL_NAME` and `WORKSPACES` are set but unused by
  the code, and the reaction emojis in the starter text aren't routed by the Slack event
  router for PM channels. Noted, not fixed here.

## Security

No new route, secret, IAM statement or resource. The map holds channel names only. The
function logs channel names and task IDs, never tokens or message bodies beyond what it
logs today.
