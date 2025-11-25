import json
import os
import requests
from datetime import timezone, timedelta
import urllib.parse
from datetime import datetime
import boto3
import logging

from common.aws import get_secret, get_json_parameter
from common.clickup import get_all_clickup_tasks, get_task, create_task
from common.slack import SlackState, get_slack_user_info

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients, initialized lazily to make testing easier
dynamodb_resource = None
lambda_client = None

def _get_dynamodb_resource():
    """Initializes and returns the DynamoDB resource, creating it if necessary."""
    global dynamodb_resource
    if dynamodb_resource is None:
        dynamodb_resource = boto3.resource('dynamodb')
    return dynamodb_resource

def _get_lambda_client():
    """Initializes and returns the Lambda client, creating it if necessary."""
    global lambda_client
    if lambda_client is None:
        lambda_client = boto3.client('lambda')
    return lambda_client

class Config:
    """Loads and holds configuration from environment variables."""
    def __init__(self):
        self.clickup_api_token_secret_name = os.environ["CLICKUP_SECRET_NAME"]
        self.slack_bot_token_secret_name = os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"]
        self.master_items_list_config_param_name = os.environ["CLICKUP_MASTER_ITEMS_LIST_CONFIG_PARAM_NAME"]
        self.purchase_requests_config_param_name = os.environ["CLICKUP_PURCHASE_REQUESTS_CONFIG_PARAM_NAME"]
        self.workspace_field_id_param_name = os.environ["CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME"]
        self.state_table_name = os.environ.get("STATE_TABLE_NAME")

        # These will be populated after fetching from SSM
        self.master_items_list_id = None
        self.purchase_requests_config = {}
        self.workspace_field_id = None

def get_all_workspaces_from_tasks(tasks):
    '''Extracts all unique workspace names from tasks.'''
    workspaces = set(task.get('workspace_name') for task in tasks if task.get('workspace_name'))
    return sorted(list(workspaces))

def get_workspace_name_from_task(task, workspace_field_id):
    '''Retrieves the name of a workspace from a task.'''
    for field in task.get("custom_fields", []):
        if field.get("id") == workspace_field_id and field.get("value") is not None:
            try:
                selected_index = int(field.get("value"))
                options = field.get("type_config", {}).get("options", [])
                matching_option = next((opt for opt in options if opt.get("orderindex") == selected_index), None)
                if matching_option: return matching_option.get("name")
            except (ValueError, TypeError): continue
    return None

def prepare_tasks_for_state(tasks, workspace_field_id):
    '''Prepares tasks for state storage, including the description.'''
    prepared_tasks = []
    for task in tasks:
        prepared_tasks.append({
            "id": task.get("id"),
            "name": task.get("name"),
            "description": task.get("description") or task.get("text_content") or "",
            "workspace_name": get_workspace_name_from_task(task, workspace_field_id)
        })
    return prepared_tasks

def build_slack_modal(tasks_to_display, all_workspaces, initial_description="", selected_workspace=None, selected_item=None):
    '''Builds the Slack modal view, preserving the selected state.'''
    sorted_tasks = sorted(tasks_to_display, key=lambda t: t['name'])

    workspace_element = {
        "type": "static_select",
        "action_id": "selected_workspace",
        "placeholder": {"type": "plain_text", "text": "All Workspaces"},
        "options": [{"text": {"type": "plain_text", "text": ws}, "value": ws} for ws in all_workspaces]
    }
    if selected_workspace:
        workspace_element["initial_option"] = {
            "text": {"type": "plain_text", "text": selected_workspace},
            "value": selected_workspace
        }

    item_element = {
        "type": "static_select",
        "action_id": "selected_item",
        "placeholder": {"type": "plain_text", "text": "Select an item"},
        "options": [{"text": {"type": "plain_text", "text": task["name"]}, "value": task["id"]} for task in sorted_tasks]
    }
    if selected_item:
        task_name = next((t['name'] for t in tasks_to_display if t['id'] == selected_item), None)
        if task_name:
            item_element["initial_option"] = {
                "text": {"type": "plain_text", "text": task_name},
                "value": selected_item
            }

    description_block_id = f"description_block_{selected_item}" if selected_item else "description_block"

    view = {
        "type": "modal", "callback_id": "reorder_modal_submit",
        "private_metadata": "",
        "title": {"type": "plain_text", "text": "Reorder Item"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {"type": "input", "block_id": "workspace_filter", "label": {"type": "plain_text", "text": "Filter by Workspace"}, "dispatch_action": True, "element": workspace_element, "optional": True},
            {"type": "input", "block_id": "delivery_date_block", "label": {"type": "plain_text", "text": "Required Delivery Date"}, "hint": {"type": "plain_text", "text": "Efforts will be made to meet this date, but it is not a guarantee."}, "element": {"type": "datepicker", "action_id": "delivery_date_action", "placeholder": {"type": "plain_text", "text": "Select a date"}}, "optional": True},
            {"type": "input", "block_id": "item_selection", "label": {"type": "plain_text", "text": "Select an item to reorder"}, "dispatch_action": True, "element": item_element},
            {"type": "input", "block_id": description_block_id, "label": {"type": "plain_text", "text": "Description"}, "element": {"type": "plain_text_input", "action_id": "description_action", "multiline": True, "initial_value": initial_description}, "optional": True},
        ]
    }
    return view

