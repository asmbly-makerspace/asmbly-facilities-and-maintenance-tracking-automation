---
plan: pm-reminder-checkmark-complete
epic: 7
---

# PM reminder ✅ completes the ClickUp task: implementation plan

**Created:** 2026-11-16

## Overview

The PM Reminder Bot (`PMReminderBotFunction`, `templates/facilities.yaml`) posts each
overdue or upcoming preventative-maintenance task from the ClickUp PM Schedule list to a
workspace channel every Saturday, as `[OVERDUE] woodshop - <asset> - <task> - Frequency:
<f> - ClickUp ID: <id>`. Its starter text tells people to mark tasks done with
`:white_check_mark:`, but nothing listens: the Slack Event Router
(`functions/routers/slack_event_subscriptions/`) only forwards reactions from the
purchase-request and problem-report channels. On 2026-11-16, 37 of the 46 PM tasks were
overdue.

This plan adds a new async handler, `PMReminderReactionFunction-${Stage}`
(`functions/facilities/pm_reminder_reaction/`), and routes ✅ reactions from the PM
channels to it. The handler checks that the reacted message really is a current PM Bot
reminder with a real ✅ on it, completes the task in ClickUp once per cycle (a DynamoDB
claim makes duplicates and old reminders harmless), replies in the reminder's thread, and
leaves a comment on the ClickUp task naming who ticked it. ClickUp's own recurrence
brings the task back at its next due date. No new public URL.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #162 | A ✅ on a PM reminder completes its ClickUp task | 2, 4 |
| #163 | Only a current PM reminder completes a task, and only once | 2, 3, 4 |
| #164 | The person sees in Slack whether the ✅ worked | 5 |
| #165 | ClickUp shows who marked a PM task done from Slack | 6 |

Only the pull request that lands the last phase in a row says `Closes #N`; inside
`/offshore` every phase lands in one pull request, which closes all four.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | PM channel config and Slack message helpers | layer, infra | S | [x] Complete |
| 2 | PM reminder reaction handler | lambda, infra, docs | L | [x] Complete |
| 3 | Complete once per cycle | lambda, infra, docs | M | [x] Complete |
| 4 | Route PM channel reactions to the handler | lambda, infra, docs | M | [x] Complete |
| 5 | Thread replies in Slack | lambda, docs | M | [x] Complete |
| 6 | ClickUp comment naming who ticked it | lambda, layer, infra, docs | S | [x] Complete |

## Dependencies

- **Phase order:** 2 needs 1 (helpers and config keys); 3 needs 2 (the handler); 4 needs
  3 (nothing is routed to the handler until it completes a task only once); 5 needs 3
  (the stale and duplicate outcomes it replies to); 6 needs 5 (same handler file and the
  same success path).
- **Outside this plan:** none of the phases needs a new secret. The existing secrets
  `clickup/api/token` (key `CLICKUP_API_TOKEN`) and `slack-maintenancebot-token` (key
  `SLACK_MAINTENANCE_BOT_TOKEN`) are reused. The Slack app already subscribes to
  `reaction_added` (the router receives it today).
- **#79 and #92 (router):** both open, neither started (no branch, no pull request on
  2026-11-16). Phase 4 is this plan's only router change and is kept small (one config
  key, one environment variable, one IAM resource, one `elif`). See Decisions.

## Parallelism

Every phase depends on the one before it except 5 (needs 3) and 6 (needs 5), so the only
pairs without a dependency path are 4–5 and 4–6.

| Pair | Verdict | Shared paths |
| --- | --- | --- |
| 4 and 5 | sequential-only | `docs/README.md`, `functions/facilities/pm_reminder_reaction/README.md` |
| 4 and 6 | sequential-only | `docs/README.md`, `functions/facilities/pm_reminder_reaction/README.md` |

Run the phases in order 1 → 6.

## Admin actions

1. **Before phase 2 reaches `stage`:** redeploy `AsmblyFacilitiesMaintTrackingStack-cicd`
   (docs/Deploying.md, "How to Manage the Deployer Role"). Phases 2 and 3 add
   `PMReminderReactionFunction-{stage,prod}`, its log groups, and the table
   `PMReminderCompletions-{stage,prod}`. The stage deploy fails without it.
