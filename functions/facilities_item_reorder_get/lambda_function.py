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

def build_slack_modal(tasks_to_display, all_workspaces):
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
                "block_id": "item_selection",
                "label": {"type": "plain_text", "text": "Select an item to reorder"},
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
        ],
    }

def lambda_handler(event, context):
    try:
        clickup_api_token = get_secret(CLICKUP_API_TOKEN_SECRET_NAME)
        slack_bot_token = get_secret(SLACK_BOT_TOKEN_SECRET_NAME)
        headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}

        parsed_body = urllib.parse.parse_qs(event["body"])
        payload_str = parsed_body.get('payload', [None])[0]

        # Scenario 1: User interacts with the modal (e.g., uses the filter)
        if payload_str:
            payload = json.loads(payload_str)
            if payload.get("type") == "block_actions":
                print("Handling block action: User changed the workspace filter.")
                action = payload["actions"][0]
                selected_workspace = action.get("selected_option", {}).get("value")
                view_id = payload["view"]["id"]

                all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
                all_workspaces = get_all_workspaces_from_tasks(all_tasks)

                tasks_to_display = []
                if selected_workspace:
                    for task in all_tasks:
                        if get_workspace_name_from_task(task) == selected_workspace:
                            tasks_to_display.append(task)
                else:
                    tasks_to_display = all_tasks

                updated_view = build_slack_modal(tasks_to_display, all_workspaces)

                response = requests.post("https://slack.com/api/views.update", headers=headers, json={"view_id": view_id, "view": updated_view})
                if not response.json().get("ok"):
                    print(f"Slack API Error during views.update: {response.json().get('error')}")

                return {"statusCode": 200, "body": ""}

            elif payload.get("type") == "view_submission":
                 # This is where you would handle the final "Submit" button click
                 print("View submitted. Add submission handling logic here.")
                 return {"statusCode": 200, "body": ""}


        # Scenario 2: Initial modal open from a Slash Command
        print("Handling initial slash command to open modal.")
        trigger_id = parsed_body.get("trigger_id", [None])[0]
        if not trigger_id:
            raise ValueError("trigger_id not found in request body")

        all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
        all_workspaces = get_all_workspaces_from_tasks(all_tasks)
        modal_view = build_slack_modal(all_tasks, all_workspaces)

        response = requests.post("https://slack.com/api/views.open", headers=headers, json={"trigger_id": trigger_id, "view": modal_view})
        if not response.json().get("ok"):
            print(f"Slack API Error during views.open: {response.json().get('error')}")

        return {"statusCode": 200, "body": ""}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}