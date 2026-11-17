"""
Completes a PM Schedule task in ClickUp when someone adds :white_check_mark: to its
PM Bot reminder in a PM channel. The Slack Event Router invokes it asynchronously with
the Slack event body; the answer reaches no one, so the outcome is for logs and tests.

A claim in the PMReminderCompletions table, written before the ClickUp update, makes
each task complete once per cycle: a second check mark, a redelivered event, a Lambda
retry or a check mark on an older reminder changes nothing.

After the outcome is known, the PM Bot replies in the reminder's thread: marked done
(with the next due date), already done, or that ClickUp failed. The reply never changes
the outcome, and stage replies nothing.
"""
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

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
    "PM_COMPLETIONS_TABLE_NAME",
)
# A pending claim older than this belongs to a dead invocation. More than three times the
# 90-second function timeout, and longer than Lambda's two async retries after a timeout
# (about 1 and 2 minutes apart), so the first retry finds the claim and stops. A retry
# that comes later takes the claim over, and the due-date check keeps that safe.
CLAIM_EXPIRY_SECONDS = 300
CLAIM_CONDITION = (
    "attribute_not_exists(pk)"
    " OR (#state = :done AND #completed_at < :reminder_epoch)"
    " OR (#state = :pending AND #claimed_at < :expired"
    # A pending claim keeps the completed_at of the completion before it, so a failed
    # update can't let a reminder older than that completion through.
    " AND (attribute_not_exists(#completed_at) OR #completed_at < :reminder_epoch))"
)
NAMES = {
    "#state": "state",
    "#claim_id": "claim_id",
    "#claimed_at": "claimed_at",
    "#completed_at": "completed_at",
    "#reminder_ts": "reminder_ts",
    "#channel": "channel",
    "#due_before": "due_before",
}

# The PM Bot's reminder, as built by pm_bot_reminder.format_slack_message:
# "[OVERDUE] woodshop - <asset> - <task> - Frequency: <f> - ClickUp ID: <id>". The whole
# text must be that one line (no re.DOTALL): extra lines mean it isn't a plain reminder.
REMINDER_PATTERN = re.compile(r"\[[A-Z]+\] .+ - ClickUp ID: ([A-Za-z0-9]+)\s*")
CHANNEL_ID_PATTERN = re.compile(r"[CG][A-Z0-9]+")
MESSAGE_TS_PATTERN = re.compile(r"\d+\.\d+")
USER_ID_PATTERN = re.compile(r"[UW][A-Z0-9]+")
# Slack event IDs are short; the bound keeps a forged one well inside the 2,048-byte key limit.
EVENT_ID_PATTERN = re.compile(r"Ev[A-Za-z0-9]{1,32}")
# The Frequency field of a reminder; the PM Bot writes "N/A" when the task has none.
FREQUENCY_PATTERN = re.compile(r" - Frequency: (.*) - ClickUp ID: [A-Za-z0-9]+\s*")
NO_FREQUENCY = frozenset({"", "n/a"})

AUSTIN_TIME_ZONE = "America/Chicago"
# How long the "already done" and failure reply markers are kept (DynamoDB TTL).
REPLY_MARKER_SECONDS = 60 * 86400
# How long to wait before re-reading a completed task to see whether ClickUp reopened it.
RECURRENCE_WAIT_SECONDS = 2
REPLY_COMPLETED_NEXT = "Marked done in ClickUp. Next due {date}"
REPLY_COMPLETED_CLOSED = "Marked done in ClickUp. This task doesn't repeat, so it's now closed."
REPLY_COMPLETED_PLAIN = "Marked done in ClickUp."
REPLY_ALREADY_DONE = "Already marked done on {date}; nothing changed."
REPLY_ALREADY_DONE_NO_DATE = "Already marked done in ClickUp; nothing changed."
# After a failed update the claim stays pending for CLAIM_EXPIRY_SECONDS, and a check mark
# added again in that window is a silent duplicate, hence the wait.
REPLY_FAILED = (
    "Couldn't mark this done in ClickUp. Try again later. "
    "Wait 5 minutes, then remove and add the :white_check_mark: again."
)

# The bot_id of the Maintenance Bot, cached for the life of the container.
_bot_id: str | None = None
# The completions table, created on first use.
_table: Any = None
_deserializer = TypeDeserializer()


