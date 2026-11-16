# Phase 1: Workspace channel map

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md` ("Rules", "Done means verified").
- `functions/facilities/pm_bot_reminder/lambda_function.py` and
  `functions/facilities/pm_bot_reminder/tests/test_pm_bot_reminder_lambda_function.py`.
- `layers/common/python/common/aws.py` (`get_json_parameter`: with no `expected_key` it
  returns the whole parsed object).
- `templates/facilities.yaml`: `ClickUpPMScheduleParameter` (built from
  `configs/clickup_cmms_pmSchedule.json`), `PMReminderBotLambdaRole` (already allows
  `ssm:GetParameter` on `/${Stage}/clickup/cmms/pmSchedule`), `PMReminderBotFunction`.
- The draft commit on `fix/pm-bot-woodshop-maintenance-channel` (env-var version); its
  `parse_channel_map` and tests are the starting point.

## Goal

A PM task whose Workspace is `Woodshop` posts to `#woodshop-maintenance`; every other
workspace posts to the channel derived from its name, as today. The mapping lives in
`configs/clickup_cmms_pmSchedule.json` under `workspace_channel_map`, so renaming a
channel later means editing that one value.

## Files to create

None.

## Files to modify

- `configs/clickup_cmms_pmSchedule.json`: add
  `"workspace_channel_map": {"woodshop": "woodshop-maintenance"}`.
- `functions/facilities/pm_bot_reminder/lambda_function.py`: read the map from the
  existing SSM parameter; apply it in `process_tasks_for_slack`. Remove the draft's
  `WORKSPACE_CHANNEL_MAP` env var reading.
- `templates/facilities.yaml`: remove the draft's `WORKSPACE_CHANNEL_MAP` env var.
  Update `ClickUpPMScheduleParameter`'s `Description` to mention the channel map.
- `functions/facilities/pm_bot_reminder/tests/test_pm_bot_reminder_lambda_function.py`:
  tests below; update the handler test's SSM assertions.
- `functions/facilities/pm_bot_reminder/README.md`: "Which Slack channel a reminder goes
  to", pointing at the config file.
- `docs/README.md`: the PM Reminder Bot entry names the map and its file.

## Implementation details

### lambda

- `parse_channel_map(raw: Any) -> dict[str, str]`: takes the value of
  `workspace_channel_map` (already parsed JSON).
  - `None` (key absent) → `{}`, no log.
  - Not a `dict`, or any key or value not a non-empty `str` after `strip()` → log
    `logger.error("workspace_channel_map in the PM schedule config is invalid; posting to default channels")`
    and return `{}`. The weekly run still posts; a valid config is enforced in CI by
    `test_pm_schedule_config_channel_map_is_valid`.
  - Keys go through the same normalization as the derived channel name, in one shared
    helper `workspace_slug(name: str) -> str` (strip, lowercase, spaces → dashes), so
    `"Woodshop "` and `"Metal Shop"` match `woodshop` and `metal-shop`.
  - Values: stripped, leading `#` removed, then must match
    `^[a-z0-9][a-z0-9_-]{0,79}$` (a Slack channel name). Any value that fails makes the
    whole map invalid (error log, `{}`).
  - The signature changes from the draft's JSON string to the parsed value; drop the
    draft's `json.loads` branch.
- Handler: replace the `get_json_parameter(..., expected_key='list_id')` call with one
  call without `expected_key`: `pm_config = get_json_parameter(CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME)`.
  `list_id` missing → `KeyError` caught by the existing `except` → logged 500 with the
  existing plain body (same outcome as today). Then
  `channel_map = parse_channel_map(pm_config.get('workspace_channel_map'))`, and log
  `logger.info("Workspace channel map has %d entries", len(channel_map))`.
- `process_tasks_for_slack(tasks, workspace_field_id, asset_field_id, frequency_field_id, channel_map=None)`
  with type hints (as in the draft): after deriving `channel_name`, replace it with
  `channel_map.get(channel_name, channel_name)` for `ClickUpTask.channel` (the post
  target). Add `ClickUpTask`-independent workspace labelling: `format_slack_message` keeps
  the derived workspace name (e.g. `woodshop`) in the text so two workspaces mapped to one
  channel stay distinguishable. If `ClickUpTask` (in `common/clickup.py`) has no field for
  it, keep a parallel value in the function rather than changing the layer.
- No new environment variables. No change to `common/`.

### infra

- `configs/clickup_cmms_pmSchedule.json`:
  ```json
  {
    "list_id": "901310894771",
    "workspace_channel_map": {
      "woodshop": "woodshop-maintenance"
    }
  }
  ```
