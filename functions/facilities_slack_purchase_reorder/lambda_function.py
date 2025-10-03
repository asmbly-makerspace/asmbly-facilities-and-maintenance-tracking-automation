import json
import os
import boto3
import requests
import urllib.parse

# Environment variables
CLICKUP_API_TOKEN_SECRET_NAME = os.environ["CLICKUP_SECRET_NAME"]
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"]
CLICKUP_LIST_ID = os.environ["LIST_ID"]

# AWS Secrets Manager client
secrets_manager = boto3.client("secretsmanager")

def get_secret(secret_name):
    """Retrieves a secret from AWS Secrets Manager."""
    try:
        response = secrets_manager.get_secret_value(SecretId=secret_name)
        secret_string = response["SecretString"]
        secret_data = json.loads(secret_string)
        if isinstance(secret_data, dict):
            return list(secret_data.values())[0]
        return secret_string
    except (json.JSONDecodeError):
        return secret_string

def get_clickup_tasks(api_token, list_id):
    """Fetches tasks from a ClickUp list."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["tasks"]

def get_clickup_task_details(api_token, task_id):
    """Fetches the full details for a single ClickUp task, including the description."""
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_workspace_name_from_task(task):
    """Helper function to extract the workspace name from a task's custom fields."""
    for field in task.get("custom_fields", []):
        if field.get("name") == "Workspace" and field.get("value") is not None:
            try:
                selected_index = int(field.get("value"))
                options = field.get("type_config", {}).get("options", [])
                matching_option = next((opt for opt in options if opt.get("orderindex") == selected_index), None)
                if matching_option:
                    return matching_option.get("name")
            except (ValueError, TypeError):
                continue
    return None

def get_all_workspaces_from_tasks(tasks):
    """Extracts a unique, sorted list of all workspace names from a list of tasks."""
    workspaces = set()
    for task in tasks:
        workspace_name = get_workspace_name_from_task(task)
        if workspace_name:
            workspaces.add(workspace_name)
    return sorted(list(workspaces))

def build_slack_modal(tasks_to_display, all_workspaces, initial_description=""):
    """Builds the Slack modal view."""
    sorted_tasks = sorted(tasks_to_display, key=lambda t: t['name'])

    return {
        "type": "modal",
        "callback_id": "reorder_modal_submit",
        "title": {"type": "plain_text", "text": "Reorder Item"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {
                "type": "input",
                "block_id": "workspace_filter",
                "label": {"type": "plain_text", "text": "Filter by Workspace"},
                "dispatch_action": True,
                "element": {
                    "type": "static_select",
                    "action_id": "selected_workspace",
                    "placeholder": {"type": "plain_text", "text": "All Workspaces"},
                    "options": [
                        {"text": {"type": "plain_text", "text": ws}, "value": ws}
                        for ws in all_workspaces
                    ],
                },
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "delivery_date_block",
                "label": {"type": "plain_text", "text": "Required Delivery Date (Optional)"},
                "hint": {"type": "plain_text", "text": "Efforts will be made to meet this date, but it is not a guarantee."},
                "element": {"type": "datepicker", "action_id": "delivery_date_action", "placeholder": {"type": "plain_text", "text": "Select a date"}},
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "item_selection",
                "label": {"type": "plain_text", "text": "Select an item to reorder"},
                "dispatch_action": True,  # Trigger an event when an item is selected
                "element": {
                    "type": "static_select",
                    "action_id": "selected_item",
                    "placeholder": {"type": "plain_text", "text": "Select an item"},
                    "options": [
                        {"text": {"type": "plain_text", "text": task["name"]}, "value": task["id"]}
                        for task in sorted_tasks
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "description_block",
                "label": {"type": "plain_text", "text": "Description"},
                "hint": {"type": "plain_text", "text": "When the item has a description, it will load here."},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description_action",
                    "multiline": True,
                    "initial_value": initial_description,
                },
                "optional": True,
            },
        ],
    }

def lambda_handler(event, context):
    try:
        clickup_api_token = get_secret(CLICKUP_API_TOKEN_SECRET_NAME)
        slack_bot_token = get_secret(SLACK_BOT_TOKEN_SECRET_NAME)
        headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}

        parsed_body = urllib.parse.parse_qs(event["body"])
        payload_str = parsed_body.get('payload', [None])[0]

        if payload_str:
            payload = json.loads(payload_str)

            if payload.get("type") == "block_actions":
                action = payload["actions"][0]
                action_id = action["action_id"]
                view_id = payload["view"]["id"]

                # Fetch all tasks to perform filtering/lookups
                all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
                all_workspaces = get_all_workspaces_from_tasks(all_tasks)

                # Get the current state of the workspace filter from the modal
                state_values = payload["view"]["state"]["values"]
                current_workspace = state_values.get("workspace_filter", {}).get("selected_workspace", {}).get("selected_option", {}).get("value")

                description = ""

                if action_id == "selected_workspace":
                    print("Handling block action: User changed the workspace filter.")
                    # The selected workspace is the new one from the action
                    current_workspace = action.get("selected_option", {}).get("value")

                elif action_id == "selected_item":
                    print("Handling block action: User selected an item.")
                    task_id = action.get("selected_option", {}).get("value")
                    if task_id:
                        task_details = get_clickup_task_details(clickup_api_token, task_id)
                        description = task_details.get("description") or ""

                # Filter the task list based on the current workspace
                tasks_to_display = []
                if current_workspace:
                    for task in all_tasks:
                        if get_workspace_name_from_task(task) == current_workspace:
                            tasks_to_display.append(task)
                else:
                    tasks_to_display = all_tasks

                # Re-build and update the modal
                updated_view = build_slack_modal(tasks_to_display, all_workspaces, initial_description=description)
                requests.post("https://slack.com/api/views.update", headers=headers, json={"view_id": view_id, "view": updated_view})
                return {"statusCode": 200, "body": ""}

            elif payload.get("type") == "view_submission":
                 print("View submitted. Preparing data for ClickUp.")
                 state_values = payload["view"]["state"]["values"]

                 selected_item_id = state_values.get("item_selection", {}).get("selected_item", {}).get("selected_option", {}).get("value")
                 selected_date = state_values.get("delivery_date_block", {}).get("delivery_date_action", {}).get("selected_date")
                 description_text = state_values.get("description_block", {}).get("description_action", {}).get("value")

                 print(f"Selected Item ID: {selected_item_id}")
                 print(f"Selected Date: {selected_date}")
                 print(f"Description: {description_text}")

                 return {"statusCode": 200, "body": ""}

        # Initial modal open from a Slash Command
        print("Handling initial slash command to open modal.")
        trigger_id = parsed_body.get("trigger_id", [None])[0]
        if not trigger_id:
            raise ValueError("trigger_id not found in request body")

        all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
        all_workspaces = get_all_workspaces_from_tasks(all_tasks)
        modal_view = build_slack_modal(all_tasks, all_workspaces)

        requests.post("https://slack.com/api/views.open", headers=headers, json={"trigger_id": trigger_id, "view": modal_view})
        return {"statusCode": 200, "body": ""}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}