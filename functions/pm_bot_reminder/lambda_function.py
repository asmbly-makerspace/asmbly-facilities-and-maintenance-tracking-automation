import json
import os
import time
from datetime import datetime, timezone, timedelta

from common import aws, clickup, slack

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

def process_tasks_for_slack(tasks, workspace_field_id, asset_field_id, frequency_field_id):
    """
    Processes tasks to extract data and prepare follow-up messages using field IDs.
    """
    unique_channels = set()
    task_followups = []

    for task in tasks:
        workspace_channel_original = clickup.get_custom_field_value(task, workspace_field_id)

        # Skip tasks that don't have a workspace value
        if not (workspace_channel_original and isinstance(workspace_channel_original, str) and workspace_channel_original.strip()):
            continue

        # Transform the channel name to match Slack's format.
        # Converts "3D Printing" to "3d-printing"
        channel_name = workspace_channel_original.strip().lower().replace(' ', '-')

        unique_channels.add(channel_name)

        task_followups.append({
            'channel': channel_name,
            'asset_name': clickup.get_custom_field_value(task, asset_field_id),
            'frequency': clickup.get_custom_field_value(task, frequency_field_id),
            'task_id': task.get('id'),
            'task_name': task.get('name', 'Unnamed Task'),
            'task_url': task.get('url', ''),
            'time_status': task.get('time_status', ''),
            'task_description': task.get('text_content') or task.get('description')
        })

    return list(unique_channels), task_followups

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
        clickup_api_token = aws.get_secret(CLICKUP_SECRET_NAME, secret_key='CLICKUP_API_TOKEN')
        slack_bot_token = aws.get_secret(SLACK_SECRET_NAME, secret_key='SLACK_MAINTENANCE_BOT_TOKEN')
        print("Secrets loaded successfully.")

        # --- 2. Fetch and Process Tasks from ClickUp ---
        now_utc = datetime.now(timezone.utc)
        one_week_from_now_utc = now_utc + timedelta(days=7)
        now_ms = int(now_utc.timestamp() * 1000)
        one_week_ms = int(one_week_from_now_utc.timestamp() * 1000)

        print("Fetching overdue tasks...")
        overdue_tasks = clickup.get_all_tasks(
            CLICKUP_LIST_ID, 
            clickup_api_token, 
            params={"due_date_lt": now_ms, "include_subtasks": "false", "include_closed": "false"}
        )
        for task in overdue_tasks:
            task['time_status'] = 'Overdue'
        print(f"Found {len(overdue_tasks)} overdue tasks.")

        print("Fetching upcoming tasks for the next 7 days...")
        upcoming_tasks = clickup.get_all_tasks(
            CLICKUP_LIST_ID, 
            clickup_api_token,
            params={"due_date_gt": now_ms, "due_date_lt": one_week_ms, "include_subtasks": "false", "include_closed": "false"}
        )
        for task in upcoming_tasks:
            task['time_status'] = 'Upcoming'
        print(f"Found {len(upcoming_tasks)} upcoming tasks.")

        all_tasks = overdue_tasks + upcoming_tasks

        if not all_tasks:
            print("No tasks found meeting the criteria. Exiting successfully.")
            return {"statusCode": 200, "body": json.dumps("No tasks to process.")}

        print("Sorting all tasks by asset name...")
        all_tasks.sort(key=lambda task: clickup.get_custom_field_value(task, CLICKUP_ASSET_FIELD_ID) or '')

        print("Processing all tasks for Slack...")
        unique_channels, task_followups = process_tasks_for_slack(
            all_tasks, CLICKUP_WORKSPACE_FIELD_ID, CLICKUP_ASSET_FIELD_ID, CLICKUP_FREQUENCY_FIELD_ID
        )
        print(f"Found {len(unique_channels)} unique channels and {len(task_followups)} tasks with valid workspace data.")

        # --- 3. Send Messages to Slack ---
        print(f"Task followups to process: {len(task_followups)}")

        for task in task_followups:
            # Build the main message
            message = (
               f"[{task.get('time_status', '').upper()}] {task.get('channel', 'Unknown')} - {task.get('asset_name', 'N/A')} - "
               f"{task.get('task_name', 'N/A')} - "
               f"Frequency: {task.get('frequency', 'N/A')} - "
               f"ClickUp ID: {task.get('task_id', 'N/A')}"
            )

            print(f"Attempting to send message to Slack channel: #{task['channel']}")

            # Send the main message and capture the response
            main_message_response = slack.send_message(slack_bot_token, task['channel'], message, BOT_NAME, BOT_ICON_EMOJI)

            # Check if the main message was sent successfully and if a description exists
            task_description = task.get('task_description')
            if main_message_response.get("ok") and task_description and task_description.strip():
                parent_message_ts = main_message_response.get("ts")
                channel_id = main_message_response.get("channel")

                # Add a small delay before sending the threaded reply
                time.sleep(1)

                # Send the description as a threaded reply
                slack.send_message(
                    token=slack_bot_token,
                    channel_to_attempt=channel_id,
                    text=task_description,
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
        "body": json.dumps(f"Successfully processed {len(task_followups)} tasks.")
    }
