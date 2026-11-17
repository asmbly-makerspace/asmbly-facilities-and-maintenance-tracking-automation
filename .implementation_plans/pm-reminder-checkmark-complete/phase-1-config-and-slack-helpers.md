---
phase_id: 1
title: PM channel config and Slack message helpers
epic: 7
implements: []
depends_on: []
domain: [layer, infra]
estimated_size: S
---

# Phase 1: PM channel config and Slack message helpers

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`, and this plan's `README.md` (Decisions 4, 9 and 12).
- `layers/common/python/common/slack.py`: `send_slack_message`, `get_slack_user_info`,
  `_slack_error_for_log` (copy its error-code logging), `DEFAULT_TIMEOUT_SECONDS`.
- `layers/common/tests/test_slack.py`: how `requests` is patched
  (`@patch('common.slack.requests.post')`, a `MagicMock` session).
- `configs/router_config.json` and `configs/clickup_cmms_pmSchedule.json`, and how
  `template.yaml` (`RouterConfigParameter`) and `templates/facilities.yaml`
  (`ClickUpPMScheduleParameter`) turn them into SSM parameters with `AWS::Include`.
- `functions/facilities/pm_bot_reminder/tests/test_pm_bot_reminder_lambda_function.py`,
  `test_pm_schedule_config_channel_map_is_valid`: the pattern for testing a committed
  config file.
- Slack API: `auth.test` (https://docs.slack.dev/reference/methods/auth.test) and
  `conversations.history` (https://docs.slack.dev/reference/methods/conversations.history),
  in particular `oldest`, `latest`, `inclusive` and the `reactions` field of a message.

## Goal

The common layer can fetch exactly one top-level Slack message by channel and `ts`, and
the bot's own `bot_id`, with errors logged by code only. The router configuration lists
the PM channels by ID, and the PM schedule configuration names the ClickUp status that
means "done". Nothing reads the new keys yet; the router ignores unknown keys, so this
phase changes no behavior.

## Files to create

- `tests/test_configs.py`: tests of the committed `configs/router_config.json` and its
  agreement with `configs/clickup_cmms_pmSchedule.json`.

## Files to modify

- `layers/common/python/common/slack.py`: add `SlackRequestError`, `get_bot_id`,
  `get_channel_message`.
- `layers/common/tests/test_slack.py`: tests for the two helpers.
- `configs/router_config.json`: add `pm_channels`.
- `configs/clickup_cmms_pmSchedule.json`: add `complete_status`.

## Implementation details

### layer: `common/slack.py`

```python
class SlackRequestError(Exception):
    """A Slack Web API call failed. The message holds the method and Slack's error code only."""


def get_bot_id(token: str) -> str:
    """Returns the bot_id of the app that owns `token` (auth.test). Raises SlackRequestError."""


def get_channel_message(token: str, channel_id: str, ts: str) -> dict[str, Any] | None:
    """
    Returns the top-level message at exactly `ts` in `channel_id`, or None when there is
    none (a thread reply, a deleted message, a wrong ts). Raises SlackRequestError when
    Slack can't be reached or answers ok=false.
    """
