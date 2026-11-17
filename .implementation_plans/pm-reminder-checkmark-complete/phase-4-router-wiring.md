---
phase_id: 4
title: Route PM channel reactions to the handler
epic: 7
implements: [162, 163]
depends_on: [3]
domain: [lambda, infra, docs]
estimated_size: M
---

# Phase 4: Route PM channel reactions to the handler

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's `README.md` (Decisions 2, 4, 8; Related work on #79 and #92).
- `functions/routers/slack_event_subscriptions/lambda_function.py`, its tests and
  README.
- `templates/routers.yaml` and `RoutersStack` in `template.yaml` (how
  `PurchaseRequestReactionFunctionArn` reaches the router).
- `functions/facilities/pm_bot_reminder/README.md`, "Which Slack channel a reminder goes
  to".
- `tests/test_templates.py`, `test_slack_event_router_has_memory_for_its_three_second_deadline`.

**Sequencing check (before building).** Run `gh issue view 79`, `gh issue view 92` and
`gh pr list --search "79 OR 92 OR router" --state open`. If a pull request for either is
open, this phase is BLOCKED until it merges; then rebase on `stage` and re-check the
router's handler and `templates/routers.yaml` against this document (README Decision 2).
On 2026-11-16 neither had a branch or pull request.

## Goal

A ✅ (any reaction, in fact; the handler filters) in a channel listed in `pm_channels`
reaches `PMReminderReactionFunction-${Stage}` through the existing `/slack/events`
route, asynchronously. Purchase-request and problem-report reactions are routed exactly
as before. Adding or remapping a PM channel is a change to `configs/` only, and the PM
bot's README names every file to change.

## Files to create

None.

## Files to modify

- `functions/routers/slack_event_subscriptions/lambda_function.py`: the PM branch.
- `functions/routers/slack_event_subscriptions/tests/test_lambda_function.py`: tests.
- `functions/routers/slack_event_subscriptions/README.md`: configuration and flow.
- `templates/routers.yaml`: parameter, environment variable, invoke permission.
- `template.yaml`: pass the function ARN to `RoutersStack`.
- `tests/test_templates.py`: one seam test.
- `functions/facilities/pm_bot_reminder/README.md`: "Adding or remapping a PM channel".
- `functions/facilities/pm_reminder_reaction/README.md`: "How it's triggered" is now
  live.
- `docs/README.md`: the Slack Event Router entry.

## Implementation details

### lambda: the router

After the two existing channel checks, before `if not target_lambda_arn`:

```python
        pm_channels = router_config.get("pm_channels") or {}
        ...
        if channel_id == purchase_request_channel_id:
            target_lambda_arn = os.environ.get("PURCHASE_REQUEST_LAMBDA_ARN")
        elif channel_id == problem_report_channel_id:
            target_lambda_arn = os.environ.get("PROBLEM_REPORT_LAMBDA_ARN")
        elif isinstance(pm_channels, dict) and channel_id in pm_channels:
            target_lambda_arn = os.environ.get("PM_REMINDER_LAMBDA_ARN")
```

Nothing else changes: same single SSM read, same async `invoke` with the original
body, same 200 answers, same logging (event type, channel ID, retry number). No new
outside call inside the 3-second budget. Don't touch the parts #79 will rewrite (header
handling, logging) beyond this.

### infra: `templates/routers.yaml`

```yaml
Parameters:
  ...
  PMReminderReactionFunctionArn: { Type: String }
```

`SlackEventSubscriptionsRouterFunction` → `Environment.Variables`:

```yaml
          PM_REMINDER_LAMBDA_ARN: !Ref PMReminderReactionFunctionArn
```

and the `lambda:InvokeFunction` statement's `Resource` list gains
`- !Ref PMReminderReactionFunctionArn`. The SAM-generated role stays as it is (#92).

### infra: `template.yaml`

`RoutersStack` → `Parameters`:

```yaml
        PMReminderReactionFunctionArn: !GetAtt FacilitiesStack.Outputs.PMReminderReactionFunctionArn
```

No cycle: `FacilitiesStack` takes `RouterConfigParameter` (a root resource), not anything
from `RoutersStack`. No new named resource, so no deploy-role change.

### infra: seam test in `tests/test_templates.py`

`test_router_can_invoke_every_function_it_routes_to`: in `templates/routers.yaml`, every
environment variable of `SlackEventSubscriptionsRouterFunction` ending in `_LAMBDA_ARN`
is a `!Ref` to a parameter that also appears in the `lambda:InvokeFunction` statement's
`Resource`, and every such parameter is passed by `RoutersStack` in `template.yaml`.
This catches a target the router is told about but can't invoke (an `AccessDenied` only
visible in prod logs).

