import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

_SLACK_ERROR_PATTERN = re.compile(r"[a-z0-9_]{1,64}")


def _slack_error_for_log(response_data: Any) -> str | None:
    """Return Slack's error code from a response if it looks like one, '<invalid>' if not."""
    if not isinstance(response_data, dict) or "error" not in response_data:
        return None
    error = response_data["error"]
    if isinstance(error, str) and _SLACK_ERROR_PATTERN.fullmatch(error):
        return error
    return "<invalid>"

# Seconds per request (to connect, and between bytes of the answer): under the
# 10-second limit of the shortest function that calls Slack through this module.
DEFAULT_TIMEOUT_SECONDS = 8.0

TEST_CHANNEL_OVERRIDE = os.environ.get('TEST_CHANNEL_OVERRIDE')


class SlackState:
    """A helper to safely access values from Slack's view state."""

    def __init__(self, state_values):
        self.values = state_values or {}

    def get_value(self, block_id, action_id, attribute="value"):
        try:
            return self.values[block_id][action_id][attribute]
        except (KeyError, TypeError):
            return None

    def get_selected_option_value(self, block_id, action_id):
        try:
            return self.values[block_id][action_id]["selected_option"]["value"]
        except (KeyError, TypeError):
            return None


def send_slack_message(
    token: str,
    channel_to_attempt: str,
    text: str,
    bot_name: str,
    icon_emoji: str,
    *,
    dry_run: bool = False,
    thread_ts: str | None = None,
) -> Any:
    """
    Sends a message to a Slack channel, optionally as a threaded reply.
    If dry_run is True, it prints the message instead of sending it.
    """
    if dry_run:
        print("--- DRY RUN MODE ---")
        print(f"Would send to channel: {channel_to_attempt}")
        print(f"Message: {text}")
        return {"ok": True, "ts": "DRY_RUN_TIMESTAMP", "channel": channel_to_attempt}

    slack_api_url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    final_target_channel = TEST_CHANNEL_OVERRIDE if TEST_CHANNEL_OVERRIDE else channel_to_attempt

    payload = {
        "channel": final_target_channel.strip().lstrip('#'),
        "text": text,
        "username": bot_name,
        "icon_emoji": icon_emoji,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        response = requests.post(slack_api_url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT_SECONDS)
        response_data = response.json()
        if not response_data.get("ok"):
            logger.error(
                "Slack chat.postMessage to %s failed: %s", final_target_channel, _slack_error_for_log(response_data)
            )
        return response_data
    except Exception as e:
        logger.error("Slack chat.postMessage to %s failed: %s", final_target_channel, type(e).__name__)
        return {"ok": False, "error": "script_error"}


def get_slack_post_url(slack_workspace_url: str | None, channel_id: str, message_ts: str) -> str | None:
    """Constructs the permalink for a Slack message."""
    if not slack_workspace_url:
        logger.warning("slack_workspace_url was not provided. Cannot generate permalink.")
        return None
    # Timestamp needs to be without the dot for the URL
    ts_for_url = message_ts.replace('.', '')
    return f"{slack_workspace_url}/archives/{channel_id}/p{ts_for_url}"


def get_slack_user_info(api_token: str, user_id: str, http_session: requests.Session | None = None) -> Any:
    '''Retrieves user information from Slack. A failed request is logged and re-raised.'''
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"user": user_id}

    session = http_session or requests.Session()

    try:
        response = session.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Slack users.info failed: %s", type(e).__name__)
        raise
    return response.json()
