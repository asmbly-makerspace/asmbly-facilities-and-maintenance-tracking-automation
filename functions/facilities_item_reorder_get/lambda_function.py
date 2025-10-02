
import json
import os
import boto3
import requests

# Environment variables
CLICKUP_API_TOKEN_SECRET_NAME = os.environ["CLICKUP_SECRET_NAME"]
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"]
CLICKUP_LIST_ID = os.environ["LIST_ID"]

# AWS Secrets Manager client
secrets_manager = boto3.client("secretsmanager")

def get_secret(secret_name):
    """Retrieves a secret from AWS Secrets Manager."""
    response = secrets_manager.get_secret_value(SecretId=secret_name)
    return response["SecretString"]

def get_clickup_tasks(api_token, list_id):
    """Fetches tasks from a ClickUp list."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["tasks"]

def build_slack_modal(tasks):
    """Builds the Slack modal view."""
    workspace_options = sorted(list(set(
        field["value"]["name"]
        for task in tasks
        for field in task.get("custom_fields", [])
        if field.get("name") == "Workspace" and field.get("value")
    )))

    return {
        "type": "modal",
        "callback_id": "reorder_modal_submit",
        "title": {"type": "plain_text", "text": "Reorder Item"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {
                "type": "input",
                "block_id": "item_selection",
                "label": {"type": "plain_text", "text": "Select an item to reorder"},
                "element": {
                    "type": "static_select",
                    "action_id": "selected_item",
                    "placeholder": {"type": "plain_text", "text": "Select an item"},
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": task["name"]},
                            "value": task["id"],
                        }
                        for task in tasks
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "workspace_filter",
                "label": {"type": "plain_text", "text": "Filter by Workspace"},
                "element": {
                    "type": "static_select",
                    "action_id": "selected_workspace",
                    "placeholder": {"type": "plain_text", "text": "All Workspaces"},
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": workspace},
                            "value": workspace,
                        }
                        for workspace in workspace_options
                    ],
                },
                "optional": True,
            },
        ],
    }

def lambda_handler(event, context):
    try:
        # Get secrets
        clickup_api_token = get_secret(CLICKUP_API_TOKEN_SECRET_NAME)
        slack_bot_token = get_secret(SLACK_BOT_TOKEN_SECRET_NAME)

        # Acknowledge the Slack command
        if "command" in event["body"]:
            body = json.loads(event["body"])
            trigger_id = body["trigger_id"]

            # Fetch tasks from ClickUp
            tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)

            # Build and open the Slack modal
            modal_view = build_slack_modal(tasks)
            slack_api_url = "https://slack.com/api/views.open"
            headers = {
                "Authorization": f"Bearer {slack_bot_token}",
                "Content-Type": "application/json",
            }
            payload = {"trigger_id": trigger_id, "view": modal_view}
            response = requests.post(slack_api_url, headers=headers, json=payload)
            response.raise_for_status()

            return {"statusCode": 200, "body": ""}

        # Handle other cases if necessary
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Hello from FacilitiesItemReorderGetFunction!"}),
        }

    except Exception as e:
        print(f"Error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
