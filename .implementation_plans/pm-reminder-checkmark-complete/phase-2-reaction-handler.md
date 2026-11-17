---
phase_id: 2
title: PM reminder reaction handler
epic: 7
implements: [162, 163]
depends_on: [1]
domain: [lambda, infra, docs]
estimated_size: L
---

# Phase 2: PM reminder reaction handler

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's `README.md` (Security, Decisions 3, 5, 7, 9).
- The closest example of new code: `functions/networking/dynamic_dns_update/lambda_function.py`
  (lazy logging, typed helpers, plain messages to the caller).
- The handler this mirrors: `functions/purchase_request/slack_reaction_webhook/lambda_function.py`
  (the router passes the Slack body as the event; `_log_received_event` logs IDs only).
- The reminder format: `functions/facilities/pm_bot_reminder/lambda_function.py`,
  `format_slack_message` and `PMTask`. Reminders are posted with the Maintenance Bot's
  token, username `PM Bot`.
- Helpers: `common/aws.py` (`get_secret`, `get_json_parameter`), `common/clickup.py`
  (`get_task`, `update_task`; both raise `ValueError` with a safe message on failure),
  `common/slack.py` (phase 1's `get_bot_id`, `get_channel_message`,
  `SlackRequestError`).
- Infra to copy: `PMReminderBotLambdaRole`, `PMReminderBotLogGroup` and
  `PMReminderBotFunction` in `templates/facilities.yaml`; the deploy-role lists in
  `template-cicd.yaml`; `tests/test_templates.py`
  (`test_each_lambda_role_writes_only_to_its_functions_log_group`).
- ClickUp API v2: Get Task (`list.id`, `status.status`, `status.type`, `due_date`,
  `date_done`, `date_closed`) and Update Task (`status`).

## Goal

A new function, `PMReminderReactionFunction-${Stage}`, takes a Slack `reaction_added`
body (as the router will pass it), and when the ✅ is on a real PM Bot reminder in a PM
channel for a task in the PM Schedule list, sets that task's status to
`complete_status`. Every other input is ignored with a log line and no ClickUp call.
On stage (`DRY_RUN=true`) it logs the task it would complete and writes nothing. Nothing
invokes it yet: the router is wired in phase 4, after phase 3 makes completion
once-only.

## Files to create

- `functions/facilities/pm_reminder_reaction/__init__.py` (empty)
- `functions/facilities/pm_reminder_reaction/lambda_function.py`
- `functions/facilities/pm_reminder_reaction/README.md`
- `functions/facilities/pm_reminder_reaction/tests/__init__.py` (empty)
- `functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`
- `functions/facilities/pm_reminder_reaction/tests/fixtures/reaction_added_event.json`:
  a router-forwarded body: `{"token": "VERIFICATION_TOKEN_SECRET", "type":
  "event_callback", "event_id": "Ev1", "event": {"type": "reaction_added", "user":
  "U_REACTOR", "reaction": "white_check_mark", "item": {"type": "message", "channel":
  "C0CJAK1D725", "ts": "1763100000.000100"}}}`
- `functions/facilities/pm_reminder_reaction/tests/fixtures/reminder_message.json`: a
  `conversations.history` message: `ts` as above, `bot_id: "B_PM"`, `username: "PM
  Bot"`, the text `[OVERDUE] woodshop - Downdraft Table - Check Downdraft Filters -
  Frequency: Every 3 weeks - ClickUp ID: 86a8eb482` (the literal pre-launch format), and
  `reactions: [{"name": "white_check_mark", "users": ["U_REACTOR"], "count": 1}]`.
- `functions/facilities/pm_reminder_reaction/tests/fixtures/clickup_task.json`: a Get
  Task answer: `id: "86a8eb482"`, `list: {"id": "901310894771"}`, `status: {"status":
  "to do", "type": "open"}`, `due_date: "1762300800000"`.

## Files to modify

- `templates/facilities.yaml`: new parameter, role, log group, function, output.
- `template.yaml`: pass `RouterConfigParameterName` to `FacilitiesStack`.
- `template-cicd.yaml`: function and log group names in `GitHubDeployPolicystage` and
  `GitHubDeployPolicyprod`.
- `docs/README.md`: a "PM Reminder Reaction Handler" entry under Facilities &
  Maintenance.

