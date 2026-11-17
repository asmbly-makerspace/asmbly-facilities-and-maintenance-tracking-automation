import copy
import json
import logging
import pathlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from common.slack import SlackRequestError
from functions.facilities.pm_bot_reminder.lambda_function import PMTask, format_slack_message
from functions.facilities.pm_reminder_reaction import lambda_function

MODULE = "functions.facilities.pm_reminder_reaction.lambda_function"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"

ENV = {
    "CLICKUP_SECRET_NAME": "clickup/api/token",
    "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
    "CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME": "/test/clickup/cmms/pmSchedule",
    "ROUTER_CONFIG_PARAMETER_NAME": "/test/config/router/slack-event-router",
    "DRY_RUN": "false",
}
ROUTER_CONFIG = {"pm_channels": {"C0CJAK1D725": "woodshop-maintenance"}}
PM_CONFIG = {"list_id": "901310894771", "complete_status": "complete"}
SECRETS = {"SLACK_MAINTENANCE_BOT_TOKEN": "xoxb-slack-token", "CLICKUP_API_TOKEN": "pk_clickup_token"}
TASK_ID = "86a8eb482"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _body(result: dict[str, Any]) -> str:
    return json.loads(result["body"])["result"]


class Mocks:
    def __init__(self, aws: MagicMock, clickup: MagicMock, slack: MagicMock) -> None:
        self.aws = aws
        self.clickup = clickup
        self.slack = slack
        self.message = _fixture("reminder_message.json")
        self.task = _fixture("clickup_task.json")
        self.router_config = copy.deepcopy(ROUTER_CONFIG)
        self.pm_config = copy.deepcopy(PM_CONFIG)
        aws.get_json_parameter.side_effect = self._parameter
        aws.get_secret.side_effect = lambda name, key: SECRETS[key]
        slack.get_bot_id.return_value = "B0PMBOT"
        slack.get_channel_message.side_effect = lambda token, channel, ts: self.message
        clickup.get_task.side_effect = lambda token, task_id: self.task
        clickup.update_task.side_effect = lambda token, task_id, payload: {"id": task_id}

    def _parameter(self, name: str) -> Any:
        return {
            ENV["ROUTER_CONFIG_PARAMETER_NAME"]: self.router_config,
            ENV["CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME"]: self.pm_config,
        }[name]

    def assert_no_outside_calls(self) -> None:
        self.aws.get_json_parameter.assert_not_called()
        self.aws.get_secret.assert_not_called()
        self.slack.get_bot_id.assert_not_called()
        self.slack.get_channel_message.assert_not_called()
        self.clickup.get_task.assert_not_called()
        self.clickup.update_task.assert_not_called()


@pytest.fixture
def mocks(monkeypatch: pytest.MonkeyPatch) -> Iterator[Mocks]:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(lambda_function, "_bot_id", None)
    with patch(f"{MODULE}.aws") as aws, patch(f"{MODULE}.clickup") as clickup, patch(f"{MODULE}.slack") as slack:
        yield Mocks(aws, clickup, slack)


@pytest.fixture
def event() -> dict[str, Any]:
    return _fixture("reaction_added_event.json")


def _pm_task(time_status: str, asset: str, name: str, task_id: str) -> PMTask:
    return PMTask(
        channel="woodshop-maintenance",
        asset_name=asset,
        frequency="Every 2 weeks",
        task_id=task_id,
        task_name=name,
        task_url=f"https://app.clickup.com/t/{task_id}",
        time_status=time_status,
        task_description=None,
        workspace="woodshop",
    )


# --- Reminder parsing ---

def test_parses_reminder_built_by_pm_bot_formatter() -> None:
    overdue = format_slack_message(_pm_task("overdue", "Table Saw - SawStop", "Clean - and oil", "86a8abc12"))
    upcoming = format_slack_message(_pm_task("upcoming", "Dust Collector 2", "Empty bin - top", "86a8def34"))
    assert overdue.startswith("[OVERDUE] ")
    assert upcoming.startswith("[UPCOMING] ")
    assert lambda_function.parse_reminder_task_id(overdue) == "86a8abc12"
    assert lambda_function.parse_reminder_task_id(upcoming) == "86a8def34"


def test_parses_pre_launch_reminder_text() -> None:
    text = _fixture("reminder_message.json")["text"]
    assert lambda_function.parse_reminder_task_id(text) == TASK_ID


@pytest.mark.parametrize(
    "text",
    [
        "see ClickUp ID: 86a8eb482",
        "[OVERDUE] woodshop - Downdraft Table - Check Downdraft Filters - Frequency: Every 3 weeks - "
        "ClickUp ID: 86a8eb482 and please also sweep",
        "[OVERDUE] woodshop - A - B - Frequency: Weekly - ClickUp ID: 86a8eb482\nthanks!",
        # A line break before the ID: the PM Bot posts one line, so this isn't its reminder.
        "[OVERDUE] woodshop - A\nB - Frequency: Weekly - ClickUp ID: 86a8eb482",
        "[OVERDUE] woodshop - A - B - Frequency: Weekly - ClickUp ID: N/A",
        "",
    ],
)
def test_rejects_text_that_only_quotes_an_id(text: str) -> None:
    assert lambda_function.parse_reminder_task_id(text) is None