@dataclass
class _ReplyContext:
    """What _handle learned that the thread reply needs. Filled in as the checks pass."""

    dry_run: bool = True
    slack_token: str | None = None
    clickup_token: str | None = None
    channel: str | None = None
    ts: str | None = None
    event_id: Any = None
    # Set once the message is confirmed as a PM Bot reminder (only then is a failure answered).
    task_id: str | None = None
    frequency: str = ""
    task: dict[str, Any] = field(default_factory=dict)
    due_before: str = ""
    # The task update_task returned, or None when the update reported an error but landed.
    updated_task: dict[str, Any] | None = None


def parse_reminder_task_id(text: str) -> str | None:
    """The ClickUp task ID from a PM Bot reminder's text, or None if it isn't one (fullmatch)."""
    if not isinstance(text, str):
        return None
    match = REMINDER_PATTERN.fullmatch(text)
    return match.group(1) if match else None


def parse_reminder_frequency(text: str) -> str:
    """The Frequency value of a PM Bot reminder, or "" if it has none."""
    match = FREQUENCY_PATTERN.search(text) if isinstance(text, str) else None
    return match.group(1).strip() if match else ""


def _austin_date(epoch_seconds: float) -> str:
    """An Austin (Central) date such as "Wed Nov 25"."""
    # The zone is loaded here, not at import, so a missing tzdata can only cost a reply.
    d = datetime.fromtimestamp(float(epoch_seconds), ZoneInfo(AUSTIN_TIME_ZONE))
    return f"{d:%a %b} {d.day}"


def _date_or_none(epoch_seconds: float) -> str | None:
    """_austin_date, or None for a value no calendar date fits (logged)."""
    try:
        return _austin_date(epoch_seconds)
    # LookupError covers ZoneInfoNotFoundError (tzdata missing from the bundle).
    except (ValueError, OverflowError, OSError, LookupError):
        logger.warning("Could not turn timestamp %r into a date", epoch_seconds)
        return None


def _millis(value: Any) -> int | None:
    """A ClickUp millisecond timestamp (string or number) as an int, or None."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _result(status_code: int, outcome: str, completed_at: Any = None) -> dict[str, Any]:
    """The answer. `completed_at` (epoch seconds) is the task's last completion, for stale and duplicate."""
    body: dict[str, Any] = {"result": outcome}
    if isinstance(completed_at, (int, Decimal)) and not isinstance(completed_at, bool):
        body["completed_at"] = int(completed_at)
    return {"statusCode": status_code, "body": json.dumps(body)}


def _now() -> int:
    return int(time.time())


def _get_table() -> Any:
    """Returns the completions table, creating the resource on first use."""
    global _table
    if _table is None:
        # Short timeouts and few retries, so a DynamoDB outage ends as a logged "failed"
        # well inside the 90-second function timeout.
        config = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"})
        _table = boto3.resource("dynamodb", config=config).Table(os.environ["PM_COMPLETIONS_TABLE_NAME"])
    return _table


def _error_code(error: ClientError | BotoCoreError) -> str:
    """The DynamoDB error code, or the exception's class name for a network error."""
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "Unknown"))
    return type(error).__name__


def _due_date(task: dict[str, Any]) -> str:
    """The task's due date as ClickUp gives it (ms string), or "" if it has none."""
    due = task.get("due_date")
    return due if isinstance(due, str) else ""


def _clickup_completed_after(task: dict[str, Any], reminder_epoch: Decimal) -> tuple[str, int] | None:
    """
    (field, epoch seconds) when ClickUp's date_done or date_closed is later than the
    reminder, so the task was completed after it was posted. A missing or malformed value
    is ignored. Best effort only: API v2 may return these as null on a reopened recurring
    task, so the claim, not this check, is what stops a second completion.
    """
    for field in ("date_done", "date_closed"):
        value = task.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        try:
            millis = Decimal(str(value))
        except InvalidOperation:
            continue
        if millis.is_finite() and millis > reminder_epoch * 1000:
            return field, int(millis / 1000)
    return None


def _completed_before(record: dict[str, Any], reminder_epoch: Decimal) -> bool:
    """True when the record has no completion yet, or its completion is older than the reminder."""
    completed_at = record.get("completed_at")
    if completed_at is None:
        return True
    return isinstance(completed_at, Decimal) and completed_at < reminder_epoch


