import json
import os
import requests # type: ignore
from dataclasses import dataclass
import time
from datetime import datetime, timezone, timedelta

from common.aws import get_secret
from common.clickup import get_all_clickup_tasks, get_custom_field_value, ClickUpTask

# --- Environment Variables ---
# These are set in the Lambda function's configuration (template.yaml)
CLICKUP_SECRET_NAME = os.environ.get('CLICKUP_SECRET_NAME')
SLACK_SECRET_NAME = os.environ.get('SLACK_MAINTENANCE_BOT_SECRET_NAME')
CLICKUP_LIST_ID = os.environ.get('CLICKUP_LIST_ID')
CLICKUP_WORKSPACE_FIELD_ID = os.environ.get('CLICKUP_WORKSPACE_FIELD_ID')
CLICKUP_ASSET_FIELD_ID = os.environ.get('CLICKUP_ASSET_FIELD_ID')
CLICKUP_FREQUENCY_FIELD_ID = os.environ.get('CLICKUP_FREQUENCY_FIELD_ID')
BOT_NAME = os.environ.get('BOT_NAME', 'ClickUp Task Bot')
BOT_ICON_EMOJI = os.environ.get('BOT_ICON_EMOJI', ':robot_face:')
TEST_CHANNEL_OVERRIDE = os.environ.get('TEST_CHANNEL_OVERRIDE')
WORKSPACES_STR = os.environ.get('WORKSPACES')
GENERAL_CHANNEL_NAME = os.environ.get('GENERAL_CHANNEL_NAME')
STARTER_MESSAGE_TEXT = os.environ.get('STARTER_MESSAGE_TEXT')
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

def process_tasks_for_slack(tasks, workspace_field_id, asset_field_id, frequency_field_id):
    """
    Processes tasks to extract data and prepare follow-up messages using field IDs.
    """
    unique_channels = set()
    processed_tasks = []

    for task in tasks:
        workspace_channel_original = get_custom_field_value(task, workspace_field_id)

        # Skip tasks that don't have a workspace value
        if not workspace_channel_original:
            continue

        # Transform the channel name to match Slack's format.
        # Converts "3D Printing" to "3d-printing"
        channel_name = workspace_channel_original.strip().lower().replace(' ', '-')
        unique_channels.add(channel_name)

        processed_tasks.append(ClickUpTask(
            channel=channel_name,
            asset_name=get_custom_field_value(task, asset_field_id),
            frequency=get_custom_field_value(task, frequency_field_id),
            task_id=task.get('id', 'N/A'),
            task_name=task.get('name', 'Unnamed Task'),
            task_url=task.get('url', ''),
            time_status=task.get('time_status', ''),
            task_description=task.get('text_content') or task.get('description')
        ))

    return list(unique_channels), processed_tasks

# --- Slack Functions ---

def send_slack_message(token, channel_to_attempt, text, bot_name, icon_emoji, thread_ts=None):
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

def format_slack_message(task: ClickUpTask) -> str:
    """Formats the main Slack message for a given task."""
    time_status = task.time_status.upper() if task.time_status else 'UNKNOWN'
    asset_name = task.asset_name or 'N/A'
    task_name = task.task_name or 'N/A'
    frequency = task.frequency or 'N/A'
    task_id = task.task_id or 'N/A'

    return (f"[{time_status}] {task.channel} - {asset_name} - "
            f"{task_name} - Frequency: {frequency} - "
            f"ClickUp ID: {task_id}")

# --- AWS Lambda Handler ---

