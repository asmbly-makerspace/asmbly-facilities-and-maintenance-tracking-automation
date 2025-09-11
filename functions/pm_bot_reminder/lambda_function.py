import boto3
import json
import os
import requests
import time
from datetime import datetime, timezone, timedelta

# --- Environment Variables ---
# These must be set in the Lambda function's configuration.

# Secret Management: These point to the *names* of the secrets in Secrets Manager
CLICKUP_SECRET_NAME = os.environ.get('CLICKUP_SECRET_NAME')
SLACK_SECRET_NAME = os.environ.get('SLACK_MAINTENANCE_BOT_SECRET_NAME')

# ClickUp Configuration
CLICKUP_LIST_ID = os.environ.get('CLICKUP_LIST_ID')
WORKSPACE_FIELD_NAME = os.environ.get('WORKSPACE_FIELD_NAME', 'Workspace')
ASSET_FIELD_NAME = os.environ.get('ASSET_FIELD_NAME', 'Asset')
FREQUENCY_FIELD_NAME = os.environ.get('FREQUENCY_FIELD_NAME', 'Frequency')

# Slack Configuration
BOT_NAME = os.environ.get('BOT_NAME', 'ClickUp Task Bot')
BOT_ICON_EMOJI = os.environ.get('BOT_ICON_EMOJI', ':robot_face:')
TEST_CHANNEL_OVERRIDE = os.environ.get('TEST_CHANNEL_OVERRIDE') 
WORKSPACES_STR = os.environ.get('WORKSPACES')
GENERAL_CHANNEL_NAME = os.environ.get('GENERAL_CHANNEL_NAME')
STARTER_MESSAGE_TEXT = os.environ.get('STARTER_MESSAGE_TEXT')


