import boto3
import json
import os
import requests
import time
from datetime import datetime, timezone, timedelta

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

def get_secret(secret_name, secret_key):
    """
    Retrieves a specific key from a secret stored in AWS Secrets Manager.
    """
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager')
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        secret_dict = json.loads(secret_string)

        if secret_key in secret_dict:
            return secret_dict[secret_key]
        else:
            raise KeyError(f"Key '{secret_key}' not found in secret '{secret_name}'")

    except Exception as e:
        print(f"ERROR: Unable to retrieve secret '{secret_name}' with key '{secret_key}': {e}")
        raise e

# --- ClickUp Functions ---

def get_custom_field_value(task, field_id):
    """
    Extracts the value of a custom field from a ClickUp task object using its ID.
    """
    if not field_id:
        return None

    custom_fields = task.get('custom_fields', [])
    if not isinstance(custom_fields, list):
        return None

    for field in custom_fields:
        if not isinstance(field, dict) or 'id' not in field:
            continue

        if field.get('id') == field_id:
            field_value = field.get('value')

            if field_value is None:
                return None

            if field.get('type') == 'drop_down' and isinstance(field_value, (str, int)):
                type_config = field.get('type_config', {})
                options = type_config.get('options', [])
                try:
                    if isinstance(field_value, str):
                        for option in options:
                            if option.get('id') == field_value:
                                return option.get('name')
                    val_as_int = int(field_value)
                    for option in options:
                        if option.get('orderindex') == val_as_int:
                            return option.get('name')
                except (ValueError, TypeError):
                    pass
                return None

            if isinstance(field_value, str):
                return field_value.strip()

            if isinstance(field_value, list) and len(field_value) > 0:
                if all(isinstance(item, str) for item in field_value):
                    return ", ".join(item.strip() for item in field_value)
                return None

            if isinstance(field_value, (int, float)):
                 return str(field_value)

            if isinstance(field_value, bool):
                 return str(field_value)

            return None

    return None

def fetch_clickup_tasks_page(list_id, api_token, page_num, due_date_lt_ms=None, due_date_gt_ms=None, include_subtasks=False, include_closed=False):
    """
    Fetches a single page of tasks from the ClickUp API with optional date ranges.
    """
    base_url = "https://api.clickup.com/api/v2"
    endpoint = f"{base_url}/list/{list_id}/task"
    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }
    query_params = {
        "archived": "false",
        "page": page_num,
        "subtasks": str(include_subtasks).lower(),
        "include_closed": str(include_closed).lower(),
    }
    if due_date_lt_ms is not None:
        query_params["due_date_lt"] = due_date_lt_ms
    if due_date_gt_ms is not None:
        query_params["due_date_gt"] = due_date_gt_ms

    try:
        response = requests.get(endpoint, headers=headers, params=query_params)
        response.raise_for_status()
        data = response.json()
        tasks_on_page = data.get('tasks', [])
        is_last_page = data.get('last_page', True) if not tasks_on_page else data.get('last_page', False)
        return tasks_on_page, is_last_page
    except requests.exceptions.HTTPError as e:
        error_message = f"ClickUp API HTTP Error: {e.response.status_code} {e.response.reason}"
        try:
            error_details = e.response.json()
            error_message += f" - Details: {json.dumps(error_details)}"
        except ValueError:
            error_message += f" - Response body: {e.response.text}"
        print(error_message)
        raise ValueError(error_message)
    except requests.exceptions.RequestException as e:
        error_message = f"Network error fetching tasks from ClickUp: {str(e)}"
        print(error_message)
        raise ValueError(error_message)

def get_all_clickup_tasks(list_id, api_token, due_date_lt_ms=None, due_date_gt_ms=None, max_pages=20):
    """
    Fetches all tasks from a ClickUp list, paginating as necessary.
    """
    all_tasks = []
    current_page = 0
    include_subtasks = False
    include_closed = False

    while True:
        if current_page >= max_pages:
            print(f"Reached maximum page limit ({max_pages}). Stopping task fetch.")
            break

        tasks_on_page, is_last_page = fetch_clickup_tasks_page(
            list_id, api_token, current_page,
            due_date_lt_ms=due_date_lt_ms, due_date_gt_ms=due_date_gt_ms,
            include_subtasks=include_subtasks, include_closed=include_closed
        )

        if tasks_on_page is None:
            break

        all_tasks.extend(tasks_on_page)

        if is_last_page or not tasks_on_page:
            break

        current_page += 1

    return all_tasks

def process_tasks_for_slack(tasks, workspace_field_id, asset_field_id, frequency_field_id):
    """
    Processes tasks to extract data and prepare follow-up messages using field IDs.
    """
    unique_channels = set()
    task_followups = []

    for task in tasks:
        workspace_channel_original = get_custom_field_value(task, workspace_field_id)

        # Skip tasks that don't have a workspace value
        if not (workspace_channel_original and isinstance(workspace_channel_original, str) and workspace_channel_original.strip()):
            continue

        # Transform the channel name to match Slack's format.
        # Converts "3D Printing" to "3d-printing"
        channel_name = workspace_channel_original.strip().lower().replace(' ', '-')

        unique_channels.add(channel_name)

        task_followups.append({
            'channel': channel_name,
            'asset_name': get_custom_field_value(task, asset_field_id),
            'frequency': get_custom_field_value(task, frequency_field_id),
            'task_id': task.get('id'),
            'task_name': task.get('name', 'Unnamed Task'),
            'task_url': task.get('url', ''),
            'time_status': task.get('time_status', ''),
            'task_description': task.get('text_content') or task.get('description')
        })

    return list(unique_channels), task_followups

    return list(unique_channels), task_followups

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

def handle_starter_messages(slack_bot_token, bot_name, bot_icon_emoji, channel_list, starter_message, parsed_workspaces, general_channel):
    # This function can be filled in or expanded based on requirements
    pass

def handle_task_followups(slack_bot_token, bot_name, bot_icon_emoji, task_list, parsed_workspaces, general_channel):
    # This function can be filled in or expanded based on requirements
    pass

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
        unique_channels, task_followups = process_tasks_for_slack(
            all_tasks, CLICKUP_WORKSPACE_FIELD_ID, CLICKUP_ASSET_FIELD_ID, CLICKUP_FREQUENCY_FIELD_ID
        )
        print(f"Found {len(unique_channels)} unique channels and {len(task_followups)} tasks with valid workspace data.")

        # --- 3. Send Messages to Slack ---
        print(f"Task followups to process: {len(task_followups)}")

        # +++ UPDATED THIS LOOP TO HANDLE THREADED REPLIES +++
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
            main_message_response = send_slack_message(
                token=slack_bot_token,
                channel_to_attempt=task['channel'],
                text=message,
                bot_name=BOT_NAME,
                icon_emoji=BOT_ICON_EMOJI
            )

            # Check if the main message was sent successfully and if a description exists
            task_description = task.get('task_description')
            if main_message_response.get("ok") and task_description and task_description.strip():
                parent_message_ts = main_message_response.get("ts")
                channel_id = main_message_response.get("channel")

                # Add a small delay before sending the threaded reply
                time.sleep(1)

                # Send the description as a threaded reply
                send_slack_message(
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