def handle_block_actions(payload, http_session, slack_bot_token):
    """Handles interactive events from the modal (e.g., filtering)."""
    view = payload["view"]
    view_id = view["id"]
    logger.info("Handling block action for view_id: %s", view_id)

    try:
        state_table = _get_dynamodb_resource().Table(os.environ.get("STATE_TABLE_NAME"))
        response = state_table.get_item(Key={'view_id': view_id})
        if 'Item' not in response:
            raise ValueError(f"State not found in DynamoDB for view_id: {view_id}")

        all_tasks_prepared = json.loads(response['Item']['tasks_data'])
        all_workspaces = get_all_workspaces_from_tasks(all_tasks_prepared)
        logger.info("Retrieved %d tasks from DynamoDB state", len(all_tasks_prepared))

    except Exception as e:
        logger.error("Failed to get state for view_id %s: %s", view_id, e, exc_info=True)
        return {"statusCode": 200, "body": ""}

    action = payload["actions"][0]
    action_id = action["action_id"]
    logger.info("Action triggered: %s", action_id)

    state = SlackState(view.get("state", {}).get("values"))
    current_workspace = state.get_selected_option_value("workspace_filter", "selected_workspace")
    selected_item = state.get_selected_option_value("item_selection", "selected_item")
    description = ""

    if action_id == "selected_workspace":
        current_workspace = (action.get("selected_option") or {}).get("value")
        selected_item = None
        description = ""
    elif action_id == "selected_item":
        selected_item = (action.get("selected_option") or {}).get("value")
        if selected_item:
            task_details = next((t for t in all_tasks_prepared if t['id'] == selected_item), None)
            if task_details:
                description = task_details.get("description", "")

    tasks_to_display = [t for t in all_tasks_prepared if not current_workspace or t.get('workspace_name') == current_workspace]
    updated_view = build_slack_modal(tasks_to_display, all_workspaces, initial_description=description, selected_workspace=current_workspace, selected_item=selected_item)

    slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}
    api_response = http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": updated_view})

    if not api_response.ok or not api_response.json().get("ok"):
        logger.error("Error updating Slack view: %s", api_response.text)
    else:
        logger.info("Successfully updated view via API")

    return {"statusCode": 200, "body": ""}

