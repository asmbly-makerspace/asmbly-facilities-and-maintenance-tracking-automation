"""
Completes a PM Schedule task in ClickUp when someone adds :white_check_mark: to its
PM Bot reminder in a PM channel. The Slack Event Router invokes it asynchronously with
the Slack event body; the answer reaches no one, so the outcome is for logs and tests.
"""
import json
import logging
import os
import re
from typing import Any

from common import aws, clickup, slack
from common.slack import SlackRequestError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CHECKMARK = "white_check_mark"
CLOSED_STATUS_TYPES = frozenset({"closed", "done"})
REQUIRED_ENV_VARS = (
    "CLICKUP_SECRET_NAME",
    "SLACK_MAINTENANCE_BOT_SECRET_NAME",
    "CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME",
    "ROUTER_CONFIG_PARAMETER_NAME",
)

# The PM Bot's reminder, as built by pm_bot_reminder.format_slack_message:
# "[OVERDUE] woodshop - <asset> - <task> - Frequency: <f> - ClickUp ID: <id>". The whole
# text must be that one line (no re.DOTALL): extra lines mean it isn't a plain reminder.
REMINDER_PATTERN = re.compile(r"\[[A-Z]+\] .+ - ClickUp ID: ([A-Za-z0-9]+)\s*")
CHANNEL_ID_PATTERN = re.compile(r"[CG][A-Z0-9]+")
MESSAGE_TS_PATTERN = re.compile(r"\d+\.\d+")
USER_ID_PATTERN = re.compile(r"[UW][A-Z0-9]+")

# The bot_id of the Maintenance Bot, cached for the life of the container.
_bot_id: str | None = None


def parse_reminder_task_id(text: str) -> str | None:
    """The ClickUp task ID from a PM Bot reminder's text, or None if it isn't one (fullmatch)."""
    if not isinstance(text, str):
        return None
    match = REMINDER_PATTERN.fullmatch(text)
    return match.group(1) if match else None


def _result(status_code: int, outcome: str) -> dict[str, Any]:
    return {"statusCode": status_code, "body": json.dumps({"result": outcome})}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ignored(event_id: Any, reason: str, *args: Any) -> dict[str, Any]:
    """Logs why the event was ignored (`reason` is a %-format of IDs only) and answers "ignored"."""
    logger.info("Ignored event %r: " + reason, event_id, *args)
    return _result(200, "ignored")


def _get_bot_id(token: str) -> str:
    global _bot_id
    if _bot_id is None:
        _bot_id = slack.get_bot_id(token)
    return _bot_id


def _user_checkmarked(message: dict[str, Any], user: str) -> bool:
    """
    True when the message carries a :white_check_mark: from `user`. Slack can truncate a
    reaction's `users` list on a busy message; when `count` is larger than the list, a real
    ✅ is on the message, so it is accepted too (a forged event can only repeat it).
    """
    reactions = message.get("reactions")
    if not isinstance(reactions, list):
        return False
    for reaction in reactions:
        if not isinstance(reaction, dict) or reaction.get("name") != CHECKMARK:
            continue
        users = reaction.get("users")
        users = users if isinstance(users, list) else []
        if user in users:
            return True
        count = reaction.get("count")
        if isinstance(count, int) and count > len(users):
            return True
    return False