2. **Before phase 4 reaches `prod`:** confirm the 7 PM channel IDs in
   `configs/router_config.json` → `pm_channels` (3d-printing, ceramics, electronics,
   lasers, metal-shop, textiles, woodshop-maintenance). Phase 1 fills every ID it can
   confirm read-only (`#woodshop-maintenance` is `C0CJAK1D725`); any channel it can't
   confirm is listed in the pull request's **Risk** section for an admin to supply.
3. **Before phase 4 reaches `prod`:** in the Slack app (Maintenance Bot), confirm the
   bot is a member of all 7 channels and has `channels:history` (and `groups:history` if
   any of them is private), `reactions:read`, `chat:write`, `chat:write.customize` (replies under the PM Bot's name
   and icon, as the reminders already do) and `users:read` (phase 6).
   Events and `conversations.history` only work in channels the bot is in.
4. **Before prod:** turn on recurrence for Clean Metal Shop Sink (`86a8be2bc`) in
   ClickUp (recurs on "complete", skip missed dates), as for the other PM tasks.
5. **On the first prod ✅:** confirm that the API v2 `PUT /task/{id}` status change to
   "complete" brings a recurring task back as "to do" with its next due date (the epic
   verified this through the ClickUp MCP, not v2). The thread reply from phase 5 shows
   the next due date; check it against the task in ClickUp.

## Related work

- **#79 Check who is calling each public route** (open, not started): its Slack
  signature check rewrites the router handler and `templates/routers.yaml`, which phase
  4 also changes. Sequenced: phase 4 lands first; #79 rebases on it.
- **#92 Scope the SAM-generated Lambda roles** (open, not started): replaces the router's
  SAM-generated role in `templates/routers.yaml`. Same sequencing as #79. The new
  function in phase 2 uses an explicit role scoped to its own log group, so it adds
  nothing to #92.
- **#166 Reaction handlers can act on the wrong message on a thread reply** (open): the
  same flaw would hit this handler; phase 1's `get_channel_message` checks the returned
  `ts`, and phase 2 uses it. #166 itself (in `common/reaction_processing.py`) stays out of
  scope.
- **Plan `pm-bot-channel-map`** (complete): added `workspace_channel_map` to
  `configs/clickup_cmms_pmSchedule.json`. Phase 1 adds keys to the same file.

## Out of scope

- `:loading:` → "in progress", and removing a ✅ (epic: only `:white_check_mark:`
  counts; removal does nothing).