def handle_process_submission(payload):
    """
    (ASYNC) Handles the slow work of a modal submission after it has been acknowledged.
    """
    view_id = payload['view']['id']
    logger.info("Starting to process submission for view_id: %s", view_id)
    http_session = requests.Session()
    slack_bot_token = None
    try:
        config = Config()
        clickup_api_token = get_secret(config.clickup_api_token_secret_name, 'CLICKUP_API_TOKEN')
        slack_bot_token = get_secret(config.slack_bot_token_secret_name, 'SLACK_MAINTENANCE_BOT_TOKEN')
        config.workspace_field_id = get_json_parameter(config.workspace_field_id_param_name, expected_key='workspace_field_id')
        config.purchase_requests_config = get_json_parameter(config.purchase_requests_config_param_name)

        state = SlackState(payload["view"]["state"]["values"])
        selected_item_id = state.get_selected_option_value("item_selection", "selected_item")
        delivery_date = state.get_value("delivery_date_block", "delivery_date_action", "selected_date")
        
        description_text = ""
        values = payload["view"]["state"]["values"]
        for block_id, fields in values.items():
            if block_id.startswith("description_block"):
                if "description_action" in fields:
                    description_text = fields["description_action"].get("value") or ""
                    break

        if not selected_item_id:
            raise ValueError("Could not determine the selected item from the submission payload.")

        slack_user_id = payload["user"]["id"]
        slack_user_info = get_slack_user_info(slack_bot_token, slack_user_id, http_session)
        requestor_real_name = slack_user_info.get("user", {}).get("real_name", "Unknown User")

        original_item_details = get_task(clickup_api_token, selected_item_id)

        def get_raw_custom_field_value(task, field_id):
            for field in task.get("custom_fields", []):
                if field.get("id") == field_id:
                    return field.get("value")
            return None

        new_task_payload = {
            "name": original_item_details["name"], "description": description_text,
            "custom_fields": [
                {"id": config.workspace_field_id, "value": get_raw_custom_field_value(original_item_details, config.workspace_field_id)},
                {"id": config.purchase_requests_config['supplier_link_field_id'], "value": get_raw_custom_field_value(original_item_details, config.purchase_requests_config['supplier_link_field_id'])},
                {"id": config.purchase_requests_config['requestor_name_field_id'], "value": requestor_real_name},
                {"id": config.purchase_requests_config['item_type_field_id'], "value": get_raw_custom_field_value(original_item_details, config.purchase_requests_config['item_type_field_id'])},
            ]
        }

        if delivery_date:
            dt_object = datetime.strptime(delivery_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            new_task_payload["due_date"] = int(dt_object.timestamp() * 1000)

        create_task(clickup_api_token, config.purchase_requests_config['list_id'], new_task_payload)

        success_view = {"type": "modal", "title": {"type": "plain_text", "text": "Success!"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Your purchase request was created successfully."}}], "close": {"type": "plain_text", "text": "Close"}}
        slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}
        http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": success_view})

    except Exception as e:
        logger.error("Failed to process submission for view_id %s: %s", view_id, e, exc_info=True)
        if slack_bot_token:
            error_view = {"type": "modal", "title": {"type": "plain_text", "text": "Error"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"An error occurred: {e}"}}], "close": {"type": "plain_text", "text": "Close"}}
            slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}
            http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": error_view})

def handle_load_data_and_update_view(view_id):
    """(ASYNC) Fetches data from ClickUp, stores it in DynamoDB, and updates the Slack modal."""
    logger.info("Starting to load data for view_id: %s", view_id)
    http_session = requests.Session()
    slack_bot_token = None
    try:
        config = Config()
        clickup_api_token = get_secret(config.clickup_api_token_secret_name, 'CLICKUP_API_TOKEN')
        slack_bot_token = get_secret(config.slack_bot_token_secret_name, 'SLACK_MAINTENANCE_BOT_TOKEN')
        config.workspace_field_id = get_json_parameter(config.workspace_field_id_param_name, expected_key='workspace_field_id')
        config.master_items_list_id = get_json_parameter(config.master_items_list_config_param_name, expected_key='list_id')
        slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}

        all_tasks_full = get_all_clickup_tasks(config.master_items_list_id, clickup_api_token)

        if not all_tasks_full:
            error_view = {"type": "modal", "title": {"type": "plain_text", "text": "No Items Found"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Sorry, no reorderable items were found."}}], "close": {"type": "plain_text", "text": "Close"}}
            http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": error_view})
            return

        all_tasks_prepared = prepare_tasks_for_state(all_tasks_full, config.workspace_field_id)
        ttl_timestamp = int((datetime.now() + timedelta(hours=1)).timestamp())
        state_table = _get_dynamodb_resource().Table(config.state_table_name)
        state_table.put_item(Item={'view_id': view_id, 'tasks_data': json.dumps(all_tasks_prepared), 'ttl': ttl_timestamp})

        all_workspaces = get_all_workspaces_from_tasks(all_tasks_prepared)
        modal_view = build_slack_modal(all_tasks_prepared, all_workspaces)
        http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": modal_view})

    except Exception as e:
        logger.error("Failed to load data and update view %s: %s", view_id, e, exc_info=True)
        if slack_bot_token:
            error_view = {"type": "modal", "title": {"type": "plain_text", "text": "Error"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"An error occurred: {e}"}}], "close": {"type": "plain_text", "text": "Close"}}
            slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}
            http_session.post("https://slack.com/api/views.update", headers=slack_headers, json={"view_id": view_id, "view": error_view})