```

- Both use `requests.get("https://slack.com/api/<method>", headers={"Authorization":
  f"Bearer {token}"}, params=..., timeout=DEFAULT_TIMEOUT_SECONDS)`.
- `get_channel_message` sends `channel=channel_id, latest=ts, oldest=ts,
  inclusive="true", limit=1`. It returns `messages[0]` only if `messages[0]["ts"] ==
  ts`; otherwise `None`. `conversations.history` never returns thread replies, so a ✅ on
  a reply (for example the PM bot's description reply) gets `None`; comparing the `ts`
  is what #166 says the old processor lacks.
- `get_bot_id` returns `response["bot_id"]`; a missing `bot_id` (a user token) raises
  `SlackRequestError("auth.test returned no bot_id")`.
- Errors: a `requests.exceptions.RequestException` is logged as
  `logger.error("Slack %s failed: %s", method, type(e).__name__)` and raised as
  `SlackRequestError(f"Slack {method} failed ({type(e).__name__})") from None`. An
  `ok: false` answer is logged with `_slack_error_for_log(data)` and raised the same
  way. Never log the token, the URL with parameters, or the response body.
- Type hints on both, lazy logging, no `print`. Leave the older helpers in the file as
  they are.

### infra: configuration

`configs/router_config.json` becomes:

```json
{
  "purchase_request_channel_id": "C026YVA7TK3",
  "problem_report_channel_id": "C063LH7MB45",
  "pm_channels": {
    "C0CJAK1D725": "woodshop-maintenance"
  }
}
```

Add every other PM channel (`3d-printing`, `ceramics`, `electronics`, `lasers`,
`metal-shop`, `textiles`) whose ID can be confirmed read-only: the Slack web UI's
channel details, a read-only Slack `conversations.list` through an available Slack
tool, or an earlier document in this repository. Don't guess (README Decision 12). List
every channel left out in the phase's hand-off and in the pull request's **Risk**
section; README admin action 2 covers them.

`configs/clickup_cmms_pmSchedule.json` becomes:

```json
{
  "list_id": "901310894771",
  "complete_status": "complete",
  "workspace_channel_map": {
    "woodshop": "woodshop-maintenance"
  }
}
```

No template change: both files are already SSM parameters
(`/${Stage}/config/router/slack-event-router` and `/${Stage}/clickup/cmms/pmSchedule`),
both already in both deploy-role data policies. The PM bot ignores the new key (it
reads `list_id` and `workspace_channel_map` only).

Update the descriptions only if they now mislead: `RouterConfigParameter`'s
description already says "including channel IDs"; leave it.

## Tests

`layers/common/tests/test_slack.py`:

- `test_get_bot_id_returns_bot_id`: `auth.test` answers `{"ok": true, "bot_id": "B1"}`;
  returns `"B1"`; the request carried `Authorization: Bearer <token>`.
- `test_get_bot_id_without_bot_id_raises`: `{"ok": true, "user_id": "U1"}` raises
  `SlackRequestError`.
- `test_get_bot_id_error_logs_code_only`: `{"ok": false, "error": "invalid_auth"}`
  raises; the log has `invalid_auth` and not the token.
- `test_get_channel_message_returns_exact_message`: asserts the params sent (`channel`,
  `latest`, `oldest`, `inclusive`, `limit=1`) and that the message is returned.
- `test_get_channel_message_other_ts_returns_none`: Slack returns a message with a
  different `ts` (the nearest earlier top-level message); returns `None`.
- `test_get_channel_message_no_messages_returns_none`.
- `test_get_channel_message_api_error_raises_and_logs_code_only`: `ok: false,
  error: "not_in_channel"`; raises `SlackRequestError`; the log names the method and
  code, not the token or channel history.
- `test_get_channel_message_timeout_raises`: `requests.exceptions.ReadTimeout` whose text
  holds a marker; raises `SlackRequestError`; the marker is not in the log or the
  exception text.

`tests/test_configs.py`:

- `test_router_config_pm_channels_are_valid`: `pm_channels` is a non-empty dict; every
  key matches `^[CG][A-Z0-9]{8,}$`; every value is a Slack channel name
  (`[a-z0-9][a-z0-9_-]{0,79}`); no key equals `purchase_request_channel_id` or
  `problem_report_channel_id`.
- `test_every_mapped_pm_channel_is_routed`: every value of `workspace_channel_map` in
  `configs/clickup_cmms_pmSchedule.json` is a value in `pm_channels`, so a remapped
  channel can't silently stop completing tasks.
- `test_pm_schedule_config_names_a_complete_status`: `complete_status` is a non-empty
  string.

## Acceptance criteria

1. `common.slack.get_channel_message` returns a message only when its `ts` equals the
   requested `ts` (supports #163: "A ✅ on the description thread reply ... changes
   nothing").
2. `common.slack.get_bot_id` returns the token's `bot_id`.
3. Neither helper logs or raises with a token, a URL with parameters, or a response
   body.
4. `configs/router_config.json` has `pm_channels` with `C0CJAK1D725:
   woodshop-maintenance` and every other PM channel ID that could be confirmed.
5. `configs/clickup_cmms_pmSchedule.json` has `complete_status: "complete"`.
6. The router's behavior is unchanged: its tests pass without modification.

## Verification

```bash
.venv/bin/python -m pytest layers/common/tests/test_slack.py tests/test_configs.py
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

(`cfn-lint`, `sam validate` and `sam build` because the configs are pulled into
templates with `AWS::Include` and the layer changes.)

On stage after deploy: the SSM parameter `/stage/config/router/slack-event-router`
contains `pm_channels` (read-only `aws ssm get-parameter`). Reactions in the
purchase-request and problem-report channels behave as before.

## Admin actions

None for this phase. Channel IDs it can't confirm feed README admin action 2.

## Hand-off

_Filled in when the phase is done._ Phase 2 relies on: `common.slack.get_bot_id`,
`common.slack.get_channel_message`, `common.slack.SlackRequestError`; config keys
`pm_channels` (router config) and `complete_status`, `list_id` (PM schedule config); the
list of PM channels whose IDs are still missing.