# --- Happy path and dry run ---

def test_checkmark_on_reminder_completes_task(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    result = lambda_function.lambda_handler(event, None)

    assert result["statusCode"] == 200
    assert _body(result) == "completed"
    mocks.clickup.update_task.assert_called_once_with("pk_clickup_token", TASK_ID, {"status": "complete"})
    mocks.clickup.get_task.assert_called_once_with("pk_clickup_token", TASK_ID)
    assert sorted(c.args for c in mocks.aws.get_secret.call_args_list) == [
        ("clickup/api/token", "CLICKUP_API_TOKEN"),
        ("slack-maintenancebot-token", "SLACK_MAINTENANCE_BOT_TOKEN"),
    ]
    mocks.slack.get_channel_message.assert_called_once_with("xoxb-slack-token", "C0CJAK1D725", "1763100000.000100")
    assert TASK_ID in caplog.text
    assert "U0REACTOR" in caplog.text
    assert "Completed task" in caplog.text
    assert "Downdraft" not in caplog.text
    assert "VERIFICATION_TOKEN_SECRET" not in caplog.text
    assert "xoxb-slack-token" not in caplog.text
    assert "pk_clickup_token" not in caplog.text


def test_dry_run_logs_and_changes_nothing(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    caplog.set_level(logging.INFO)
    result = lambda_function.lambda_handler(event, None)

    assert _body(result) == "would_complete"
    assert f"Dry run: would complete task {TASK_ID}" in caplog.text
    mocks.clickup.update_task.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "yes", "TRUE"])