- `templates/facilities.yaml`: delete the `WORKSPACE_CHANNEL_MAP` line;
  `ClickUpPMScheduleParameter` `Description: "JSON configuration for the PM reminder bot: the ClickUp PM Schedule list ID and the workspace-to-Slack-channel map."`.
- IAM: none (the role already reads this parameter's exact ARN). Deploy role: none (the
  parameter name is unchanged and already in both Data policies).

### docs

- The draft already wrote these sections citing `WORKSPACE_CHANNEL_MAP`; rewrite them.
- Function README: the derivation rule, the map's file and key, an example, that the bot
  must be in the target channel, and what an invalid map does.
- `docs/README.md`: one sentence in the PM Reminder Bot entry.
- Function README also notes the rename hazards: renaming the Slack channel or the
  ClickUp Workspace option silently breaks the mapping until the config is updated.

## Tests

- `test_process_tasks_for_slack_maps_channel`: `Woodshop` → `woodshop-maintenance`,
  `Metal Shop` stays `metal-shop`; `unique_channels` holds the mapped names.
- `test_process_tasks_for_slack` (existing): with no map, `woodshop` is unchanged.
- `test_parse_channel_map` (parametrized): `None` → `{}`; `{}` → `{}`;
  `{"Woodshop ": " #woodshop-maintenance"}` → `{"woodshop": "woodshop-maintenance"}`;
  a list, a non-string value, and an empty-string value → `{}`.
- `test_parse_channel_map_invalid_logs_error`: an invalid map logs the error line at
  ERROR (caplog).
- `test_pm_schedule_config_channel_map_is_valid`: loads
  `configs/clickup_cmms_pmSchedule.json`, asserts `list_id` is present and
  `parse_channel_map` of its map equals the raw map with no error logged, so a typo fails
  CI instead of a Saturday run.
- **Stale mocks (fix in build):** `test_lambda_handler_no_tasks`,
  `test_lambda_handler_with_tasks`, `test_lambda_handler_logs_progress_at_info` and
  `test_lambda_handler_dry_run_mode` mock `get_json_parameter` so the PM config call
  returns a string. Change each so that call returns a dict with `list_id`
  (`test_lambda_handler_dry_run_mode` uses one `return_value` for both calls: switch it to
  `side_effect`).
- Delete the draft's `test_channel_map_read_from_environment` (the env var is gone).
- The draft's `test_process_tasks_for_slack_maps_channel` and `test_parse_channel_map`
  exist; rewrite them for the new signature and cases (including `"Metal Shop"` key,
  `"Woodshop-Maintenance"`, `"woodshop maintenance"` and `"#"` values → `{}`).
- `test_format_slack_message_keeps_workspace_label`: a mapped task's text still names
  `woodshop`.
- Handler test (existing, updated): `get_json_parameter` is called with the PM schedule
  parameter name and no `expected_key`; the mocked config includes
  `workspace_channel_map: {"woodshop": "woodshop-maintenance"}`, and the woodshop task's
  `send_slack_message` call has `channel_to_attempt == 'woodshop-maintenance'`.
- `test_lambda_handler_missing_list_id_returns_500`: config without `list_id` → 500 with
  the plain body, nothing sent to Slack.

## Acceptance criteria

1. With the committed config, a task with Workspace `Woodshop` is sent to
   `woodshop-maintenance`; a task with Workspace `Metal Shop` to `metal-shop`.
2. The map is read from `/${Stage}/clickup/cmms/pmSchedule`; the function has no
   `WORKSPACE_CHANNEL_MAP` environment variable.
3. An absent map changes nothing; an invalid map logs an error and posts to default
   channels.
4. `configs/clickup_cmms_pmSchedule.json` is checked by a test.
5. No new AWS resource, IAM statement or deploy-role entry.
6. The function README and `docs/README.md` say where the map is and how to change it.

## Verification

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

After the stage deploy (read-only): `aws ssm get-parameter --name /stage/clickup/cmms/pmSchedule --profile asmbly`
shows `workspace_channel_map`. The Saturday stage run (`DRY_RUN=true`) logs
`Would send to channel: woodshop-maintenance` for woodshop tasks in
`/asmbly/lambda/PMReminderBotFunction-stage`.

After the first prod run: search `/asmbly/lambda/PMReminderBotFunction-prod` for
`not_in_channel` / `channel_not_found`. Slack failures are logged, not raised, so the
run still returns 200 if the bot isn't in the channel.

Before build: confirm `#woodshop-maintenance`'s channel ID is not one of the router's
(`configs/router_config.json`), so PM posts don't reach a reaction processor.

## Admin actions

Invite the Maintenance Bot to `#woodshop-maintenance` before the first prod run.

## Hand-off

Filled in when the phase is done.
