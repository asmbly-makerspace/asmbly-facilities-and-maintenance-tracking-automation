import json
import os
from common import clickup, slack, aws


def get_slack_post_url(channel_id, message_ts):
    """Constructs the permalink for a Slack message."""
    slack_workspace_url = os.environ.get('SLACK_WORKSPACE_URL')
    if not slack_workspace_url:
        print("SLACK_WORKSPACE_URL environment variable not set. Cannot generate permalink.")
        return None
    # Timestamp needs to be without the dot for the URL
    ts_for_url = message_ts.replace('.', '')
    return f"{slack_workspace_url}/archives/{channel_id}/p{ts_for_url}"


def lambda_handler(event, context):
    """
    Handles a webhook from ClickUp for a new purchase request.

    This function processes the payload from a ClickUp task creation,
    sends a notification to a specified Slack channel, and then updates
    the ClickUp task with a link to the Slack notification.
    """
    # --- Environment Variables ---
    # Fail fast if any required environment variables are missing.
    required_env_vars = {
        'CLICKUP_SECRET_NAME',
        'SLACK_MAINTENANCE_BOT_SECRET_NAME',
        'SLACK_CHANNEL_ID',
        'SLACK_WORKSPACE_URL',
        'CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME',
        'CLICKUP_PURCHASE_REQUESTS_CONFIG_PARAM_NAME'
    }
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        error_message = f"Missing required environment variables: {', '.join(missing_vars)}"
        print(error_message)
        return {'statusCode': 500, 'body': json.dumps(error_message)}

    clickup_secret_name = os.environ['CLICKUP_SECRET_NAME']
    slack_secret_name = os.environ['SLACK_MAINTENANCE_BOT_SECRET_NAME']
    slack_channel_id = os.environ['SLACK_CHANNEL_ID']
    slack_bot_name = os.environ.get('SLACK_BOT_NAME', 'Purchase Bot')
    slack_bot_emoji = os.environ.get('SLACK_BOT_EMOJI', ':moneybag:')
    workspace_field_id_param_name = os.environ['CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME']
    purchase_requests_config_param_name = os.environ['CLICKUP_PURCHASE_REQUESTS_CONFIG_PARAM_NAME']

    try:
        body = json.loads(event.get('body', '{}'))

        # ClickUp sends a test payload that is just a string.
        # Real events have a 'trigger_id'. If it's missing, it's either a test
        # or an event we don't care about. Respond with 200 to satisfy the test.
        if 'trigger_id' not in body:
            print("Received a request without a 'trigger_id'. Likely a ClickUp test. Responding with 200 OK.")
            return {'statusCode': 200, 'body': json.dumps('Webhook test successful or unhandled event type.')}

        task = body.get('payload')
        if not task: return {'statusCode': 400, 'body': json.dumps('Invalid payload: missing task payload.')}

        task_id = task.get('id')
        if not task_id:
            return {'statusCode': 400, 'body': json.dumps('Invalid payload: missing task ID.')}

        task_name = task.get('name')
        task_url = f"https://app.clickup.com/t/{task_id}"
        task_description = task.get('text_content', 'No description provided.')

        # --- Fetch Full Task Details to get Custom Field Values ---
        # The webhook payload has a different structure for custom fields.
        # We fetch the task again to get the standard format.
        # Now that we have a valid task ID, we can fetch secrets.
        clickup_api_token = aws.get_secret(clickup_secret_name, "CLICKUP_API_TOKEN")
        slack_api_token = aws.get_secret(slack_secret_name, "SLACK_MAINTENANCE_BOT_TOKEN")
        workspace_field_id = aws.get_json_parameter(workspace_field_id_param_name, expected_key='workspace_field_id')
        purchase_requests_config = aws.get_json_parameter(purchase_requests_config_param_name)

        full_task = clickup.get_task(clickup_api_token, task_id)

        # --- Extract Custom Field Values ---
        asset_name = clickup.get_custom_field_value(full_task, purchase_requests_config['asset_name_field_id'])
        requestor_name = clickup.get_custom_field_value(full_task, purchase_requests_config['requestor_name_field_id'])
        supplier_link = clickup.get_custom_field_value(full_task, purchase_requests_config['supplier_link_field_id'])
        workspace = clickup.get_custom_field_value(full_task, workspace_field_id)
        item_type = clickup.get_custom_field_value(full_task, purchase_requests_config['item_type_field_id'])

        # --- 1. Send Slack Notification ---
        message_lines = [
            "New purchase request received\n",
            f"Item Requested: {task_name}",
            f"Link: {supplier_link or 'N/A'}",
            f"Workspace: {workspace or 'N/A'}",
            f"Asset: {asset_name or 'N/A'}",
            f"Item Type: {item_type or 'N/A'}",
            f"Purpose: {task_description}",
            f"Requested By: {requestor_name or 'N/A'}",
            f"ClickUp: {task_url}"
        ]
        slack_message_text = "\n".join(message_lines)

        slack_response = slack.send_slack_message(
            token=slack_api_token,
            channel_to_attempt=slack_channel_id,
            text=slack_message_text,
            bot_name=slack_bot_name,
            icon_emoji=slack_bot_emoji
        )

        if not slack_response.get('ok'):
            print(f"Failed to send Slack message: {slack_response.get('error')}")
            # Decide if you want to fail the whole execution or just log
            return {'statusCode': 500, 'body': json.dumps('Failed to send Slack message.')}

        # --- 2. Update ClickUp Task with Slack Post URL ---
        slack_post_url = get_slack_post_url(slack_response['channel'], slack_response['ts'])
        print(f"Generated Slack permalink: {slack_post_url}")

        slack_post_field_id = purchase_requests_config['slack_post_field_id']
        print(f"Attempting to set custom field '{slack_post_field_id}' on task {task_id}.")
        update_response = clickup.set_custom_field_value(clickup_api_token, task_id, slack_post_field_id, slack_post_url)
        print(f"Received response from ClickUp update API: {json.dumps(update_response)}")
        print(f"Successfully updated task {task_id} with Slack post URL.")

        return {'statusCode': 200, 'body': json.dumps('Successfully processed purchase request.')}

    except Exception as e:
        print(f"An error occurred: {e}")
        return {'statusCode': 500, 'body': json.dumps(f'An error occurred: {str(e)}')}