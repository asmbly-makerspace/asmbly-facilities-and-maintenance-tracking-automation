import json
import os
import boto3
import requests
import urllib.parse
from datetime import datetime

# Environment variables
CLICKUP_API_TOKEN_SECRET_NAME = os.environ["CLICKUP_SECRET_NAME"]
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"]
CLICKUP_LIST_ID = os.environ["LIST_ID"]
PURCHASE_REQUEST_LIST_ID = os.environ["PURCHASE_REQUEST_LIST_ID"]

# --- TODO: REPLACE THESE PLACEHOLDERS WITH YOUR ACTUAL CUSTOM FIELD IDs ---
# You can find these IDs using the API call from Part 1.
WORKSPACE_FIELD_ID_PLACEHOLDER = "abc-123-your-workspace-field-id"
SUPPLIER_LINK_FIELD_ID_PLACEHOLDER = "def-456-your-supplier-field-id"
REQUESTOR_NAME_FIELD_ID_PLACEHOLDER = "ghi-789-your-requestor-field-id"
ITEM_TYPE_FIELD_ID_PLACEHOLDER = "jkl-012-your-item-type-field-id"

# AWS Secrets Manager client
secrets_manager = boto3.client("secretsmanager")

def get_secret(secret_name):
    # ... (this function remains the same)
    try:
        response = secrets_manager.get_secret_value(SecretId=secret_name)
        secret_string = response["SecretString"]
        secret_data = json.loads(secret_string)
        if isinstance(secret_data, dict): return list(secret_data.values())[0]
        return secret_string
    except (json.JSONDecodeError): return secret_string

def get_clickup_tasks(api_token, list_id):
    # ... (this function remains the same)
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["tasks"]