def get_secret(secret_name, secret_key):
    """
    Retrieves a specific key from a secret stored in AWS Secrets Manager.
    Assumes the secret is a JSON object.
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

def get_custom_field_value(task, field_name):
    """
    Extracts the value of a named custom field from a ClickUp task object.
    Prioritizes getting the text label for dropdowns.
    """
    custom_fields = task.get('custom_fields', [])
    if not isinstance(custom_fields, list):
        return None

    for field in custom_fields:
        if not isinstance(field, dict) or 'name' not in field:
            continue

        if field.get('name') == field_name:
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
    Fetches all tasks from a ClickUp list, paginating as necessary, with optional date ranges.
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

def process_tasks_for_slack(tasks, workspace_custom_field_name, asset_field_name, frequency_field_name):
    """
    Processes tasks to extract unique channels, asset names, frequency, and prepare follow-up messages.
    """
    unique_channels = set()
    task_followups = []
    tasks_missing_workspace_info = []
    tasks_missing_asset_name_info = []
    tasks_missing_frequency_info = []

    for task in tasks:
        task_id = task.get('id')
        task_name = task.get('name', 'Unnamed Task')
        task_url = task.get('url', '')
        task_status = task.get('status', '') # Get the custom status
        task_description = task.get('text_content') 
        if task_description is None: 
             task_description = task.get('description') 

        workspace_channel = get_custom_field_value(task, workspace_custom_field_name)
        asset_name_value = get_custom_field_value(task, asset_field_name)
        frequency_value = get_custom_field_value(task, frequency_field_name)

        if not (workspace_channel and isinstance(workspace_channel, str) and workspace_channel.strip()):
            reason = "Missing or empty Workspace field"
            if workspace_channel is not None:
                reason = f"Workspace field value '{workspace_channel}' (type: {type(workspace_channel)}) not a usable string"
            tasks_missing_workspace_info.append({'id': task_id, 'name': task_name, 'reason': reason})
            continue

        channel_name = workspace_channel.strip().lstrip('#') 
        unique_channels.add(channel_name)

        if not (asset_name_value and isinstance(asset_name_value, str) and asset_name_value.strip()):
            reason_asset = "Missing or empty Asset Name field"
            if asset_name_value is not None:
                reason_asset = f"Asset Name field value '{asset_name_value}' (type: {type(asset_name_value)}) not a usable string"
            tasks_missing_asset_name_info.append({'id': task_id, 'name': task_name, 'reason': reason_asset})
            final_asset_name = None
        else:
            final_asset_name = asset_name_value.strip()

        if not (frequency_value and isinstance(frequency_value, str) and frequency_value.strip()):
            reason_frequency = "Missing or empty Frequency field"
            if frequency_value is not None:
                reason_frequency = f"Frequency field value '{frequency_value}' (type: {type(frequency_value)}) not a usable string"
            tasks_missing_frequency_info.append({'id': task_id, 'name': task_name, 'reason': reason_frequency})
            final_frequency = None
        else:
            final_frequency = frequency_value.strip()

        task_followups.append({
            'channel': channel_name,
            'asset_name': final_asset_name,
            'frequency': final_frequency,
            'task_id': task_id,
            'task_name': task_name,
            'task_url': task_url,
            'task_status': task_status,
            'task_description': task_description.strip() if task_description else None
        })
            
    return list(unique_channels), task_followups, tasks_missing_workspace_info, tasks_missing_asset_name_info, tasks_missing_frequency_info


# --- Slack Functions ---

def send_slack_message(token, channel_to_attempt, text, bot_name, icon_emoji, thread_ts=None):
    """
    Sends a message to a Slack channel, optionally as a threaded reply.
    """
    slack_api_url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    final_target_channel = TEST_CHANNEL_OVERRIDE if TEST_CHANNEL_OVERRIDE else channel_to_attempt
    
    clean_final_target_channel = None
    if final_target_channel and isinstance(final_target_channel, str):
         temp_cleaned = final_target_channel.strip().lstrip('#')
         if temp_cleaned and temp_cleaned[0].upper() in ('C', 'G', 'D', 'U'):
              clean_final_target_channel = temp_cleaned
         elif temp_cleaned:
              clean_final_target_channel = temp_cleaned.lower()
         
    if not clean_final_target_channel:
        error_msg = f"Cannot send Slack message: Final target channel is invalid or None. (Attempted: {channel_to_attempt}, Override: {TEST_CHANNEL_OVERRIDE})."
        print(error_msg)
        return {"ok": False, "error": "invalid_final_target_channel", "error_message": error_msg}

    payload = {
        "channel": clean_final_target_channel,
        "text": text,
        "username": bot_name,
        "icon_emoji": icon_emoji,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        print(f"Attempting Slack API call with payload: {json.dumps(payload)}") 
        response = requests.post(slack_api_url, headers=headers, json=payload)
        response_data = response.json()

        if response_data.get("ok"):
            response_data["channel_sent_to_name_or_id"] = clean_final_target_channel 
            return response_data 
        else:
            response_data["channel_attempted"] = clean_final_target_channel
            print(f"Slack API Error Response: {response_data}")
            return response_data
    except Exception as e:
        print(f"Network or script error sending to {clean_final_target_channel}: {e}")
        return {"ok": False, "error": "script_error", "error_message": str(e), "channel_attempted": clean_final_target_channel}

def handle_starter_messages(slack_bot_token, bot_name, bot_icon_emoji, channel_list_input, starter_message_text, parsed_workspaces, general_channel_name):
    starter_message_results = []
    if not (channel_list_input and starter_message_text):
        print("Starter messages: 'channel_list' or 'starter_message' not provided. Skipping.")
        return starter_message_results

    starter_channels_orig = []
    if isinstance(channel_list_input, str):
        starter_channels_orig = [ch.strip() for ch in channel_list_input.split(',') if ch.strip()]
    elif isinstance(channel_list_input, list):
        starter_channels_orig = [str(ch).strip() for ch in channel_list_input if str(ch).strip()]
    
    if not starter_channels_orig:
        print("Starter messages: No valid channels found in 'channel_list_input'.")
        return starter_message_results

    print(f"Starter messages: Processing {len(starter_channels_orig)} original channel(s).")
    for original_channel in starter_channels_orig:
        channel_to_attempt_api_call = original_channel
        is_redirected = False
        original_channel_check = original_channel.strip().lstrip('#').lower() if original_channel else ""

        if not TEST_CHANNEL_OVERRIDE and parsed_workspaces:
            if not (original_channel_check and original_channel_check in parsed_workspaces):
                if general_channel_name and general_channel_name.strip():
                    channel_to_attempt_api_call = general_channel_name
                    is_redirected = True
                else:
                    print(f"Skipping starter message for '{original_channel}': Not in workspaces and no general_channel_name configured.")
                    starter_message_results.append({"original_channel": original_channel, "status": "skipped_routing"})
                    continue
        
        response_data = send_slack_message(slack_bot_token, channel_to_attempt_api_call, starter_message_text, bot_name, bot_icon_emoji)
        
        result_entry = {
            "original_channel": original_channel,
            "sent_to_channel": response_data.get("channel_sent_to_name_or_id", response_data.get("channel_attempted", "Unknown")),
            "is_redirected_by_routing": is_redirected,
            "status": "success" if response_data.get("ok") else "error",
            "response_details": response_data
        }
        starter_message_results.append(result_entry)
        
        # Add a pause to respect Slack's rate limits
        time.sleep(1)
        
    return starter_message_results

def handle_task_followups(slack_bot_token, bot_name, bot_icon_emoji, task_followup_list, parsed_workspaces, general_channel_name):
    task_followup_results = []
    if not task_followup_list:
        print("Task follow-ups: No tasks found. Skipping.")
        return task_followup_results

    print(f"Task follow-ups: Processing {len(task_followup_list)} task(s).")
    for task_item in task_followup_list:
        original_channel = task_item.get('channel')
        channel_to_attempt_api_call = original_channel
        is_redirected = False
        original_channel_check = original_channel.strip().lstrip('#').lower() if original_channel else ""

        if not TEST_CHANNEL_OVERRIDE and parsed_workspaces:
            if not (original_channel_check and original_channel_check in parsed_workspaces):
                if general_channel_name and general_channel_name.strip():
                    channel_to_attempt_api_call = general_channel_name
                    is_redirected = True
                else:
                    print(f"Skipping task ID {task_item.get('task_id')}: Not in workspaces and no general channel configured.")
                    task_followup_results.append({"task_id": task_item.get('task_id'), "status": "skipped_routing"})
                    continue
        
        status_prefix = f"[{task_item.get('task_status').upper()}] " if task_item.get('task_status') else ""
        main_message_text = (
            f"{status_prefix}{original_channel or 'Unknown'} - {task_item.get('asset_name', 'N/A')} - "
            f"{task_item.get('task_name', 'N/A')} - Frequency: {task_item.get('frequency')} - "
            f"ClickUp ID: {task_item.get('task_id')}"
        )
        main_message_response = send_slack_message(slack_bot_token, channel_to_attempt_api_call, main_message_text, bot_name, bot_icon_emoji)
        
        current_task_results = {
            "task_id": task_item.get('task_id'),
            "original_channel": original_channel,
            "sent_to_channel": main_message_response.get("channel_sent_to_name_or_id", "Unknown"),
            "main_message_status": "success" if main_message_response.get("ok") else "error",
            "thread_message_status": "not_attempted"
        }

        if main_message_response.get("ok"):
            task_description = task_item.get('task_description')
            if task_description and task_description.strip():
                # Add a small delay before sending the threaded reply
                time.sleep(1)
                thread_response = send_slack_message(
                    slack_bot_token,
                    main_message_response.get("channel"), # Use channel ID from response
                    task_description,
                    bot_name,
                    bot_icon_emoji,
                    thread_ts=main_message_response.get("ts")
                )
                current_task_results["thread_message_status"] = "success" if thread_response.get("ok") else "error"
        
        task_followup_results.append(current_task_results)
        
        # Add a pause to respect Slack's rate limits
        time.sleep(1)
        
    return task_followup_results


# --- AWS Lambda Handler ---

def lambda_handler(event, context):
    """
    Main function executed by AWS Lambda.
    """
    print("--- Lambda execution started. ---")
    
    # --- 1. Load Configuration and Secrets ---
    try:
        if not all([CLICKUP_SECRET_NAME, SLACK_SECRET_NAME, CLICKUP_LIST_ID]):
            raise ValueError("Missing critical environment variables: CLICKUP_SECRET_NAME, SLACK_MAINTENANCE_BOT_SECRET_NAME, or CLICKUP_LIST_ID")
            
        print("Fetching secrets from AWS Secrets Manager...")
        clickup_api_token = get_secret(CLICKUP_SECRET_NAME, secret_key='CLICKUP_API_TOKEN')
        slack_bot_token = get_secret(SLACK_SECRET_NAME, secret_key='SLACK_MAINTENANCE_BOT_TOKEN')
        print("Secrets loaded successfully.")

    except Exception as e:
        print(f"FATAL: Failed during configuration or secret retrieval: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Configuration error: {e}")}

    # --- 2. Fetch and Process Tasks from ClickUp ---
    try:
        now_utc = datetime.now(timezone.utc)
        one_week_from_now_utc = now_utc + timedelta(days=7)
        
        now_ms = int(now_utc.timestamp() * 1000)
        one_week_ms = int(one_week_from_now_utc.timestamp() * 1000)

        # A. Fetch overdue tasks (due date is in the past)
        print("Fetching overdue tasks...")
        overdue_tasks = get_all_clickup_tasks(CLICKUP_LIST_ID, clickup_api_token, due_date_lt_ms=now_ms)
        for task in overdue_tasks:
            task['status'] = 'Overdue'
        print(f"Found {len(overdue_tasks)} overdue tasks.")

        # B. Fetch upcoming tasks (due date is between now and 1 week from now)
        print("Fetching upcoming tasks for the next 7 days...")
        upcoming_tasks = get_all_clickup_tasks(
            CLICKUP_LIST_ID, clickup_api_token, 
            due_date_gt_ms=now_ms, 
            due_date_lt_ms=one_week_ms
        )
        for task in upcoming_tasks:
            task['status'] = 'Upcoming'
        print(f"Found {len(upcoming_tasks)} upcoming tasks.")

        # C. Combine the lists first
        all_tasks = overdue_tasks + upcoming_tasks
        
        # D. Sort the combined list by Asset Name
        print("Sorting all tasks by asset name...")
        all_tasks.sort(key=lambda task: get_custom_field_value(task, ASSET_FIELD_NAME) or '')
        
        if not all_tasks:
            print("No tasks found meeting the criteria. Exiting successfully.")
            return {"statusCode": 200, "body": json.dumps("No tasks to process.")}

        print("Processing all tasks for Slack...")
        unique_channels, task_followups, _, _, _ = process_tasks_for_slack(
            all_tasks, WORKSPACE_FIELD_NAME, ASSET_FIELD_NAME, FREQUENCY_FIELD_NAME
        )
        print(f"Found {len(unique_channels)} unique channels and {len(task_followups)} tasks with valid workspace data.")
        
    except Exception as e:
        print(f"FATAL: Failed during ClickUp API interaction: {e}")
        return {"statusCode": 500, "body": json.dumps(f"ClickUp API error: {e}")}

    # --- 3. Send Messages to Slack ---
    try:
        parsed_workspaces = [ch.strip().lstrip('#').lower() for ch in WORKSPACES_STR.split(',')] if WORKSPACES_STR else []
        if parsed_workspaces:
            print(f"Workspace routing is active for: {parsed_workspaces}")

        if STARTER_MESSAGE_TEXT:
            print("Handling starter messages...")
            # Un-escape the newline characters for proper formatting in Slack
            formatted_starter_message = STARTER_MESSAGE_TEXT.replace('\\n', '\n')
            handle_starter_messages(
                slack_bot_token, BOT_NAME, BOT_ICON_EMOJI, 
                list(unique_channels), formatted_starter_message,
                parsed_workspaces, GENERAL_CHANNEL_NAME
            )
        
        print("Handling task follow-up messages...")
        handle_task_followups(
            slack_bot_token, BOT_NAME, BOT_ICON_EMOJI,
            task_followups,
            parsed_workspaces, GENERAL_CHANNEL_NAME
        )
        
    except Exception as e:
        print(f"FATAL: Failed during Slack API interaction: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Slack API error: {e}")}


    print("--- Lambda execution finished successfully. ---")
    return {
        "statusCode": 200,
        "body": json.dumps(f"Successfully processed {len(task_followups)} tasks.")
    }