## Implementation details

### lambda: `functions/facilities/pm_reminder_reaction/lambda_function.py`

Module level: `logger = logging.getLogger(); logger.setLevel(logging.INFO)`;
`CHECKMARK = "white_check_mark"`; `CLOSED_STATUS_TYPES = frozenset({"closed",
"done"})`; `_bot_id: str | None = None` (cached per container).

```python
REMINDER_PATTERN = re.compile(r"\[[A-Z]+\] .+ - ClickUp ID: ([A-Za-z0-9]+)\s*", re.DOTALL)

def parse_reminder_task_id(text: str) -> str | None:
    """The ClickUp task ID from a PM Bot reminder's text, or None if it isn't one (fullmatch)."""

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
```

Every return is `_result(status_code, outcome)` →
`{"statusCode": status_code, "body": json.dumps({"result": outcome})}`. The function
is invoked asynchronously, so the answer reaches no one; the outcome is for tests and
logs. The handler never raises: an unexpected exception is caught at the top,
`logger.exception("Unexpected error handling event %s", event_id)`, and answered
`_result(500, "error")`. (Lambda retries a raised async invocation twice; Decision 7.)

Flow, in order:

1. **Log the event's IDs** (`type`, `reaction`, `item.channel`, `item.ts`, `event_id`,
   `user`) like `_log_received_event` in the purchase-request handler. Never the body
   (it holds Slack's verification token).
2. **Environment.** Required: `CLICKUP_SECRET_NAME`,
   `SLACK_MAINTENANCE_BOT_SECRET_NAME`, `CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME`,
   `ROUTER_CONFIG_PARAMETER_NAME`. Any missing: `logger.error("Missing environment
   variables: %s", ", ".join(names))` and `_result(500, "misconfigured")`.
   `DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"`, read inside the
   handler so tests can set it.
3. **Cheap checks, no outside calls.** Ignored (`_result(200, "ignored")`, one
   `logger.info("Ignored event %s: %s", event_id, reason)`) when: `event.type !=
   "reaction_added"`; `reaction != "white_check_mark"`; `item.type != "message"`; or
   `channel`, `ts` or `user` is missing or not a string.
4. **PM channel.** `pm_channels = get_json_parameter(ROUTER_CONFIG_PARAMETER_NAME).get("pm_channels")
   or {}`. Channel not a key: `logger.info("Ignored event %s: channel %s is not a PM
   channel", event_id, channel)` → ignored. No secret is fetched and no ClickUp call
   made.
5. **Secrets.** `get_secret(SLACK_..., "SLACK_MAINTENANCE_BOT_TOKEN")`,
   `get_secret(CLICKUP_..., "CLICKUP_API_TOKEN")`.
6. **The message, from Slack.** `bot_id` = cached `get_bot_id(slack_token)`;
   `message = get_channel_message(slack_token, channel, ts)`. Ignored (with the reason
   logged) when: `message is None` (thread reply or no such message); `message.get("bot_id")
   != bot_id` (a person's message or another bot's); `message.get("thread_ts")` is set
   and differs from `ts`; no entry in `message.get("reactions", [])` has `name ==
   "white_check_mark"` and `user in users` (forged or not yet visible; Decision 9);
   `parse_reminder_task_id(message.get("text", ""))` is `None`. A `SlackRequestError`:
   `logger.error("Could not read reminder %s in %s for event %s", ts, channel,
   event_id)` → `_result(200, "failed")`.
7. **PM schedule config.** `pm_config = get_json_parameter(CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME)`;
   `list_id = pm_config.get("list_id")`, `complete_status =
   pm_config.get("complete_status")`. Either missing: `logger.error(...)` →
   `_result(500, "misconfigured")`.
8. **The task, from ClickUp.** `task = clickup.get_task(clickup_token, task_id)`.
   `ValueError`: `logger.error("Could not read task %s for event %s", task_id,
   event_id)` → `_result(200, "failed")`. Ignored when `task["list"]["id"] !=
   list_id` (logged with the task ID). When `task["status"]["type"]` is in
   `CLOSED_STATUS_TYPES`: `logger.info("Task %s is already closed", task_id)` →
   `_result(200, "already_closed")`.
9. **Dry run.** `logger.info("Dry run: would complete task %s from reminder %s in %s
   for user %s", task_id, ts, channel, user)` → `_result(200, "would_complete")`.
10. **Complete.** `clickup.update_task(clickup_token, task_id, {"status":
    complete_status})`. `ValueError`: `logger.error("Could not complete task %s for
    event %s", task_id, event_id)` → `_result(200, "failed")`, task unchanged. Success:
    `logger.info("Completed task %s from reminder %s in %s for user %s", task_id, ts,
    channel, user)` → `_result(200, "completed")`.

Patch points for tests: the module imports `from common import aws, clickup, slack` and
calls `aws.get_secret`, `aws.get_json_parameter`, `clickup.get_task`,
`clickup.update_task`, `slack.get_bot_id`, `slack.get_channel_message`, so tests patch
`functions.facilities.pm_reminder_reaction.lambda_function.{aws,clickup,slack}`.
Reset `_bot_id` to `None` in each test.

Logged: IDs only (event ID, channel ID, `ts`, task ID, Slack user ID), outcome and
reason. Never message text, tokens or the event body.

### infra: `templates/facilities.yaml`

New parameter:

```yaml
  RouterConfigParameterName: { Type: String }
```

New resources (after the PM Reminder Bot block):

```yaml
  # --- Facilities: PM reminder ✅ reactions ---
  PMReminderReactionLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/asmbly/lambda/PMReminderReactionFunction-${Stage}"
      RetentionInDays: 14
      Tags:
        - Key: Project
          Value: facilities:pm-reminder-reaction

  PMReminderReactionLambdaRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service:
                - lambda.amazonaws.com
            Action:
              - sts:AssumeRole
      Policies:
        - PolicyName: PMReminderReactionPolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: !GetAtt PMReminderReactionLogGroup.Arn
              - Effect: Allow
                Action: secretsmanager:GetSecretValue
                Resource:
                  - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:clickup/api/token-*'
                  - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:slack-maintenancebot-token-*'
              - Effect: Allow
                Action: ssm:GetParameter
                Resource:
                  - !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${RouterConfigParameterName}'
                  - !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${Stage}/clickup/cmms/pmSchedule'
      Tags:
        - Key: Project
          Value: facilities:pm-reminder-reaction

  PMReminderReactionFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub "PMReminderReactionFunction-${Stage}"
      Description: "Completes a PM Schedule task in ClickUp when someone adds a white check mark to its PM Bot reminder in Slack (invoked by the Slack event router)."
      CodeUri: ../functions/facilities/pm_reminder_reaction/
      Handler: lambda_function.lambda_handler
      Runtime: python3.12
      # Two Slack calls and two ClickUp calls, each with an 8-second timeout.
      Timeout: 30
      Role: !GetAtt PMReminderReactionLambdaRole.Arn
      LoggingConfig:
        LogGroup: !Ref PMReminderReactionLogGroup
      Layers:
        - !Ref RequestsLayerARN
        - !Ref CommonLayerARN
      Environment:
        Variables:
          DRY_RUN: !If [IsProd, 'false', 'true']
          CLICKUP_SECRET_NAME: 'clickup/api/token'
          SLACK_MAINTENANCE_BOT_SECRET_NAME: 'slack-maintenancebot-token'
          CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME: !Ref ClickUpPMScheduleParameter
          ROUTER_CONFIG_PARAMETER_NAME: !Ref RouterConfigParameterName
      Tags:
        Project: facilities:pm-reminder-reaction
```

New output:

```yaml
  PMReminderReactionFunctionArn:
    Description: "The ARN of the PM Reminder Reaction Lambda Function"
    Value: !GetAtt PMReminderReactionFunction.Arn
```

The role has no `RoleName`, so CloudFormation names it after the nested stack, under the
deploy role's existing `AsmblyFacilitiesMaintTrac*` prefix (like
`PMReminderBotLambdaRole`). No `EventInvokeConfig` (Decision 7).

