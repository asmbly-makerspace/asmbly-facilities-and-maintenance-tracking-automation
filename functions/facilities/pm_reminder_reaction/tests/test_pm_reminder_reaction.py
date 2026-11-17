import copy
from decimal import Decimal
import json
import logging
import pathlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from moto import mock_aws

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
    "PM_COMPLETIONS_TABLE_NAME": "PMReminderCompletions-test",
    "DRY_RUN": "false",
}
ROUTER_CONFIG = {"pm_channels": {"C0CJAK1D725": "woodshop-maintenance"}}
PM_CONFIG = {"list_id": "901310894771", "complete_status": "complete"}
SECRETS = {"SLACK_MAINTENANCE_BOT_TOKEN": "xoxb-slack-token", "CLICKUP_API_TOKEN": "pk_clickup_token"}
TASK_ID = "86a8eb482"
TS = "1763100000.000100"
KEY = {"pk": f"task#{TASK_ID}"}
NOW = 1763200000
DUE = "1762300800000"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _body(result: dict[str, Any]) -> str:
    return json.loads(result["body"])["result"]


class Mocks:
    def __init__(self, aws: MagicMock, clickup: MagicMock, slack: MagicMock, table: Any) -> None:
        self.table = table
        self.now = NOW
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

    def record(self) -> dict[str, Any] | None:
        return self.table.get_item(Key=KEY, ConsistentRead=True).get("Item")

    def put_record(self, **attributes: Any) -> None:
        self.table.put_item(Item={**KEY, **attributes})

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
    # Another test module sets AWS_REGION at import; boto3 reads either.
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.setenv(name, "us-east-2")
    monkeypatch.setattr(lambda_function, "_bot_id", None)
    monkeypatch.setattr(lambda_function, "_table", None)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=ENV["PM_COMPLETIONS_TABLE_NAME"],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb").Table(ENV["PM_COMPLETIONS_TABLE_NAME"])
        with patch(f"{MODULE}.aws") as aws, patch(f"{MODULE}.clickup") as clickup, patch(f"{MODULE}.slack") as slack:
            m = Mocks(aws, clickup, slack, table)
            monkeypatch.setattr(lambda_function, "_now", lambda: m.now)
            yield m


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


# --- Completed once per cycle ---

def _completed_at(result: dict[str, Any]) -> Any:
    return json.loads(result["body"]).get("completed_at")


def _client_error(code: str, operation: str = "UpdateItem") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, operation)


def test_first_checkmark_claims_and_completes(mocks: Mocks, event: dict[str, Any]) -> None:
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"

    record = mocks.record()
    assert record is not None
    assert record["state"] == "done"
    assert record["reminder_ts"] == TS
    assert record["channel"] == "C0CJAK1D725"
    assert record["due_before"] == DUE
    assert record["completed_at"] == NOW
    assert "claim_id" not in record
    mocks.clickup.update_task.assert_called_once()


def test_second_checkmark_on_same_reminder_is_duplicate(mocks: Mocks, event: dict[str, Any]) -> None:
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    # ClickUp's recurrence reopens the task with its next due date, so it isn't "closed".
    mocks.task["due_date"] = "1762905600000"
    mocks.message["reactions"] = [{"name": "white_check_mark", "users": ["U0REACTOR", "U0OTHER2"], "count": 2}]
    second = copy.deepcopy(event)
    second["event_id"] = "Ev2"
    second["event"]["user"] = "U0OTHER2"
    mocks.now = NOW + 30

    result = lambda_function.lambda_handler(second, None)

    assert _body(result) == "duplicate"
    assert _completed_at(result) == NOW
    mocks.clickup.update_task.assert_called_once()
    assert mocks.record()["completed_at"] == NOW


def test_redelivered_event_is_duplicate(mocks: Mocks, event: dict[str, Any]) -> None:
    lambda_function.lambda_handler(event, None)
    mocks.task["due_date"] = "1762905600000"
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "duplicate"
    mocks.clickup.update_task.assert_called_once()


