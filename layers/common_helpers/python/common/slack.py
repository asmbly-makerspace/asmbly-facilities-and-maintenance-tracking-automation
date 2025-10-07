import requests
import os

# --- Slack API Functions ---

DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'
TEST_CHANNEL_OVERRIDE = os.environ.get('TEST_CHANNEL_OVERRIDE')

def send_message(token, channel_to_attempt, text, bot_name, icon_emoji, thread_ts=None):
    """
    Sends a message to a Slack channel, optionally as a threaded reply.
    """
    if DRY_RUN:
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

def get_user_info(api_token, user_id):
    '''Retrieves user information from Slack.'''
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"user": user_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def open_view(token, trigger_id, view):
    """Opens a view for a user in Slack."""
    url = "https://slack.com/api/views.open"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    payload = {"trigger_id": trigger_id, "view": view}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def update_view(token, view_id, view):
    """Updates an existing view in Slack."""
    url = "https://slack.com/api/views.update"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    payload = {"view_id": view_id, "view": view}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()
