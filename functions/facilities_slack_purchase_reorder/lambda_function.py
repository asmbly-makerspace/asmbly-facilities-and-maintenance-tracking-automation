import json
import os
import boto3
import requests
import urllib.parse
from datetime import datetime

# (Clients and Environment Variables remain the same)
secrets_manager = boto3.client("secretsmanager")
http_session = requests.Session()
CLICKUP_API_TOKEN_SECRET_NAME = os.environ["CLICKUP_SECRET_NAME"]
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"]
CLICKUP_LIST_ID = os.environ["LIST_ID"]
PURCHASE_REQUEST_LIST_ID = os.environ["PURCHASE_REQUEST_LIST_ID"]
WORKSPACE_FIELD_ID = os.environ["WORKSPACE_FIELD_ID"]
SUPPLIER_LINK_FIELD_ID = os.environ["SUPPLIER_LINK_FIELD_ID"]
REQUESTOR_NAME_FIELD_ID = os.environ["REQUESTOR_NAME_FIELD_ID"]
ITEM_TYPE_FIELD_ID = os.environ["ITEM_TYPE_FIELD_ID"]


def get_secret(secret_name):
    '''Retrieves a secret from AWS Secrets Manager.'''
    try:
        response = secrets_manager.get_secret_value(SecretId=secret_name)
        secret_string = response["SecretString"]
        secret_data = json.loads(secret_string)
        if isinstance(secret_data, dict): return list(secret_data.values())[0]
        return secret_string
    except (json.JSONDecodeError): return secret_string

def get_slack_user_info(api_token, user_id):
    '''Retrieves user information from Slack.'''
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {"user": user_id}
    response = http_session.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_clickup_tasks(api_token, list_id):
    '''Retrieves tasks from a ClickUp list.'''
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_token}
    response = http_session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["tasks"]

def get_clickup_task_details(api_token, task_id):
    '''Retrieves task details from a ClickUp task.'''
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": api_token}
    response = http_session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def create_clickup_purchase_request(api_token, payload):
    '''Creates a ClickUp purchase request.'''
    url = f"https://api.clickup.com/api/v2/list/{PURCHASE_REQUEST_LIST_ID}/task"
    headers = {"Authorization": api_token, "Content-Type": "application/json"}
    response = http_session.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def get_custom_field_value(task_details, field_id):
    '''Retrieves the value of a custom field from a task.'''
    for field in task_details.get("custom_fields", []):
        if field.get("id") == field_id:
            return field.get("value")
    return None

def get_all_workspaces_from_tasks(tasks):
    '''Extracts all unique workspace names from tasks.'''
    workspaces = set()
    for task in tasks:
        workspace_name = get_workspace_name_from_task(task)
        if workspace_name: workspaces.add(workspace_name)
    return sorted(list(workspaces))

def get_workspace_name_from_task(task):
    '''Retrieves the name of a workspace from a task.'''
    for field in task.get("custom_fields", []):
        if field.get("id") == WORKSPACE_FIELD_ID and field.get("value") is not None:
            try:
                selected_index = int(field.get("value"))
                options = field.get("type_config", {}).get("options", [])
                matching_option = next((opt for opt in options if opt.get("orderindex") == selected_index), None)
                if matching_option: return matching_option.get("name")
            except (ValueError, TypeError): continue
    return None

def prepare_tasks_for_metadata(tasks):
    '''Prepares tasks for metadata storage.'''
    prepared_tasks = []
    for task in tasks:
        prepared_tasks.append({
            "id": task.get("id"),
            "name": task.get("name"),
            "description": task.get("description") or task.get("text_content") or "",
            "workspace_name": get_workspace_name_from_task(task)
        })
    return prepared_tasks

