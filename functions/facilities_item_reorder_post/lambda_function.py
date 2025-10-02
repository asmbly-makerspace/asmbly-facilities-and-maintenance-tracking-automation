
import json
import os
import boto3
import requests

# Environment variables
CLICKUP_API_TOKEN_SECRET_NAME = os.environ["CLICKUP_SECRET_NAME"]
CLICKUP_PURCHASE_LIST_ID = os.environ["PURCHASE_REQUEST_LIST_ID"]

# AWS Secrets Manager client
secrets_manager = boto3.client("secretsmanager")

def get_secret(secret_name):
    """Retrieves a secret from AWS Secrets Manager."""
    response = secrets_manager.get_secret_value(SecretId=secret_name)
    return response["SecretString"]

def get_clickup_task(api_token, task_id):
    """Fetches a single task from ClickUp."""
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def create_clickup_task(api_token, list_id, original_task):
    """Creates a new task in a ClickUp list."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token, "Content-Type": "application/json"}

    # Extract relevant custom fields by name
    custom_fields_to_copy = ["Preferred Supplier Link", "Workspace", "Item Type"]
    new_custom_fields = []
    for field in original_task.get("custom_fields", []):
        if field.get("name") in custom_fields_to_copy and field.get("value") is not None:
            # NOTE: This assumes the destination list has custom fields with the same IDs and options.
            # A more robust solution would fetch the destination list's fields and match by name.
            new_custom_fields.append({"id": field["id"], "value": field["value"]})

    payload = {
        "name": original_task["name"],
        "description": f'Reorder request from task: {original_task["url"]}',
        "custom_fields": new_custom_fields,
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def lambda_handler(event, context):
    try:
        # Get secrets
        clickup_api_token = get_secret(CLICKUP_API_TOKEN_SECRET_NAME)

        # Parse the Slack payload
        payload = json.loads(event["body"])["payload"]
        if payload["type"] == "view_submission":
            view = payload["view"]
            if view["callback_id"] == "reorder_modal_submit":
                # Extract selected item
                selected_item_id = view["state"]["values"]["item_selection"]["selected_item"]["value"]

                # Get the original task details
                original_task = get_clickup_task(clickup_api_token, selected_item_id)

                # Create the new purchase request task
                create_clickup_task(
                    clickup_api_token, CLICKUP_PURCHASE_LIST_ID, original_task
                )

                # Return a confirmation message to update the modal
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "response_action": "update",
                        "view": {
                            "type": "modal",
                            "title": {"type": "plain_text", "text": "Request Submitted"},
                            "close": {"type": "plain_text", "text": "Close"},
                            "blocks": [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": ":white_check_mark: Your reorder request has been submitted successfully!",
                                    },
                                }
                            ],
                        },
                    }),
                    "headers": {"Content-Type": "application/json"},
                }

    except Exception as e:
        print(f"Error: {e}")
        # Return an error message in the modal
        return {
            "statusCode": 200, # Slack needs 200 to update the view
            "body": json.dumps({
                "response_action": "update",
                "view": {
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Error"},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":x: An error occurred: {e}",
                            },
                        }
                    ],
                },
            }),
            "headers": {"Content-Type": "application/json"},
        }

    return {"statusCode": 200, "body": ""}
