
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
    print(f"Attempting to retrieve secret: {secret_name}")
    response = secrets_manager.get_secret_value(SecretId=secret_name)
    secret_string = response["SecretString"]
    print(f"Successfully retrieved secret: {secret_name}")
    
    # Check if the secret is a JSON string and parse it if so.
    try:
        secret_data = json.loads(secret_string)
        # If it's a dict, assume the token is the first value.
        if isinstance(secret_data, dict):
            return list(secret_data.values())[0]
    except json.JSONDecodeError:
        # It's not a JSON string, so return it as is.
        pass
    
    return secret_string

def get_clickup_tasks(api_token, list_id):
    """Fetches tasks from a ClickUp list."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token}
    
    print(f"Making request to ClickUp API at URL: {url}")
    print(f"Using Authorization header (masked): {api_token[:4]}...{api_token[-4:]}")
    
    response = requests.get(url, headers=headers)
    
    print(f"ClickUp API response status code: {response.status_code}")
    # Only print the first 500 chars of the body for brevity
    print(f"ClickUp API response body (truncated): {response.text[:500]}")
    
    response.raise_for_status()
    return response.json()["tasks"]

def build_slack_modal(tasks):
    """Builds the Slack modal view from a list of ClickUp tasks."""
    workspaces = set()
    for task in tasks:
        for field in task.get("custom_fields", []):
            if field.get("name") == "Workspace" and field.get("value") is not None:
                try:
                    # For dropdowns, the 'value' is the orderindex of the selected option.
                    selected_index = int(field.get("value"))
                    options = field.get("type_config", {}).get("options", [])
                    
                    # Find the option in the list that has the matching orderindex.
                    matching_option = next((opt for opt in options if opt.get("orderindex") == selected_index), None)
                    
                    if matching_option and matching_option.get("name"):
                        workspaces.add(matching_option.get("name"))
                        
                except (ValueError, TypeError):
                    # This handles cases where the value is not an integer, etc. Just skip.
                    continue
    
    workspace_options = sorted(list(workspaces))

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
        print(f"Lambda invoked. Event body: {event.get('body')}")

        # Get secrets
        clickup_api_token = get_secret(CLICKUP_API_TOKEN_SECRET_NAME)
        slack_bot_token = get_secret(SLACK_BOT_TOKEN_SECRET_NAME)

        # Slack sends a URL-encoded body. Parse it.
        parsed_body = urllib.parse.parse_qs(event["body"])

        # Check if the request is from an interactive component (e.g., a button)
        if 'payload' in parsed_body:
            payload_str = parsed_body['payload'][0]
            print(f"Received interactive payload: {payload_str}")
            payload_json = json.loads(payload_str)
            trigger_id = payload_json.get("trigger_id")
        # Otherwise, assume it's a slash command.
        else:
            print("Received slash command payload.")
            trigger_id = parsed_body.get("trigger_id", [None])[0]

        if not trigger_id:
            print("Error: trigger_id not found in request body")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "trigger_id not found in request body"}),
            }
        
        print(f"Extracted trigger_id: {trigger_id}")

        # Fetch tasks from ClickUp
        tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)

        # Build and open the Slack modal
        modal_view = build_slack_modal(tasks)
        slack_api_url = "https://slack.com/api/views.open"
        headers = {
            "Authorization": f"Bearer {slack_bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {"trigger_id": trigger_id, "view": modal_view}
        
        print("Opening Slack modal...")
        response = requests.post(slack_api_url, headers=headers, json=payload)
        slack_response_data = response.json()

        if not slack_response_data.get("ok"):
            print(f"Slack API Error: {slack_response_data.get('error')}")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Slack API error: {slack_response_data.get('error')}"}),
            }
        
        print("Successfully opened Slack modal.")
        # Return a 200 OK to Slack to acknowledge the command.
        return {"statusCode": 200, "body": ""}

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # Log the full traceback for debugging
        import traceback
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