def build_slack_modal(tasks_to_display, all_workspaces, private_metadata_str="", initial_description="", unique_id=None):
    '''Builds the Slack modal view.'''
    sorted_tasks = sorted(tasks_to_display, key=lambda t: t['name'])

    description_block_id = "description_block"
    if unique_id:
        description_block_id = f"description_block_{unique_id}"

    view = {
        "type": "modal", "callback_id": "reorder_modal_submit",
        "private_metadata": private_metadata_str,
        "title": {"type": "plain_text", "text": "Reorder Item"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {"type": "input", "block_id": "workspace_filter", "label": {"type": "plain_text", "text": "Filter by Workspace"}, "dispatch_action": True, "element": {"type": "static_select", "action_id": "selected_workspace", "placeholder": {"type": "plain_text", "text": "All Workspaces"}, "options": [{"text": {"type": "plain_text", "text": ws}, "value": ws} for ws in all_workspaces]}, "optional": True},
            {"type": "input", "block_id": "delivery_date_block", "label": {"type": "plain_text", "text": "Required Delivery Date"}, "hint": {"type": "plain_text", "text": "Efforts will be made to meet this date, but it is not a guarantee."}, "element": {"type": "datepicker", "action_id": "delivery_date_action", "placeholder": {"type": "plain_text", "text": "Select a date"}}, "optional": True},
            {"type": "input", "block_id": "item_selection", "label": {"type": "plain_text", "text": "Select an item to reorder"}, "dispatch_action": True, "element": {"type": "static_select", "action_id": "selected_item", "placeholder": {"type": "plain_text", "text": "Select an item"}, "options": [{"text": {"type": "plain_text", "text": task["name"]}, "value": task["id"]} for task in sorted_tasks]}},
            {"type": "input", "block_id": description_block_id, "label": {"type": "plain_text", "text": "Description"}, "element": {"type": "plain_text_input", "action_id": "description_action", "multiline": True, "initial_value": initial_description}, "optional": True},
        ]
    }
    return view

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
                view = payload["view"]
                view_id = view["id"]
                private_metadata_str = view.get("private_metadata", "{}")
                all_tasks_prepared = json.loads(private_metadata_str)
                all_workspaces = sorted(list(set(t['workspace_name'] for t in all_tasks_prepared if t['workspace_name'])))
                action = payload["actions"][0]
                action_id = action["action_id"]
                state_values = view["state"]["values"]
                workspace_state = state_values.get("workspace_filter", {}).get("selected_workspace", {})
                selected_option = workspace_state.get("selected_option")
                current_workspace = selected_option.get("value") if selected_option else None
                description = ""

                if action_id == "selected_workspace":
                    current_workspace = action.get("selected_option", {}).get("value")
                elif action_id == "selected_item":
                    task_id = action.get("selected_option", {}).get("value")
                    if task_id:
                        task_details = next((t for t in all_tasks_prepared if t['id'] == task_id), None)
                        if task_details:
                            description = task_details.get("description", "")

                tasks_to_display = [t for t in all_tasks_prepared if t.get('workspace_name') == current_workspace] if current_workspace else all_tasks_prepared

                # --- MODIFIED: Pass a unique ID to the modal builder ---
                unique_id = str(datetime.now().timestamp())
                updated_view = build_slack_modal(tasks_to_display, all_workspaces, private_metadata_str=private_metadata_str, initial_description=description, unique_id=unique_id)

                http_session.post("https://slack.com/api/views.update", headers=headers, json={"view_id": view_id, "view": updated_view})
                return {"statusCode": 200, "body": ""}

            elif payload.get("type") == "view_submission":
                 state_values = payload["view"]["state"]["values"]
                 selected_item_id = state_values.get("item_selection", {}).get("selected_item", {}).get("selected_option", {}).get("value")
                 delivery_date = state_values.get("delivery_date_block", {}).get("delivery_date_action", {}).get("selected_date")

                 # --- MODIFIED: Find the description value using its dynamic ID ---
                 description_text = ""
                 for block_id, block_values in state_values.items():
                     if block_id.startswith("description_block"):
                         description_text = block_values.get("description_action", {}).get("value")
                         break

                 slack_user_id = payload["user"]["id"]
                 slack_user_info = get_slack_user_info(slack_bot_token, slack_user_id)
                 requestor_real_name = slack_user_info.get("user", {}).get("real_name", "Unknown User")

                 original_item_details = get_clickup_task_details(clickup_api_token, selected_item_id)

                 new_task_payload = {
                     "name": original_item_details["name"], "description": description_text,
                     "custom_fields": [
                         {"id": WORKSPACE_FIELD_ID, "value": get_custom_field_value(original_item_details, WORKSPACE_FIELD_ID)},
                         {"id": SUPPLIER_LINK_FIELD_ID, "value": get_custom_field_value(original_item_details, SUPPLIER_LINK_FIELD_ID)},
                         {"id": REQUESTOR_NAME_FIELD_ID, "value": requestor_real_name},
                         {"id": ITEM_TYPE_FIELD_ID, "value": get_custom_field_value(original_item_details, ITEM_TYPE_FIELD_ID)},
                     ]
                 }

                 if delivery_date:
                     dt_object = datetime.strptime(delivery_date, '%Y-%m-%d')
                     new_task_payload["due_date"] = int(dt_object.timestamp() * 1000)

                 create_clickup_purchase_request(clickup_api_token, new_task_payload)

                 success_view = {"type": "modal", "title": {"type": "plain_text", "text": "Success!"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Your purchase request was created successfully."}}], "close": {"type": "plain_text", "text": "Close"}}
                 return {"statusCode": 200, "body": json.dumps({"response_action": "update", "view": success_view})}

        # Initial modal open
        trigger_id = parsed_body.get("trigger_id", [None])[0]
        if not trigger_id: raise ValueError("trigger_id not found")

        all_tasks_full = get_clickup_tasks(clickup_api_token, CLICKUP_LIST_ID)

        if not all_tasks_full:
            error_view = {"type": "modal", "title": {"type": "plain_text", "text": "No Items Found"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Sorry, no reorderable items were found in the ClickUp list."}}], "close": {"type": "plain_text", "text": "Close"}}
            http_session.post("https://slack.com/api/views.open", headers=headers, json={"trigger_id": trigger_id, "view": error_view})
            return {"statusCode": 200, "body": ""}

        all_tasks_prepared = prepare_tasks_for_metadata(all_tasks_full)
        all_workspaces = sorted(list(set(t['workspace_name'] for t in all_tasks_prepared if t['workspace_name'])))
        private_metadata_str = json.dumps(all_tasks_prepared)

        modal_view = build_slack_modal(all_tasks_prepared, all_workspaces, private_metadata_str=private_metadata_str)
        http_session.post("https://slack.com/api/views.open", headers=headers, json={"trigger_id": trigger_id, "view": modal_view})
        return {"statusCode": 200, "body": ""}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}