- Backfill: ✅s added before launch don't fire.
- The Slack signature check (#79), the router's role (#92), and #166.
- Changing the reminder text format or the PM bot's posting logic.
- A role check on who may complete a task (epic: anyone who can react in a PM channel).
- Detecting a completion made directly in ClickUp: a ✅ on an older reminder after a
  ClickUp-side completion is caught only when ClickUp reports `date_done` or
  `date_closed` later than the reminder (phase 3).

## Security

- **No new public route.** The handler is invoked only by the router
  (`InvocationType='Event'`); the route table in `docs/README.md` is unchanged.
- **`/slack/events` still doesn't check its caller (#79).** A forged event can name any
  channel and timestamp. The handler acts only when Slack itself returns a top-level PM
  Bot message at that exact `ts`, in a configured PM channel, carrying a
  `:white_check_mark:` reaction from the event's user, whose ClickUp ID is a task in the
  PM Schedule list. A forged event can therefore only repeat what a real ✅ already did,
  and the phase 3 claim makes that a no-op.
- **IAM:** an explicit role per function, logs only to its own log group,
  `ssm:GetParameter` on the two exact parameter ARNs, `secretsmanager:GetSecretValue` on
  `secret:clickup/api/token-*` and `secret:slack-maintenancebot-token-*`, DynamoDB item
  actions on the one table. The router gets `lambda:InvokeFunction` on the new function
  only.
- **Logs:** IDs only (task ID, channel ID, message `ts`, Slack user ID, event ID). Never
  the message text, a token, the event body, or a person's name. The display name in the
  phase 6 ClickUp comment is sent to ClickUp, never logged.
- **Stage:** `DRY_RUN=true` outside prod. The stage function reads Slack and ClickUp but
  writes nothing to ClickUp, Slack or its table.

## Decisions

1. **#165 is built, as phase 6.** It needs one small ClickUp helper and existing Slack
   helpers (`get_slack_user_info`, `get_slack_post_url`), size S. Alternative: defer it.
   It fits easily, which is the epic's condition.
2. **Router sequencing with #79 and #92.** Both are open with no branch or pull request,
   so this plan goes first and its router change is a single small phase (4). Whoever
   builds #79 or #92 rebases on `stage` after this merges. If either has an open pull
   request when phase 4 is prepped, `/prep` marks phase 4 BLOCKED until that pull
   request merges, then phase 4 rebases on it. Alternative: wait for #79/#92 first; that
   would block a Must feature on unstarted work.
3. **A new function, not a third caller of `common.reaction_processing`.** The shared
   processor looks for a `https://app.clickup.com/t/<id>` link, which PM reminders don't
   have, doesn't compare the returned message's `ts` (#166), and doesn't check the
   author. Alternative: extend it; that would change the purchase-request and
   problem-report handlers, which #162 says must behave as today.
4. **PM channel IDs live in `configs/router_config.json` as `pm_channels`
   (`{channel_id: channel_name}`).** The router already reads that parameter, so routing
   costs no extra SSM call inside its 3-second budget; the handler re-checks against the
   same parameter. Names next to IDs let a test check that every channel in
   `workspace_channel_map` is routed. Alternative: a key in
   `configs/clickup_cmms_pmSchedule.json`, which would add a second SSM read to the
   router.
5. **The reminder format is tested against the PM bot's own formatter.** The handler's
   tests build reminder text with `functions.facilities.pm_bot_reminder.lambda_function.
   format_slack_message` and parse it, plus one literal pre-launch reminder string. A
   format change in the bot then fails the handler's tests. Alternative: move the format
   into the common layer; that changes the PM bot for no user-visible gain.
6. **Idempotency and staleness use a DynamoDB claim** (`PMReminderCompletions-${Stage}`,
   one item per task) with a conditional write, not ClickUp's task fields. ClickUp's
   recurrence reopens the same task, so its status and due date can't tell a duplicate
   from a new cycle (a weekly task completed late is due again within the reminder's
   7-day window). Alternative: read ClickUp `date_done`; kept only as an extra stale
   check because its behavior on reopened recurring tasks is unconfirmed.
7. **No `EventInvokeConfig` (async retries left at Lambda's default).** Setting
   `MaximumRetryAttempts` needs `lambda:PutFunctionEventInvokeConfig`, a new deploy-role
   action. The handler never raises, and the claim makes a retry after a timeout a
   no-op.
8. **The router routes PM channels by channel only, like the other two.** The handler
   drops every reaction other than `:white_check_mark:` before any outside call.
   Alternative: filter the emoji in the router; it saves a few cheap invocations at the
   cost of PM-specific logic in the router #79 is about to rewrite.
9. **The handler requires the ✅ to be on the message** (`reactions` in the
   `conversations.history` result includes `white_check_mark` with the event's user).
   This makes a forged event do nothing until #79 lands. If Slack's copy hasn't caught
   up, the person removes and re-adds the ✅.
10. **`implements` for phase 4 includes #163** for its "no new public URL" criterion,
    which phase 4 fully delivers by routing through the existing router. Phase 2
    includes #163 for the non-reminder, wrong-list and forged-event criteria.
11. **Thread replies are plain text, not Block Kit.** Each is one short sentence; Block
    Kit adds nothing. `send_slack_message` (existing helper) posts them with the PM
    Bot's name and icon.
12. **Unconfirmed channel IDs are left out, not guessed.** A missing ID means that
    channel's ✅s are ignored (logged with the channel ID), which is safe; a wrong ID
    could route another channel's reactions. Missing IDs become an admin action.