### infra: `template.yaml`

In `FacilitiesStack` → `Parameters`, add:

```yaml
        RouterConfigParameterName: !Ref RouterConfigParameter
```

### infra: `template-cicd.yaml`

In `GitHubDeployPolicystage`, statement `AllowLambdaFunctionManagement` → `Resource`,
after the `PMReminderBotFunction-stage` line:

```yaml
              - !Sub "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:PMReminderReactionFunction-stage"
```

and in `AllowCloudWatchLogsManagement` → `Resource`:

```yaml
              - !Sub "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/asmbly/lambda/PMReminderReactionFunction-stage*"
```

The same two lines with `-prod` in `GitHubDeployPolicyprod`. Both policies are about
4,200 characters today; two lines add about 200, well under the 5,800 budget
`tests/test_templates.py` enforces. No new SSM parameter, rule or table in this phase.

### docs

- `functions/facilities/pm_reminder_reaction/README.md`: purpose; how it's triggered
  (async invoke by the Slack Event Router, wired in phase 4; until then only by hand);
  the checks in order and that each failed check is ignored with a log line; what
  "complete" means (`complete_status` in `configs/clickup_cmms_pmSchedule.json`;
  ClickUp's recurrence, configured in ClickUp, brings the task back); environment
  variables (table: name, value, purpose); IAM; the log group
  `/asmbly/lambda/PMReminderReactionFunction-<stage>` and the log lines to look for
  (`Completed task`, `Ignored event`, `Could not`); `DRY_RUN` on stage; how to test it
  by hand on stage (below); that the reminder format is tested against the PM bot's
  formatter.
- `docs/README.md`, Facilities & Maintenance, after the PM Reminder Bot:

  ```markdown
  * **PM Reminder Reaction Handler** (`PMReminderReactionFunction`)
      * **What it does:** When someone adds :white_check_mark: to a PM Bot reminder in a PM channel, sets that task to "complete" in the ClickUp PM Schedule list; ClickUp's recurrence brings it back at its next due date. Any other reaction or message is ignored. Stage is a dry run.
      * **How it's triggered:** Asynchronously invoked by the **Slack Event Router** for reactions in the channels listed in `pm_channels` in `configs/router_config.json`.
      * **Config Location:** `configs/router_config.json` (`pm_channels`) and `configs/clickup_cmms_pmSchedule.json` (`list_id`, `complete_status`).
  ```

  Until phase 4 the router doesn't send it events; phase 4 checks this entry is true.
  The route table is unchanged.

## Tests

`functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`, all
with `aws`, `clickup` and `slack` patched where used:

- `test_parses_reminder_built_by_pm_bot_formatter`: builds text with
  `functions.facilities.pm_bot_reminder.lambda_function.format_slack_message(PMTask(...))`
  for an overdue and an upcoming task (with spaces and dashes in the asset and task
  names); `parse_reminder_task_id` returns each task ID. A format change in the bot
  fails this (#162 criterion 3).
- `test_parses_pre_launch_reminder_text`: the fixture's literal text returns
  `86a8eb482`.
- `test_rejects_text_that_only_quotes_an_id`: `"see ClickUp ID: 86a8eb482"` and a
  reminder line followed by extra prose return `None`.
- `test_checkmark_on_reminder_completes_task`: happy path. Asserts `update_task` was
  called once with `(clickup_token, "86a8eb482", {"status": "complete"})`, outcome
  `completed`, and the log has the task ID and `U_REACTOR` but not the message text or
  `VERIFICATION_TOKEN_SECRET`.
- `test_other_reaction_is_ignored_without_calls`: `reaction: "eyes"` → `ignored`;
  `get_json_parameter`, `get_secret`, Slack and ClickUp mocks not called.
- `test_reaction_removed_is_ignored_without_calls`: `type: "reaction_removed"`.
- `test_unlisted_channel_is_ignored_and_logs_channel`: channel not in `pm_channels` →
  `ignored`; log contains the channel ID; no secret fetched, no ClickUp call.
- `test_thread_reply_is_ignored`: `get_channel_message` returns `None` → `ignored`, no
  ClickUp call.
- `test_person_message_with_id_is_ignored`: message without `bot_id` (a `user` field)
  and reminder-like text → `ignored`.
- `test_other_bot_message_is_ignored`: `bot_id: "B_OTHER"` → `ignored`.
- `test_message_without_users_checkmark_is_ignored`: no `reactions`, and a
  `white_check_mark` reaction by another user → `ignored` (forged event).
- `test_non_reminder_bot_message_is_ignored`: a Maintenance Bot message without the
  reminder format → `ignored`.
- `test_task_in_another_list_is_ignored`: `list.id` differs → `ignored`, no
  `update_task`.
- `test_closed_task_is_not_updated`: `status.type: "closed"` → `already_closed`.
- `test_dry_run_logs_and_changes_nothing`: `DRY_RUN=true` → `would_complete`; log
  names the task; `update_task` not called (#162 criterion 7).
- `test_slack_error_is_logged_and_nothing_changes`: `get_channel_message` raises
  `SlackRequestError` → `failed`; no ClickUp call.
- `test_clickup_read_error_is_logged_with_task_id`: `get_task` raises `ValueError` →
  `failed`; log has the task ID.
- `test_clickup_update_error_is_logged_with_task_id`: `update_task` raises → `failed`;
  log has the task ID; no exception text beyond the helper's safe message.
- `test_missing_env_var_answers_500`: each required variable removed in turn →
  `misconfigured`, 500, no outside calls.
- `test_missing_complete_status_answers_500`.
- `test_unexpected_exception_is_caught`: `get_secret` raises `RuntimeError("SECRET")` →
  500 `error`; `"SECRET"` not in the response body.
- `test_bot_id_is_cached`: two invocations call `get_bot_id` once.

`tests/test_templates.py` needs no new test: the existing role, log-group and secret-ARN
tests cover the new role. Run them.

## Acceptance criteria

1. A `reaction_added` ✅ body for a PM Bot reminder in a `pm_channels` channel, whose task
   is in the PM Schedule list, calls `update_task` with `{"status": "complete"}` once,
   and the log records the task ID and the Slack user ID (#162 criterion 1).
2. The handler's tests build reminder text with the PM bot's own formatter and parse it,
   and parse a literal pre-launch reminder (#162 criterion 3).
3. Another reaction, a removed reaction, or an unlisted channel makes no ClickUp call;
   the unlisted case logs the channel ID (#162 criterion 4).
4. With `DRY_RUN=true` the handler logs the task it would complete and makes no
   `update_task` call (#162 criterion 7).
5. A ✅ on a thread reply, a person's message quoting an ID, or another bot's message
   changes nothing (#163 criterion 3).
6. A task ID not in the PM Schedule list changes nothing (#163 criterion 4).
7. An event whose channel and `ts` aren't a PM Bot reminder carrying the user's ✅
   changes nothing (#163 criterion 5).
8. A ClickUp error leaves the task unchanged and logs the task ID (#163 criterion 6,
   first half; the retry half is phase 3).
9. `PMReminderReactionFunction-${Stage}` exists with log group
   `/asmbly/lambda/PMReminderReactionFunction-${Stage}` (14 days), an explicit role
   whose logs grant is that log group only, `ssm:GetParameter` on exactly the router
   config and PM schedule parameters, and `GetSecretValue` on exactly the two secrets.
10. Both deploy-role policies list the function and its log group for their stage.
11. No new API route.

## Verification

```bash
.venv/bin/python -m pytest functions/facilities/pm_reminder_reaction tests/test_templates.py
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

On stage after deploy (the deploy role redeployed first): invoke
`PMReminderReactionFunction-stage` by hand with the fixture body, using the channel ID
and `ts` of a real current PM reminder (copy the message link in Slack: the `p…` part
is the `ts` without its dot) and the user ID of someone who has ✅ on it. The log group
`/asmbly/lambda/PMReminderReactionFunction-stage` shows `Dry run: would complete task
<id>`; the task in ClickUp is unchanged. With `reaction` set to `eyes`, the log shows
`Ignored event`.

## Admin actions

Redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` (docs/Deploying.md, "How to Manage
the Deployer Role") before this reaches `stage` (README admin action 1).

## Hand-off

_Filled in when the phase is done._ Phase 3 relies on: the handler's flow and outcome
names (`ignored`, `already_closed`, `would_complete`, `completed`, `failed`,
`misconfigured`, `error`); `parse_reminder_task_id`; the role
`PMReminderReactionLambdaRole` and function `PMReminderReactionFunction` in
`templates/facilities.yaml`; the test fixtures. Phase 4 relies on the output
`PMReminderReactionFunctionArn` of `FacilitiesStack`.