def get_clickup_task_details(api_token, task_id):
    # ... (this function remains the same)
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def create_clickup_purchase_request(api_token, payload):
    """Creates a new task in the Purchase Request list."""
    url = f"https://api.clickup.com/api/v2/list/{PURCHASE_REQUEST_LIST_ID}/task"
    headers = {"Authorization": api_token, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def get_custom_field_value(task_details, field_name):
    """Helper to find a custom field's value by its name from a task object."""
    for field in task_details.get("custom_fields", []):
        if field.get("name") == field_name:
            return field.get("value")
    return None

def get_all_workspaces_from_tasks(tasks):
    # ... (this function remains the same)
    workspaces = set()
    for task in tasks:
        workspace_name = get_workspace_name_from_task(task)
        if workspace_name: workspaces.add(workspace_name)
    return sorted(list(workspaces))

def get_workspace_name_from_task(task):
    # ... (this function remains the same)
    for field in task.get("custom_fields", []):
        if field.get("name") == "Workspace" and field.get("value") is not None:
            try:
                selected_index = int(field.get("value"))
                options = field.get("type_config", {}).get("options", [])
                matching_option = next((opt for opt in options if opt.get("orderindex") == selected_index), None)
                if matching_option: return matching_option.get("name")
            except (ValueError, TypeError): continue
    return None

def build_slack_modal(tasks_to_display, all_workspaces, initial_description=""):
    # ... (this function remains the same)
    sorted_tasks = sorted(tasks_to_display, key=lambda t: t['name'])
    return {
        "type": "modal", "callback_id": "reorder_modal_submit",
        "title": {"type": "plain_text", "text": "Reorder Item"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {"type": "input", "block_id": "workspace_filter", "label": {"type": "plain_text", "text": "Filter by Workspace"}, "dispatch_action": True, "element": {"type": "static_select", "action_id": "selected_workspace", "placeholder": {"type": "plain_text", "text": "All Workspaces"}, "options": [{"text": {"type": "plain_text", "text": ws}, "value": ws} for ws in all_workspaces]}, "optional": True},
            {"type": "input", "block_id": "delivery_date_block", "label": {"type": "plain_text", "text": "Required Delivery Date (Optional)"}, "hint": {"type": "plain_text", "text": "Efforts will be made to meet this date, but it is not a guarantee."}, "element": {"type": "datepicker", "action_id": "delivery_date_action", "placeholder": {"type": "plain_text", "text": "Select a date"}}, "optional": True},
            {"type": "input", "block_id": "item_selection", "label": {"type": "plain_text", "text": "Select an item to reorder"}, "dispatch_action": True, "element": {"type": "static_select", "action_id": "selected_item", "placeholder": {"type": "plain_text", "text": "Select an item"}, "options": [{"text": {"type": "plain_text", "text": task["name"]}, "value": task["id"]} for task in sorted_tasks]}},
            {"type": "input", "block_id": "description_block", "label": {"type": "plain_text", "text": "Description"}, "element": {"type": "plain_text_input", "action_id": "description_action", "multiline": True, "initial_value": initial_description}, "optional": True},
        ]
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
                # ... (this logic remains the same)
                action, view_id = payload["actions"][0], payload["view"]["id"]
                all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
                all_workspaces = get_all_workspaces_from_tasks(all_tasks)
                state_values = payload["view"]["state"]["values"]
                current_workspace = state_values.get("workspace_filter", {}).get("selected_workspace", {}).get("selected_option", {}).get("value")
                description = ""
                if action["action_id"] == "selected_workspace": current_workspace = action.get("selected_option", {}).get("value")
                elif action["action_id"] == "selected_item":
                    task_id = action.get("selected_option", {}).get("value")
                    if task_id:
                        task_details = get_clickup_task_details(clickup_api_token, task_id)
                        description = task_details.get("description") or ""
                tasks_to_display = [t for t in all_tasks if get_workspace_name_from_task(t) == current_workspace] if current_workspace else all_tasks
                updated_view = build_slack_modal(tasks_to_display, all_workspaces, initial_description=description)
                requests.post("https://slack.com/api/views.update", headers=headers, json={"view_id": view_id, "view": updated_view})
                return {"statusCode": 200, "body": ""}

            elif payload.get("type") == "view_submission":
                 print("View submitted. Creating ClickUp purchase request.")
                 state_values = payload["view"]["state"]["values"]

                 # --- 1. EXTRACT DATA FROM MODAL AND SLACK ---
                 selected_item_id = state_values.get("item_selection", {}).get("selected_item", {}).get("selected_option", {}).get("value")
                 delivery_date = state_values.get("delivery_date_block", {}).get("delivery_date_action", {}).get("selected_date")
                 description_text = state_values.get("description_block", {}).get("description_action", {}).get("value")
                 slack_user_name = payload["user"]["name"]

                 # --- 2. FETCH FULL DETAILS OF THE ORIGINAL ITEM ---
                 original_item_details = get_clickup_task_details(clickup_api_token, selected_item_id)

                 # --- 3. MAP DATA FOR THE NEW TASK PAYLOAD ---
                 new_task_payload = {
                     "name": original_item_details["name"],
                     "description": description_text,
                     "custom_fields": [
                         {"id": WORKSPACE_FIELD_ID_PLACEHOLDER, "value": get_custom_field_value(original_item_details, "Workspace")},
                         {"id": SUPPLIER_LINK_FIELD_ID_PLACEHOLDER, "value": get_custom_field_value(original_item_details, "Preferred Supplier Link")},
                         {"id": REQUESTOR_NAME_FIELD_ID_PLACEHOLDER, "value": slack_user_name},
                         {"id": ITEM_TYPE_FIELD_ID_PLACEHOLDER, "value": get_custom_field_value(original_item_details, "Item Type")},
                     ]
                 }

                 # Add due date if it was selected, converting it to a unix millisecond timestamp
                 if delivery_date:
                     dt_object = datetime.strptime(delivery_date, '%Y-%m-%d')
                     new_task_payload["due_date"] = int(dt_object.timestamp() * 1000)

                 # --- 4. CREATE THE NEW TASK IN CLICKUP ---
                 create_clickup_purchase_request(clickup_api_token, new_task_payload)

                 # --- 5. SHOW A SUCCESS MESSAGE TO THE USER ---
                 success_view = {"type": "modal", "title": {"type": "plain_text", "text": "Success!"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Your purchase request was created successfully."}}], "close": {"type": "plain_text", "text": "Close"}}
                 return {"statusCode": 200, "body": json.dumps({"response_action": "update", "view": success_view})}

        # Initial modal open
        trigger_id = parsed_body.get("trigger_id", [None])[0]
        if not trigger_id: raise ValueError("trigger_id not found")
        all_tasks = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)
        all_workspaces = get_all_workspaces_from_tasks(all_tasks)
        modal_view = build_slack_modal(all_tasks, all_workspaces)
        requests.post("https://slack.com/api/views.open", headers=headers, json={"trigger_id": trigger_id, "view": modal_view})
        return {"statusCode": 200, "body": ""}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}