### docs

- Router README: the configuration example gains `pm_channels`; the flow and "Determine
  Target" step name the PM Reminder Reaction Handler as a third target; the environment
  variable list gains `PM_REMINDER_LAMBDA_ARN`.
- PM bot README, new subsection "Adding or remapping a PM channel" after "Which Slack
  channel a reminder goes to":
  1. `configs/clickup_cmms_pmSchedule.json` → `workspace_channel_map`, if the channel
     isn't named after its workspace (where the bot posts).
  2. `configs/router_config.json` → `pm_channels`, `"<channel ID>": "<channel name>"`
     (where ✅s are acted on). The channel ID is in Slack's channel details, at the
     bottom of the About tab.
  3. Invite the Maintenance Bot to the channel.
  `tests/test_configs.py` fails if a mapped channel is missing from `pm_channels`. No
  template change is needed.
  Also note that the starter text's `:loading:` line is not acted on (epic: out of
  scope).
- Handler README: triggered by the router for reactions in `pm_channels`; the router's
  log line `Invoking target Lambda: …PMReminderReactionFunction…` shows each forward.
- `docs/README.md`, Slack Event Router entry: "forwards reactions in the
  purchase-request channel, the problem-report channel and the PM channels
  (`pm_channels` in `configs/router_config.json`)". The route table is unchanged.

## Tests

`functions/routers/slack_event_subscriptions/tests/test_lambda_function.py` (add
`"pm_channels": {"C_PM": "woodshop-maintenance"}` to `fake_router_config` and
`PM_REMINDER_LAMBDA_ARN` to `env_vars`):

- `test_routes_to_pm_reminder_lambda`: a reaction in `C_PM` invokes
  `PM_REMINDER_LAMBDA_ARN` with `InvocationType='Event'` and the original body.
- `test_purchase_and_problem_routing_unchanged_with_pm_channels`: with `pm_channels`
  present, `C_PURCHASE` and `C_PROBLEM` still go to their functions (#162 criterion 6).
- `test_pm_channel_without_pm_lambda_arn_takes_no_action`: env var missing → "No action
  taken", no invoke.
- `test_missing_pm_channels_key_routes_nothing_new`: config without `pm_channels` →
  `C_PM` takes no action.
- `test_non_dict_pm_channels_is_ignored`: `pm_channels: ["C_PM"]` → no action, no
  exception.
- The existing tests still pass unchanged (their config has no `pm_channels`).

`tests/test_templates.py`: `test_router_can_invoke_every_function_it_routes_to`.

## Acceptance criteria

1. A reaction in any channel in `pm_channels` is forwarded asynchronously to
   `PMReminderReactionFunction-${Stage}` (#162 criterion 1, with phases 2–3).
2. Purchase-request and problem-report reactions are routed as before, and their
   handlers are untouched (#162 criterion 6).
3. Adding or remapping a PM channel changes only `configs/`, and the PM bot README names
   every file (#162 criterion 5).
4. No new path in `FacilitiesApi`; the route table in `docs/README.md` is unchanged
   (#163 criterion 7).
5. The router's role can invoke the new function and nothing new besides.

## Verification

```bash
.venv/bin/python -m pytest functions/routers tests/test_templates.py tests/test_configs.py
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

On stage after deploy: invoke `facilities-slack-event-router-stage` by hand with an API
Gateway-shaped event whose body is a `reaction_added` ✅ in `C0CJAK1D725` on a current
reminder. The router's log shows `Invoking target Lambda:
…PMReminderReactionFunction-stage`, and the handler's log shows `Dry run: would
complete task <id>`. A ✅ in the purchase-request channel still goes to
`PurchaseRequest-ReactionFunction-stage`. (Slack sends real events to the prod URL only.)

On prod, after the merge to `main`: add ✅ to a current reminder in
`#woodshop-maintenance`; within a minute the ClickUp task shows "to do" with its next
due date (README admin action 5).

## Admin actions

README admin actions 2 and 3 must be done before this reaches prod: confirmed IDs for
all 7 channels in `pm_channels`, and the Maintenance Bot in each channel with the
history scopes. No deploy-role change in this phase.

## Hand-off

_Filled in when the phase is done._ Phase 5 relies on: live events reaching the
handler; the router unchanged otherwise. #79 and #92 rebase on this phase's router and
`templates/routers.yaml`.