def handle_initial_open(trigger_id, slack_headers, context):
    """(SYNC) Handles the initial slash command to open the modal."""
    logger.info("Opening loading modal for trigger_id: %s", trigger_id)
    loading_view = {"type": "modal", "callback_id": "reorder_modal_submit", "title": {"type": "plain_text", "text": "Reorder Item"}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Loading items... :hourglass_flowing_sand:"}}]}
    http_session = requests.Session()
    response = http_session.post("https://slack.com/api/views.open", headers=slack_headers, json={"trigger_id": trigger_id, "view": loading_view})
    response.raise_for_status()
    view_id = response.json()["view"]["id"]

    payload = {"action": "load_data_and_update_view", "view_id": view_id}
    _get_lambda_client().invoke(FunctionName=context.function_name, InvocationType='Event', Payload=json.dumps(payload))
    return {"statusCode": 200, "body": ""}

def lambda_handler(event, context):
    """Main Lambda handler that routes requests based on the event payload."""
    try:
        # Route 1: Asynchronous background processing
        if "action" in event:
            action = event["action"]
            if action == "load_data_and_update_view":
                handle_load_data_and_update_view(event['view_id'])
                return {"statusCode": 200}
            elif action == "process_submission":
                handle_process_submission(event['payload'])
                return {"statusCode": 200}

        # Route 2: Synchronous events from Slack API Gateway
        parsed_body = urllib.parse.parse_qs(event["body"])
        payload_str = parsed_body.get('payload', [None])[0]

        if payload_str:
            payload = json.loads(payload_str)
            payload_type = payload.get("type")

            # Route 2a: User interacts with a block in the modal
            if payload_type == "block_actions":
                config = Config()
                http_session = requests.Session()
                slack_bot_token = get_secret(config.slack_bot_token_secret_name, 'SLACK_MAINTENANCE_BOT_TOKEN')
                return handle_block_actions(payload, http_session, slack_bot_token)

            # Route 2b: User submits the modal
            elif payload_type == "view_submission":
                # Acknowledge immediately with a "processing" message
                processing_view = {"type": "modal", "title": {"type": "plain_text", "text": "Processing..."}, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Your request is being processed. Please wait. :hourglass_flowing_sand:"}}], "close": {"type": "plain_text", "text": "Close"}}
                
                # Asynchronously invoke self to do the slow work
                async_payload = {"action": "process_submission", "payload": payload}
                _get_lambda_client().invoke(FunctionName=context.function_name, InvocationType='Event', Payload=json.dumps(async_payload))
                
                # Return the acknowledgement response to Slack
                return {"statusCode": 200, "body": json.dumps({"response_action": "update", "view": processing_view})}

        # Route 3: Initial slash command to open the modal
        trigger_id = parsed_body.get("trigger_id", [None])[0]
        if not trigger_id:
            raise ValueError("trigger_id not found in request body")

        config = Config()
        slack_bot_token = get_secret(config.slack_bot_token_secret_name, 'SLACK_MAINTENANCE_BOT_TOKEN')
        slack_headers = {"Authorization": f"Bearer {slack_bot_token}", "Content-Type": "application/json; charset=utf-8"}
        return handle_initial_open(trigger_id, slack_headers, context)

    except Exception as e:
        logger.error("An unhandled exception occurred in lambda_handler: %s", e, exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An internal server error occurred."})}
