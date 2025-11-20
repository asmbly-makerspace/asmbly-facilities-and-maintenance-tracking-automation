import os
import requests

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


def send_slack_message(token, channel_to_attempt, text, bot_name, icon_emoji, *, dry_run=False, thread_ts=None):
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
        response = requests.post(slack_api_url, headers=headers, json=payload)
        response_data = response.json()
        if not response_data.get("ok"):
            print(f"Slack API Error Response: {response_data}")
        return response_data
    except Exception as e:
        print(f"Network or script error sending to {final_target_channel}: {e}")
        return {"ok": False, "error": "script_error", "error_message": str(e)}


def get_slack_post_url(slack_workspace_url, channel_id, message_ts):
    """Constructs the permalink for a Slack message."""
    if not slack_workspace_url:
        print("slack_workspace_url was not provided. Cannot generate permalink.")
        return None
    # Timestamp needs to be without the dot for the URL
    ts_for_url = message_ts.replace('.', '')
    return f"{slack_workspace_url}/archives/{channel_id}/p{ts_for_url}"


def get_slack_user_info(api_token, user_id, http_session=None):
    '''Retrieves user information from Slack.'''
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"user": user_id}

    session = http_session or requests.Session()

    response = session.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()