def _handle(inner: dict[str, Any], item: dict[str, Any], event_id: Any) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        logger.error("Missing environment variables: %s", ", ".join(missing))
        return _result(500, "misconfigured")
    # Fail closed: only an explicit "false" writes to ClickUp (stage shares prod's list).
    dry_run = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

    # Cheap checks, no outside calls.
    if inner.get("type") != "reaction_added":
        return _ignored(event_id, "not a reaction_added event")
    if inner.get("reaction") != CHECKMARK:
        return _ignored(event_id, "not a white_check_mark reaction")
    if item.get("type") != "message":
        return _ignored(event_id, "the reaction is not on a message")
    channel, ts, user = item.get("channel"), item.get("ts"), inner.get("user")
    if not (isinstance(channel, str) and CHANNEL_ID_PATTERN.fullmatch(channel)):
        return _ignored(event_id, "missing or malformed channel")
    if not (isinstance(ts, str) and MESSAGE_TS_PATTERN.fullmatch(ts)):
        return _ignored(event_id, "missing or malformed message ts")
    if not (isinstance(user, str) and USER_ID_PATTERN.fullmatch(user)):
        return _ignored(event_id, "missing or malformed user")

    # PM channel.
    router_config = _as_dict(aws.get_json_parameter(os.environ["ROUTER_CONFIG_PARAMETER_NAME"]))
    pm_channels = _as_dict(router_config.get("pm_channels"))
    if channel not in pm_channels:
        return _ignored(event_id, "channel %s is not a PM channel", channel)

    slack_token = aws.get_secret(os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"], "SLACK_MAINTENANCE_BOT_TOKEN")
    clickup_token = aws.get_secret(os.environ["CLICKUP_SECRET_NAME"], "CLICKUP_API_TOKEN")

    # The message, from Slack.
    try:
        bot_id = _get_bot_id(slack_token)
        message = slack.get_channel_message(slack_token, channel, ts)
    except SlackRequestError:
        logger.error("Could not read reminder %s in %s for event %r", ts, channel, event_id)
        return _result(200, "failed")
    if message is None:
        return _ignored(event_id, "no top-level message at %s in %s", ts, channel)
    if message.get("bot_id") != bot_id:
        return _ignored(event_id, "message %s in %s is not from the PM Bot", ts, channel)
    thread_ts = message.get("thread_ts")
    if thread_ts is not None and thread_ts != ts:
        return _ignored(event_id, "message %s in %s is a thread reply", ts, channel)
    if not _user_checkmarked(message, user):
        return _ignored(event_id, "message %s in %s has no white_check_mark from %s", ts, channel, user)
    task_id = parse_reminder_task_id(message.get("text", ""))
    if task_id is None:
        return _ignored(event_id, "message %s in %s is not a PM reminder", ts, channel)

    # PM schedule config.
    pm_config = _as_dict(aws.get_json_parameter(os.environ["CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME"]))
    list_id = pm_config.get("list_id")
    complete_status = pm_config.get("complete_status")
    if not (isinstance(list_id, str) and list_id and isinstance(complete_status, str) and complete_status):
        logger.error("PM schedule config is missing list_id or complete_status")
        return _result(500, "misconfigured")

    # The task, from ClickUp.
    try:
        task = clickup.get_task(clickup_token, task_id)
    except ValueError:
        logger.error("Could not read task %s for event %r", task_id, event_id)
        return _result(200, "failed")
    task = _as_dict(task)
    task_list_id = _as_dict(task.get("list")).get("id")
    if not isinstance(task_list_id, str):
        logger.error("Could not read the list of task %s for event %r", task_id, event_id)
        return _result(200, "failed")
    if task_list_id != list_id:
        return _ignored(event_id, "task %s is not in the PM Schedule list", task_id)
    status_type = _as_dict(task.get("status")).get("type")
    if not isinstance(status_type, str):
        logger.error("Could not read the status of task %s for event %r", task_id, event_id)
        return _result(200, "failed")
    if status_type in CLOSED_STATUS_TYPES:
        logger.info("Task %s is already closed", task_id)
        return _result(200, "already_closed")

    if dry_run:
        logger.info("Dry run: would complete task %s from reminder %s in %s for user %s", task_id, ts, channel, user)
        return _result(200, "would_complete")

    # Complete. A failed or timed-out PUT leaves the task's state unknown, not unchanged.
    try:
        clickup.update_task(clickup_token, task_id, {"status": complete_status})
    except ValueError:
        logger.error("Could not complete task %s for event %r", task_id, event_id)
        return _result(200, "failed")
    logger.info("Completed task %s from reminder %s in %s for user %s", task_id, ts, channel, user)
    return _result(200, "completed")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handles one Slack reaction event forwarded by the Slack Event Router. Never raises."""
    body = _as_dict(event)
    inner = _as_dict(body.get("event"))
    item = _as_dict(inner.get("item"))
    event_id = body.get("event_id")
    # IDs only, never the body: it carries Slack's verification token. %r keeps a forged
    # value from writing extra log lines.
    logger.info(
        "Received event: type=%r reaction=%r channel=%r ts=%r event_id=%r user=%r",
        inner.get("type"), inner.get("reaction"), item.get("channel"), item.get("ts"), event_id, inner.get("user"),
    )
    try:
        return _handle(inner, item, event_id)
    except Exception:
        logger.exception("Unexpected error handling event %r", event_id)
        return _result(500, "error")