def test_in_flight_claim_is_duplicate(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.put_record(state="pending", claim_id="other", claimed_at=NOW - 10, reminder_ts=TS, due_before=DUE)
    assert _body(lambda_function.lambda_handler(event, None)) == "duplicate"
    mocks.clickup.update_task.assert_not_called()
    assert mocks.record()["claim_id"] == "other"


def test_older_reminder_after_completion_is_stale(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    mocks.put_record(state="done", completed_at=1763150000, reminder_ts="1763140000.000200", due_before=DUE)
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "stale"
    assert _completed_at(result) == 1763150000
    assert f"Task {TASK_ID}: stale for reminder {TS}" in caplog.text
    mocks.clickup.update_task.assert_not_called()
    assert mocks.record()["reminder_ts"] == "1763140000.000200"


def test_newer_reminder_after_old_completion_completes(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.put_record(state="done", completed_at=1763000000, reminder_ts="1762500000.000100", due_before="1")
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.clickup.update_task.assert_called_once()
    record = mocks.record()
    assert record["reminder_ts"] == TS
    assert record["completed_at"] == NOW


@pytest.mark.parametrize("field", ["date_done", "date_closed"])
def test_clickup_date_done_after_reminder_is_stale(
    mocks: Mocks, event: dict[str, Any], field: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    mocks.task[field] = "1763150000000"
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "stale"
    assert _completed_at(result) == 1763150000
    assert field in caplog.text
    assert mocks.record() is None
    mocks.clickup.update_task.assert_not_called()


@pytest.mark.parametrize("value", ["soon", "NaN", "Infinity", True, None, {"ms": 1}, "1763000000000"])
def test_clickup_date_done_malformed_or_earlier_is_ignored(mocks: Mocks, event: dict[str, Any], value: Any) -> None:
    mocks.task["date_done"] = value
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"


def test_update_failure_keeps_pending_claim(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    mocks.clickup.update_task.side_effect = ValueError("ClickUp API HTTP Error: 503")
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "failed"
    assert f"Could not complete task {TASK_ID}" in caplog.text
    record = mocks.record()
    assert record["state"] == "pending"
    assert record["claim_id"]
    assert record["claimed_at"] == NOW
    assert "ClickUp API HTTP Error" not in result["body"]


def test_retry_after_failure_completes_once(mocks: Mocks, event: dict[str, Any]) -> None:
    calls: list[str] = []

    def update(token: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(task_id)
        if len(calls) == 1:
            raise ValueError("Network error during ClickUp API request: PUT task/<id> (ReadTimeout)")
        return {"id": task_id}

    mocks.clickup.update_task.side_effect = update
    assert _body(lambda_function.lambda_handler(event, None)) == "failed"

    # Lambda's retry, or the person re-adding the check mark, inside the claim's expiry.
    mocks.now = NOW + 120
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "duplicate"
    assert len(calls) == 1

    # After the expiry, the due date is unchanged, so the earlier update didn't land.
    mocks.now = NOW + lambda_function.CLAIM_EXPIRY_SECONDS + 1
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "completed"
    assert len(calls) == 2
    assert mocks.record()["state"] == "done"


@pytest.mark.parametrize(
    "landed",
    [
        {"due_date": "1762905600000"},
        {"status": {"status": "complete", "type": "closed"}},
        {"status": {"status": "Complete", "type": "custom"}},
    ],
)
def test_update_error_that_landed_counts_as_completed(
    mocks: Mocks, event: dict[str, Any], landed: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    mocks.clickup.update_task.side_effect = ValueError("Network error (ReadTimeout)")
    mocks.clickup.get_task.side_effect = [copy.deepcopy(mocks.task), {**mocks.task, **landed}]
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    assert f"Task {TASK_ID} was completed although the update reported an error" in caplog.text
    assert mocks.record()["state"] == "done"
    mocks.clickup.update_task.assert_called_once()


def test_reread_failure_leaves_pending_claim(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.clickup.update_task.side_effect = ValueError("Network error (ReadTimeout)")
    mocks.clickup.get_task.side_effect = [copy.deepcopy(mocks.task), ValueError("503"), copy.deepcopy(mocks.task)]
    assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    assert mocks.record()["state"] == "pending"

    mocks.now = NOW + 100
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "duplicate"
    mocks.clickup.update_task.assert_called_once()


@pytest.mark.parametrize(
    ("reminder_ts", "claimed_at", "outcome"),
    [
        # The dead invocation was completing this same reminder.
        (TS, NOW - 400, "duplicate"),
        # It completed a newer reminder after this one was posted.
        ("1763190000.000100", NOW - 400, "stale"),
    ],
)
def test_expired_claim_whose_update_landed_is_not_repeated(
    mocks: Mocks, event: dict[str, Any], reminder_ts: str, claimed_at: int, outcome: str
) -> None:
    mocks.put_record(
        state="pending", claim_id="dead", claimed_at=claimed_at, reminder_ts=reminder_ts,
        channel="C0CJAK1D725", due_before="1761696000000",
    )
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == outcome
    assert _completed_at(result) == claimed_at
    mocks.clickup.update_task.assert_not_called()
    record = mocks.record()
    assert record["state"] == "done"
    assert record["completed_at"] == claimed_at
    assert record["reminder_ts"] == reminder_ts
    assert "claim_id" not in record


def test_expired_claim_from_before_this_reminder_that_landed_completes(mocks: Mocks, event: dict[str, Any]) -> None:
    # A claim stuck since last week, whose update landed; ClickUp brought the task back.
    mocks.put_record(
        state="pending", claim_id="dead", claimed_at=1762500000, reminder_ts="1762490000.000100",
        channel="C0CJAK1D725", due_before="1761696000000",
    )
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.clickup.update_task.assert_called_once()
    record = mocks.record()
    assert record["reminder_ts"] == TS
    assert record["completed_at"] == NOW


def test_expired_claim_whose_update_did_not_land_completes(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.put_record(
        state="pending", claim_id="dead", claimed_at=NOW - 400, reminder_ts=TS, channel="C0CJAK1D725", due_before=DUE,
    )
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.clickup.update_task.assert_called_once()
    assert mocks.record()["state"] == "done"


def test_dynamodb_error_makes_no_clickup_call(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    table = MagicMock()
    table.update_item.side_effect = _client_error("ProvisionedThroughputExceededException")
    with patch(f"{MODULE}._get_table", return_value=table):
        result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
    assert f"Could not record completion of task {TASK_ID}: ProvisionedThroughputExceededException" in caplog.text
    mocks.clickup.update_task.assert_not_called()


def test_conditional_failure_without_item_fails(mocks: Mocks, event: dict[str, Any]) -> None:
    table = MagicMock()
    table.update_item.side_effect = _client_error("ConditionalCheckFailedException")
    with patch(f"{MODULE}._get_table", return_value=table):
        assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    mocks.clickup.update_task.assert_not_called()


def test_done_write_error_still_completed(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    table = MagicMock()
    table.update_item.side_effect = [{}, _client_error("InternalServerError")]
    with patch(f"{MODULE}._get_table", return_value=table):
        result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "completed"
    assert f"Could not record task {TASK_ID} as done: InternalServerError" in caplog.text


def test_done_write_after_lost_claim_still_completed(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    table = MagicMock()
    table.update_item.side_effect = [{}, _client_error("ConditionalCheckFailedException")]
    with patch(f"{MODULE}._get_table", return_value=table):
        assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    assert f"The claim on task {TASK_ID} expired" in caplog.text


def test_dry_run_reads_but_writes_nothing(
    mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    assert _body(lambda_function.lambda_handler(event, None)) == "would_complete"
    assert mocks.record() is None

    mocks.put_record(state="done", completed_at=NOW - 60, reminder_ts=TS, due_before=DUE)
    before = mocks.record()
    result = lambda_function.lambda_handler(copy.deepcopy(event), None)
    assert _body(result) == "duplicate"
    assert _completed_at(result) == NOW - 60
    assert mocks.record() == before

    mocks.put_record(state="done", completed_at=NOW - 60, reminder_ts="1763190000.000100", due_before=DUE)
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "stale"

    mocks.put_record(state="pending", claim_id="dead", claimed_at=NOW - 400, reminder_ts=TS, due_before=DUE)
    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "would_complete"
    mocks.clickup.update_task.assert_not_called()


def test_dry_run_read_error_fails(mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    table = MagicMock()
    table.get_item.side_effect = _client_error("AccessDeniedException", "GetItem")
    with patch(f"{MODULE}._get_table", return_value=table):
        assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    table.update_item.assert_not_called()
    table.put_item.assert_not_called()


def test_claim_expiry_outlasts_the_function_timeout() -> None:
    template = pathlib.Path(__file__).parents[4] / "templates" / "facilities.yaml"
    block = template.read_text().split("PMReminderReactionFunction:\n", 1)[1]
    timeout = int(block.split("Timeout:", 1)[1].split()[0])
    assert lambda_function.CLAIM_EXPIRY_SECONDS >= 3 * timeout


@pytest.mark.parametrize("date_done", [None, str(NOW * 1000)])
def test_reopened_task_is_not_completed_twice_whatever_date_done_says(
    mocks: Mocks, event: dict[str, Any], date_done: str | None
) -> None:
    # API v2 may hide date_done/date_closed on a reopened recurring task (null), or show
    # the completion just made. Either way the claim alone stops a second completion.
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.task.update({
        "status": {"status": "to do", "type": "open"},
        "due_date": "1762905600000",
        "date_done": date_done,
        "date_closed": date_done,
    })
    mocks.now = NOW + 60
    result = lambda_function.lambda_handler(copy.deepcopy(event), None)
    assert _body(result) == "duplicate"
    assert _completed_at(result) == NOW
    mocks.clickup.update_task.assert_called_once()


def test_failed_update_does_not_let_an_older_reminder_through(mocks: Mocks, event: dict[str, Any]) -> None:
    # Done at T1 from a newer reminder; a later ✅ on an even newer reminder fails in
    # ClickUp, leaving a pending claim. After it expires, a ✅ on a reminder older than T1
    # must still be stale.
    mocks.put_record(
        state="done", completed_at=1763150000, reminder_ts="1763140000.000200", channel="C0CJAK1D725", due_before="1",
    )
    assert _body(lambda_function.lambda_handler(event, None)) == "stale"
    mocks.table.update_item(
        Key=KEY,
        UpdateExpression="SET #s = :p, claim_id = :c, claimed_at = :t, reminder_ts = :r, due_before = :d",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":p": "pending", ":c": "dead", ":t": NOW - 10, ":r": "1763190000.000100", ":d": DUE},
    )

    assert _body(lambda_function.lambda_handler(copy.deepcopy(event), None)) == "stale"
    mocks.now = NOW + lambda_function.CLAIM_EXPIRY_SECONDS + 1
    result = lambda_function.lambda_handler(copy.deepcopy(event), None)

    assert _body(result) == "stale"
    assert _completed_at(result) == 1763150000
    mocks.clickup.update_task.assert_not_called()
    assert mocks.record()["claim_id"] == "dead"


def test_dry_run_expired_claim_over_a_newer_completion_is_stale(
    mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    mocks.put_record(
        state="pending", claim_id="dead", claimed_at=NOW - 400, completed_at=1763150000,
        reminder_ts="1763190000.000100", due_before=DUE,
    )
    assert _body(lambda_function.lambda_handler(event, None)) == "stale"


def _timeout() -> ReadTimeoutError:
    return ReadTimeoutError(endpoint_url="https://dynamodb.us-east-2.amazonaws.com")


def test_dynamodb_network_error_on_claim_makes_no_clickup_call(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    table = MagicMock()
    table.update_item.side_effect = _timeout()
    with patch(f"{MODULE}._get_table", return_value=table):
        result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
    assert f"Could not record completion of task {TASK_ID}: ReadTimeoutError" in caplog.text
    mocks.clickup.update_task.assert_not_called()


def test_dynamodb_network_error_on_done_write_still_completed(mocks: Mocks, event: dict[str, Any]) -> None:
    table = MagicMock()
    table.update_item.side_effect = [{}, _timeout()]
    with patch(f"{MODULE}._get_table", return_value=table):
        result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "completed"


def test_dry_run_network_error_fails(mocks: Mocks, event: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    table = MagicMock()
    table.get_item.side_effect = _timeout()
    with patch(f"{MODULE}._get_table", return_value=table):
        result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"


def test_takeover_that_cannot_record_a_landed_update_logs_an_error(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    table = MagicMock()
    table.update_item.side_effect = [
        {"Attributes": {"state": "pending", "claimed_at": Decimal(1), "reminder_ts": TS, "due_before": "1761696000000"}},
        _client_error("InternalServerError"),
    ]
    with patch(f"{MODULE}._get_table", return_value=table):
        assert _body(lambda_function.lambda_handler(event, None)) == "duplicate"
    assert f"Task {TASK_ID}: an earlier update landed but could not be recorded" in caplog.text
    mocks.clickup.update_task.assert_not_called()


def test_clickup_date_done_with_unreadable_record_is_stale(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.task["date_done"] = "1763150000000"
    table = MagicMock()
    table.get_item.side_effect = _timeout()
    with patch(f"{MODULE}._get_table", return_value=table):
        assert _body(lambda_function.lambda_handler(event, None)) == "stale"
    table.update_item.assert_not_called()
    mocks.clickup.update_task.assert_not_called()


def test_expired_claim_over_an_older_completion_completes(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.put_record(
        state="pending", claim_id="dead", claimed_at=NOW - 400, completed_at=1763000000,
        reminder_ts="1763190000.000100", channel="C0CJAK1D725", due_before=DUE,
    )
    assert _body(lambda_function.lambda_handler(event, None)) == "completed"
    mocks.clickup.update_task.assert_called_once()
    record = mocks.record()
    assert record["state"] == "done"
    assert record["reminder_ts"] == TS
    assert record["completed_at"] == NOW


def test_own_claim_retried_after_lost_response_fails_without_clickup_call(
    mocks: Mocks, event: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with patch(f"{MODULE}.uuid.uuid4") as uuid4:
        uuid4.return_value.hex = "mine"
        mocks.put_record(state="pending", claim_id="mine", claimed_at=NOW, reminder_ts=TS, due_before=DUE)
        result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "failed"
    assert f"The claim on task {TASK_ID} was written but its response was lost" in caplog.text
    mocks.clickup.update_task.assert_not_called()


def test_reread_error_body_is_not_a_landed_update(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.clickup.update_task.side_effect = ValueError("Network error (ReadTimeout)")
    mocks.clickup.get_task.side_effect = [copy.deepcopy(mocks.task), {"err": "x", "ECODE": "Y"}]
    assert _body(lambda_function.lambda_handler(event, None)) == "failed"
    assert mocks.record()["state"] == "pending"


def test_duplicate_against_an_in_flight_claim_reports_no_completion_time(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.put_record(
        state="pending", claim_id="other", claimed_at=NOW - 10, completed_at=1762000000,
        reminder_ts=TS, due_before=DUE,
    )
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "duplicate"
    assert _completed_at(result) is None


def test_in_flight_claim_for_another_reminder_is_duplicate(mocks: Mocks, event: dict[str, Any]) -> None:
    # Two reminders for the same task in one cycle, ticked at once: the second waits on the first.
    mocks.put_record(
        state="pending", claim_id="other", claimed_at=NOW - 10, completed_at=1762000000,
        reminder_ts="1763190000.000100", due_before=DUE,
    )
    result = lambda_function.lambda_handler(event, None)
    assert _body(result) == "duplicate"
    assert _completed_at(result) is None
    mocks.clickup.update_task.assert_not_called()


def test_reread_with_unexpected_status_type_fails_cleanly(mocks: Mocks, event: dict[str, Any]) -> None:
    mocks.clickup.update_task.side_effect = ValueError("Network error (ReadTimeout)")
    mocks.clickup.get_task.side_effect = [
        copy.deepcopy(mocks.task), {**mocks.task, "status": {"status": "to do", "type": ["open"]}},
    ]
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert _body(result) == "failed"