def lambda_handler(event, context):
    """
    Main function executed by AWS Lambda.
    """
    print("--- HANDLER STARTED ---")

    try:
        # --- 1. Load Configuration and Secrets ---
        if not all([CLICKUP_SECRET_NAME, SLACK_SECRET_NAME, CLICKUP_LIST_ID, CLICKUP_WORKSPACE_FIELD_ID, CLICKUP_ASSET_FIELD_ID, CLICKUP_FREQUENCY_FIELD_ID]):
            raise ValueError("Missing critical environment variables...")

        print("Fetching secrets from AWS Secrets Manager...")
        clickup_api_token = get_secret(CLICKUP_SECRET_NAME, secret_key='CLICKUP_API_TOKEN')
        slack_bot_token = get_secret(SLACK_SECRET_NAME, secret_key='SLACK_MAINTENANCE_BOT_TOKEN')
        print("Secrets loaded successfully.")

        # --- 2. Fetch and Process Tasks from ClickUp ---
        now_utc = datetime.now(timezone.utc)
        one_week_from_now_utc = now_utc + timedelta(days=7)
        now_ms = int(now_utc.timestamp() * 1000)
        one_week_ms = int(one_week_from_now_utc.timestamp() * 1000)

        print("Fetching overdue tasks...")
        overdue_tasks = get_all_clickup_tasks(CLICKUP_LIST_ID, clickup_api_token, due_date_lt_ms=now_ms)
        for task in overdue_tasks:
            task['time_status'] = 'Overdue'
        print(f"Found {len(overdue_tasks)} overdue tasks.")

        print("Fetching upcoming tasks for the next 7 days...")
        upcoming_tasks = get_all_clickup_tasks(
            CLICKUP_LIST_ID, clickup_api_token,
            due_date_gt_ms=now_ms,
            due_date_lt_ms=one_week_ms
        )
        for task in upcoming_tasks:
            task['time_status'] = 'Upcoming'
        print(f"Found {len(upcoming_tasks)} upcoming tasks.")

        all_tasks = overdue_tasks + upcoming_tasks

        if not all_tasks:
            print("No tasks found meeting the criteria. Exiting successfully.")
            return {"statusCode": 200, "body": json.dumps("No tasks to process.")}

        print("Sorting all tasks by asset name...")
        all_tasks.sort(key=lambda task: (get_custom_field_value(task, CLICKUP_ASSET_FIELD_ID) or '', task.get('name', '')))

        print("Processing all tasks for Slack...")
        unique_channels, processed_tasks = process_tasks_for_slack(
            all_tasks, CLICKUP_WORKSPACE_FIELD_ID, CLICKUP_ASSET_FIELD_ID, CLICKUP_FREQUENCY_FIELD_ID
        )
        print(f"Found {len(unique_channels)} unique channels and {len(processed_tasks)} tasks with valid workspace data.")

        # --- 3. Send Messages to Slack ---
        print(f"Tasks to process for Slack: {len(processed_tasks)}")

        for task in processed_tasks:
            message = format_slack_message(task)
            print(f"Attempting to send message to Slack channel: #{task.channel}")

            # Send the main message and capture the response
            main_message_response = send_slack_message(
                token=slack_bot_token,
                channel_to_attempt=task.channel,
                text=message,
                bot_name=BOT_NAME,
                icon_emoji=BOT_ICON_EMOJI
            )

            # Check if the main message was sent successfully and if a description exists
            if main_message_response.get("ok") and task.task_description and task.task_description.strip():
                parent_message_ts = main_message_response.get("ts")
                # Use the channel ID from the response for threaded replies
                channel_id = main_message_response.get("channel")

                # Add a small delay before sending the threaded reply
                time.sleep(1)

                print(f"Sending threaded reply for task {task.task_id} in channel {channel_id}")

                # Send the description as a threaded reply
                send_slack_message(
                    token=slack_bot_token,
                    channel_to_attempt=channel_id, # Use channel ID for replies
                    text=task.task_description,
                    bot_name=BOT_NAME,
                    icon_emoji=BOT_ICON_EMOJI,
                    thread_ts=parent_message_ts
                )

            # Main rate-limiting delay between processing each task
            time.sleep(1)

    except Exception as e:
        print(f"--- FATAL ERROR in handler: {str(e)} ---")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps(f"Error: {str(e)}")}

    print("--- HANDLER FINISHED SUCCESSFULLY ---")
    return {
        "statusCode": 200,
        "body": json.dumps(f"Successfully processed {len(processed_tasks)} tasks.")
    }