def test_dry_run_unless_explicitly_false(
    mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("DRY_RUN")
    else:
        monkeypatch.setenv("DRY_RUN", value)
    assert _body(lambda_function.lambda_handler(event, None)) == "would_complete"
    mocks.clickup.update_task.assert_not_called()


def test_thread_parent_reminder_completes_task(mocks: Mocks, event: dict[str, Any]) -> None:
    # A reminder with a description reply is a thread parent: thread_ts equals its own ts.
    mocks.message["thread_ts"] = mocks.message["ts"]
    mocks.message["reply_count"] = 1
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.clickup.update_task.assert_called_once()


def test_truncated_reaction_users_still_counts(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.message["reactions"] = [{"name": "white_check_mark", "users": ["U0OTHER1"], "count": 60}]
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"


# --- Ignored without outside calls ---

def test_other_reaction_is_ignored_without_calls(mocks: Mocks, event: dict[str, Any]) -> None:
    event["event"]["reaction"] = "eyes"
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "ignored"
    mocks.assert_no_outside_calls()


def test_reaction_removed_is_ignored_without_calls(mocks: Mocks, event: dict[str, Any]) -> None:
    event["event"]["type"] = "reaction_removed"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.assert_no_outside_calls()


@pytest.mark.parametrize(
    "field, value",
    [
        ("channel", None),
        ("channel", "C0CJAK1D725\nCompleted task 1"),
        ("ts", "not-a-ts"),
        ("ts", 1763100000.0001),
        ("user", None),
        ("user", "U0REACTOR\nfake"),
    ],
)
def test_missing_or_malformed_ids_are_ignored_without_calls(
    mocks: Mocks, event: dict[str, Any], field: str, value: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    target = event["event"] if field == "user" else event["event"]["item"]
    target[field] = value
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.assert_no_outside_calls()
    # A forged newline never starts a log line of its own.
    assert all("\n" not in message for message in caplog.messages)


def test_reaction_on_a_file_is_ignored_without_calls(mocks: Mocks, event: dict[str, Any]) -> None:
    event["event"]["item"]["type"] = "file"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.assert_no_outside_calls()


def test_unlisted_channel_is_ignored_and_logs_channel(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    event["event"]["item"]["channel"] = "C0NOTPM01"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    assert "channel C0NOTPM01 is not a PM channel" in caplog.text
    mocks.aws.get_secret.assert_not_called()
    mocks.slack.get_channel_message.assert_not_called()
    mocks.clickup.get_task.assert_not_called()


def test_missing_pm_channels_key_ignores_everything(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.router_config = {}
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


# --- The message is not a current PM Bot reminder with the user's ✅ ---

def test_thread_reply_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.message = None
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


def test_message_in_a_thread_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.message["thread_ts"] = "1763000000.000001"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


def test_person_message_with_id_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    del mocks.message["bot_id"]
    mocks.message["user"] = "U0PERSON1"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


def test_other_bot_message_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.message["bot_id"] = "B0OTHER"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


@pytest.mark.parametrize(
    "reactions",
    [
        None,
        [],
        [{"name": "white_check_mark", "users": ["U0OTHER1"], "count": 1}],
        [{"name": "eyes", "users": ["U0REACTOR"], "count": 1}],
    ],
)
def test_message_without_users_checkmark_is_ignored(
    mocks: Mocks, event: dict[str, Any], reactions: Any
) -> None:
    if reactions is None:
        del mocks.message["reactions"]
    else:
        mocks.message["reactions"] = reactions
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


def test_non_reminder_bot_message_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.message["text"] = "Weekly task update! Mark tasks with :white_check_mark: to call them done!"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


# --- The task ---

def test_task_in_another_list_is_ignored(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    mocks.task["list"]["id"] = "999"
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    assert f"task {TASK_ID} is not in the PM Schedule list" in caplog.text
    mocks.clickup.update_task.assert_not_called()


@pytest.mark.parametrize("status_type", ["closed", "done"])
def test_closed_task_is_not_updated(mocks: Mocks, event: dict[str, Any], status_type: str) -> None:
    mocks.task["status"] = {"status": "complete", "type": status_type}
    assert _body(lambda_function.lambda_handler(event, None)) == "already_closed"
    mocks.clickup.update_task.assert_not_called()


@pytest.mark.parametrize("field", ["list", "status"])
def test_task_without_a_list_or_status_fails_cleanly(mocks: Mocks, event: dict[str, Any], field: str) -> None:
    del mocks.task[field]
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
    mocks.clickup.update_task.assert_not_called()


# --- Outside failures ---

def test_slack_error_is_logged_and_nothing_changes(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    mocks.slack.get_channel_message.side_effect = SlackRequestError("Slack conversations.history failed (not_in_channel)")
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
    assert "Could not read reminder 1763100000.000100 in C0CJAK1D725" in caplog.text
    mocks.clickup.get_task.assert_not_called()


def test_bot_id_error_is_logged_and_nothing_changes(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.slack.get_bot_id.side_effect = SlackRequestError("Slack auth.test failed (invalid_auth)")
    assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    mocks.clickup.get_task.assert_not_called()


def test_clickup_read_error_is_logged_with_task_id(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    mocks.clickup.get_task.side_effect = ValueError("ClickUp API HTTP Error: 503")
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "failed"
    assert f"Could not read task {TASK_ID}" in caplog.text
    mocks.clickup.update_task.assert_not_called()


def test_clickup_update_error_is_logged_with_task_id(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    mocks.clickup.update_task.side_effect = ValueError("ClickUp API HTTP Error: 400 Bad Request - PUT task/<id>")
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
    assert f"Could not complete task {TASK_ID}" in caplog.text
    assert "ClickUp API HTTP Error" not in result["body"]


# --- Configuration ---

@pytest.mark.parametrize("name", [n for n in ENV if n != "DRY_RUN"])
def test_missing_env_var_answers_500(
    mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch, name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv(name)
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 500
    assert _body(result) == "misconfigured"
    assert name in caplog.text
    mocks.assert_no_outside_calls()


@pytest.mark.parametrize("key", ["complete_status", "list_id"])
def test_missing_pm_config_key_answers_500(mocks: Mocks, event: dict[str, Any], key: str) -> None:
    del mocks.pm_config[key]
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 500
    assert _body(result) == "misconfigured"
    mocks.clickup.get_task.assert_not_called()


def test_non_dict_task_fails_cleanly(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.task = ["not", "a", "task"]
    assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    mocks.clickup.update_task.assert_not_called()


def test_bot_message_without_text_is_ignored(mocks: Mocks, event: dict[str, Any]) -> None:
    del mocks.message["text"]
    assert _body(lambda_function.lambda_handler(event, None)) == "ignored"
    mocks.clickup.get_task.assert_not_called()


def test_ssm_failure_answers_500_error(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.aws.get_json_parameter.side_effect = RuntimeError("ParameterNotFound /test/config")
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 500
    assert _body(result) == "error"
    assert "ParameterNotFound" not in result["body"]
    mocks.clickup.update_task.assert_not_called()


def test_unexpected_exception_is_caught(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.aws.get_secret.side_effect = RuntimeError("SECRET")
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 500
    assert _body(result) == "error"
    assert "SECRET" not in result["body"]


@pytest.mark.parametrize("bad_event", [None, "text", {"event": "text"}, {"event": {"item": "text"}}])
def test_malformed_event_never_raises(mocks: Mocks, bad_event: Any) -> None:
    result = lambda_function.lambda_handler(bad_event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "ignored"
    mocks.assert_no_outside_calls()


def test_bot_id_is_cached(mocks: Mocks, event: dict[str, Any]) -> None:
    lambda_function.lambda_handler(event, None)
    lambda_function.lambda_handler(copy.deepcopy(event), None)
    mocks.slack.get_bot_id.assert_called_once()