def _classify_blocked(record: dict[str, Any], ts: str, reminder_epoch: Decimal) -> str:
    """Why a claim was refused: this reminder did it or is doing it, another is, or the reminder is older."""
    if record.get("reminder_ts") == ts:
        return "duplicate"
    if not _completed_before(record, reminder_epoch):
        return "stale"
    return "duplicate" if record.get("state") == "pending" else "stale"


def _last_completion(record: dict[str, Any], outcome: str) -> Any:
    """The completed_at to report: on a pending record it is the previous cycle's, so only for stale."""
    if outcome == "stale" or record.get("state") == "done":
        return record.get("completed_at")
    return None


def _claimable(record: dict[str, Any] | None, reminder_epoch: Decimal, now: int) -> bool:
    """The claim condition, evaluated in Python for the dry run."""
    if not record:
        return True
    state = record.get("state")
    if state == "done":
        return record.get("completed_at") is not None and _completed_before(record, reminder_epoch)
    if state == "pending":
        claimed_at = record.get("claimed_at")
        expired = isinstance(claimed_at, Decimal) and claimed_at < now - CLAIM_EXPIRY_SECONDS
        return expired and _completed_before(record, reminder_epoch)
    return False


def _mark_done(
    task_id: str, claim_id: str, completed_at: Any, reminder_ts: Any = None, channel: Any = None
) -> bool:
    """Records the task as done, if this invocation still holds the claim. Never raises."""
    update = "SET #state = :done, #completed_at = :completed_at"
    values: dict[str, Any] = {":done": "done", ":completed_at": completed_at, ":claim": claim_id}
    if reminder_ts is not None:
        update += ", #reminder_ts = :reminder_ts"
        values[":reminder_ts"] = reminder_ts
    if channel is not None:
        update += ", #channel = :channel"
        values[":channel"] = channel
    update += " REMOVE #claim_id"
    names = {name: attribute for name, attribute in NAMES.items() if name in update}
    try:
        _get_table().update_item(
            Key={"pk": f"task#{task_id}"},
            UpdateExpression=update,
            ConditionExpression="#claim_id = :claim",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except (ClientError, BotoCoreError) as error:
        code = _error_code(error)
        if code == "ConditionalCheckFailedException":
            logger.warning("The claim on task %s expired before it was recorded as done", task_id)
        else:
            logger.error("Could not record task %s as done: %s", task_id, code)
        return False
    return True


def _update_landed(clickup_token: str, task_id: str, complete_status: str, due_before: str) -> bool:
    """After a failed update, re-reads the task: True if the update was applied anyway."""
    try:
        task = _as_dict(clickup.get_task(clickup_token, task_id))
    except ValueError:
        logger.error("Could not re-read task %s after its update failed", task_id)
        return False
    status = _as_dict(task.get("status"))
    status_name = status.get("status")
    status_type = status.get("type")
    if isinstance(status_type, str) and status_type in CLOSED_STATUS_TYPES:
        return True
    if isinstance(status_name, str) and status_name.casefold() == complete_status.casefold():
        return True
    # ClickUp can answer 200 with an error body; only a real task's due date counts.
    return task.get("id") == task_id and _due_date(task) != due_before


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


def _handle(inner: dict[str, Any], item: dict[str, Any], event_id: Any, ctx: _ReplyContext) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        logger.error("Missing environment variables: %s", ", ".join(missing))
        return _result(500, "misconfigured")
    # Fail closed: only an explicit "false" writes to ClickUp (stage shares prod's list).
    dry_run = os.environ.get("DRY_RUN", "true").strip().lower() != "false"
    ctx.dry_run = dry_run

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
    ctx.slack_token, ctx.clickup_token, ctx.channel, ctx.ts = slack_token, clickup_token, channel, ts

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
    ctx.task_id = task_id
    ctx.frequency = parse_reminder_frequency(message.get("text", ""))

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
    ctx.task = task
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

    reminder_epoch = Decimal(ts)
    key = {"pk": f"task#{task_id}"}
    completed_after = _clickup_completed_after(task, reminder_epoch)
    if completed_after is not None:
        # If ClickUp keeps date_done on the reopened task, this reminder may be the one that
        # completed it (a second check mark or a redelivery): that is a duplicate, not stale.
        try:
            record = _as_dict(_get_table().get_item(Key=key, ConsistentRead=True).get("Item"))
        except (ClientError, BotoCoreError) as error:
            logger.warning("Could not read the completion record of task %s: %s", task_id, _error_code(error))
            record = {}
        if record.get("reminder_ts") == ts:
            logger.info("Task %s: duplicate for reminder %s", task_id, ts)
            return _result(200, "duplicate", _last_completion(record, "duplicate"))
        field, completed_at = completed_after
        logger.info("Reminder %s for task %s is older than its last completion (%s)", ts, task_id, field)
        return _result(200, "stale", completed_at)

    due_before = _due_date(task)
    ctx.due_before = due_before
    now = _now()

    if dry_run:
        try:
            record = _get_table().get_item(Key=key, ConsistentRead=True).get("Item")
        except (ClientError, BotoCoreError) as error:
            logger.error("Could not read the completion record of task %s: %s", task_id, _error_code(error))
            return _result(200, "failed")
        if _claimable(record, reminder_epoch, now):
            logger.info(
                "Dry run: would complete task %s from reminder %s in %s for user %s", task_id, ts, channel, user
            )
            return _result(200, "would_complete")
        outcome = _classify_blocked(record, ts, reminder_epoch)
        logger.info("Dry run: task %s: %s for reminder %s", task_id, outcome, ts)
        return _result(200, outcome, _last_completion(record, outcome))

    # Claim the task before the update, so a retry or a second check mark can't complete it again.
    claim_id = uuid.uuid4().hex
    try:
        response = _get_table().update_item(
            Key=key,
            UpdateExpression=(
                "SET #state = :pending, #claim_id = :claim, #claimed_at = :now,"
                " #reminder_ts = :ts, #channel = :channel, #due_before = :due"
            ),
            ConditionExpression=CLAIM_CONDITION,
            ExpressionAttributeNames=NAMES,
            ExpressionAttributeValues={
                ":pending": "pending",
                ":done": "done",
                ":claim": claim_id,
                ":now": now,
                ":ts": ts,
                ":channel": channel,
                ":due": due_before,
                ":reminder_epoch": reminder_epoch,
                ":expired": now - CLAIM_EXPIRY_SECONDS,
            },
            ReturnValues="ALL_OLD",
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
    except (ClientError, BotoCoreError) as error:
        code = _error_code(error)
        if not isinstance(error, ClientError) or code != "ConditionalCheckFailedException":
            logger.error("Could not record completion of task %s: %s", task_id, code)
            return _result(200, "failed")
        raw_item = error.response.get("Item")
        if not isinstance(raw_item, dict) or not raw_item:
            logger.error("Could not read the record that blocked the claim on task %s", task_id)
            return _result(200, "failed")
        blocking = {name: _deserializer.deserialize(value) for name, value in raw_item.items()}
        if blocking.get("claim_id") == claim_id:
            # Our own write landed and botocore retried it after a lost response. The claim
            # is ours but the run stops here; it expires after CLAIM_EXPIRY_SECONDS.
            logger.error("The claim on task %s was written but its response was lost", task_id)
            return _result(200, "failed")
        outcome = _classify_blocked(blocking, ts, reminder_epoch)
        logger.info("Task %s: %s for reminder %s", task_id, outcome, ts)
        return _result(200, outcome, _last_completion(blocking, outcome))

    old = _as_dict(response.get("Attributes"))
    if old.get("state") == "pending" and old.get("due_before", "") != due_before:
        # Took over an expired claim whose update landed before its invocation died.
        old_claimed_at = old.get("claimed_at")
        if old.get("reminder_ts") == ts or not (
            isinstance(old_claimed_at, Decimal) and old_claimed_at < reminder_epoch
        ):
            outcome = "duplicate" if old.get("reminder_ts") == ts else "stale"
            if not _mark_done(task_id, claim_id, old_claimed_at, old.get("reminder_ts"), old.get("channel")):
                # The claim now holds the current due date, so the next takeover can't see
                # that the earlier update landed. Rare (two failures in a row); logged to check by hand.
                logger.error("Task %s: an earlier update landed but could not be recorded; check the record", task_id)
            logger.info("Task %s: %s for reminder %s (an earlier update landed)", task_id, outcome, ts)
            return _result(200, outcome, old_claimed_at)
        # The earlier claim predates this reminder: the task came back, and this is a new cycle.
        logger.info("Task %s: an earlier claim landed before reminder %s was posted", task_id, ts)

    # Complete. A failed or timed-out PUT may still have landed, so the claim is kept
    # unless the re-read shows the update was applied; it expires after CLAIM_EXPIRY_SECONDS.
    try:
        ctx.updated_task = _as_dict(clickup.update_task(clickup_token, task_id, {"status": complete_status}))
    except ValueError:
        logger.error("Could not complete task %s for event %r", task_id, event_id)
        if not _update_landed(clickup_token, task_id, complete_status, due_before):
            logger.info("Task %s keeps its pending claim for up to %s seconds", task_id, CLAIM_EXPIRY_SECONDS)
            return _result(200, "failed")
        logger.warning("Task %s was completed although the update reported an error", task_id)
    _mark_done(task_id, claim_id, _now())
    logger.info("Completed task %s from reminder %s in %s for user %s", task_id, ts, channel, user)
    return _result(200, "completed")


def _reply(slack_token: str, channel: str, ts: str, text: str) -> bool:
    """Posts `text` in the reminder's thread (never broadcast to the channel): True if Slack accepted it."""
    bot_name = os.environ.get("BOT_NAME") or "PM Bot"
    icon_emoji = os.environ.get("BOT_ICON_EMOJI") or ":hammer_and_wrench:"
    response = slack.send_slack_message(slack_token, channel, text, bot_name, icon_emoji, thread_ts=ts)
    if not (isinstance(response, dict) and response.get("ok")):
        logger.warning("Could not reply in the thread of %s in %s", ts, channel)
        return False
    return True


def _put_reply_marker(pk: str) -> bool | None:
    """
    Writes a reply marker unless it exists: True if written, False if it already existed
    (that reply was sent before), None if DynamoDB failed.
    """
    try:
        _get_table().put_item(
            Item={"pk": pk, "expires_at": _now() + REPLY_MARKER_SECONDS},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except (ClientError, BotoCoreError) as error:
        code = _error_code(error)
        if code == "ConditionalCheckFailedException":
            return False
        logger.error("Could not write reply marker %s: %s", pk, code)
        return None
    return True


def _recurrence(task: dict[str, Any], task_id: str, due_before: str) -> tuple[str, int | None]:
    """
    ("recurred", next due in ms) when the task is open again with a later due date,
    ("closed", None) when it is closed, ("unknown", None) otherwise.
    """
    if task.get("id") != task_id:
        return "unknown", None
    status_type = _as_dict(task.get("status")).get("type")
    if not isinstance(status_type, str):
        return "unknown", None
    if status_type in CLOSED_STATUS_TYPES:
        return "closed", None
    due_after, due_was = _millis(task.get("due_date")), _millis(due_before)
    if due_after is not None and due_was is not None and due_after > due_was:
        return "recurred", due_after
    return "unknown", None


def _completed_text(ctx: _ReplyContext) -> str:
    """The reply after a completion: the next due date, "doesn't repeat", or plain."""
    task_id = ctx.task_id or ""
    if ctx.updated_task:
        state, due = _recurrence(ctx.updated_task, task_id, ctx.due_before)
        if state == "recurred" and due is not None:
            date = _date_or_none(due / 1000)
            return REPLY_COMPLETED_NEXT.format(date=date) if date else REPLY_COMPLETED_PLAIN
    # ClickUp may reopen a recurring task a moment after the update answers.
    time.sleep(RECURRENCE_WAIT_SECONDS)
    try:
        state, due = _recurrence(_as_dict(clickup.get_task(ctx.clickup_token, task_id)), task_id, ctx.due_before)
    except ValueError:
        logger.error("Could not re-read task %s after completing it", task_id)
        state, due = "unknown", None
    if state == "recurred" and due is not None:
        date = _date_or_none(due / 1000)
        return REPLY_COMPLETED_NEXT.format(date=date) if date else REPLY_COMPLETED_PLAIN
    if state == "closed":
        if ctx.frequency.casefold() in NO_FREQUENCY:
            return REPLY_COMPLETED_CLOSED
        logger.warning("Task %s: closed after completion although its frequency says it repeats", task_id)
        return REPLY_COMPLETED_PLAIN
    logger.warning("Task %s: could not tell whether it recurred", task_id)
    return REPLY_COMPLETED_PLAIN


def _already_done_text(epoch_seconds: Any) -> str:
    if isinstance(epoch_seconds, (int, float, Decimal)) and not isinstance(epoch_seconds, bool):
        date = _date_or_none(float(epoch_seconds))
        if date:
            return REPLY_ALREADY_DONE.format(date=date)
    return REPLY_ALREADY_DONE_NO_DATE


def _already_closed_date(ctx: _ReplyContext) -> tuple[bool, Any]:
    """
    For an already-closed task: (duplicate, date). A record for this reminder, in any state,
    is a duplicate. Otherwise the date is the record's completion when it is done, else
    ClickUp's date_closed (epoch seconds), or None.
    """
    try:
        record = _as_dict(
            _get_table().get_item(Key={"pk": f"task#{ctx.task_id}"}, ConsistentRead=True).get("Item")
        )
    except (ClientError, BotoCoreError) as error:
        logger.warning("Could not read the completion record of task %s: %s", ctx.task_id, _error_code(error))
        record = {}
    if record.get("reminder_ts") == ctx.ts:
        return True, None
    dates = [
        millis / 1000
        for millis in (_millis(ctx.task.get("date_closed")), _millis(ctx.task.get("date_done")))
        if millis is not None
    ]
    if record.get("state") == "done" and isinstance(record.get("completed_at"), Decimal):
        dates.append(float(record["completed_at"]))
    # The latest: a task completed from Slack and later reopened and closed by hand shows the hand close.
    return False, max(dates) if dates else None


def _send_reply(ctx: _ReplyContext, result: dict[str, Any]) -> None:
    """Replies in the reminder's thread for the outcomes that get one. Called once, at the end."""
    try:
        body = json.loads(result["body"])
    except (KeyError, TypeError, ValueError):
        return
    outcome = body.get("result")
    if ctx.task_id is None or ctx.slack_token is None or ctx.channel is None or ctx.ts is None:
        return  # Not confirmed as a PM reminder: no reply.
    if outcome not in ("completed", "stale", "already_closed", "failed"):
        return
    if outcome == "failed" and not (isinstance(ctx.event_id, str) and EVENT_ID_PATTERN.fullmatch(ctx.event_id)):
        logger.info("No failure reply for reminder %s: the event has no usable event ID", ctx.ts)
        return
    if ctx.dry_run:
        logger.info("Dry run: would reply %s to %s", outcome, ctx.ts)
        return

    if outcome == "completed":
        text = _completed_text(ctx)
        # Marks this reminder as answered, so a later check mark on it that turns out stale
        # adds no "Already marked done" under the "Marked done". The reply is sent either way.
        _put_reply_marker(f"reply#{ctx.channel}#{ctx.ts}")
    elif outcome == "failed":
        if _put_reply_marker(f"reply#failed#{ctx.event_id}") is False:
            logger.info("Event %r already got a failure reply", ctx.event_id)
            return
        text = REPLY_FAILED
    else:
        if outcome == "stale":
            date = body.get("completed_at")
        else:
            duplicate, date = _already_closed_date(ctx)
            if duplicate:
                logger.info("Task %s: duplicate for reminder %s", ctx.task_id, ctx.ts)
                return
        # The text first, so a bad date can't use up the marker without a reply.
        text = _already_done_text(date)
        written = _put_reply_marker(f"reply#{ctx.channel}#{ctx.ts}")
        if written is not True:
            if written is False:
                logger.info("Reminder %s in %s already got an already-done reply", ctx.ts, ctx.channel)
            return
    if not _reply(ctx.slack_token, ctx.channel, ctx.ts, text):
        return
    logger.info("Replied %s for task %s in the thread of %s in %s", outcome, ctx.task_id, ctx.ts, ctx.channel)


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
    ctx = _ReplyContext(event_id=event_id)
    try:
        result = _handle(inner, item, event_id, ctx)
    except Exception:
        logger.exception("Unexpected error handling event %r", event_id)
        return _result(500, "error")
    # The reply comes after the outcome is recorded, and can't change it.
    try:
        _send_reply(ctx, result)
    except Exception:
        logger.exception("Could not reply for event %r", event_id)
    return result
