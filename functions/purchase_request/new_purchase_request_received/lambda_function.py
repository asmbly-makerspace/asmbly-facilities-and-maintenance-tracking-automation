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
    clickup_secret_name = os.environ.get('CLICKUP_SECRET_NAME')
    slack_secret_name = os.environ.get('SLACK_MAINTENANCE_BOT_SECRET_NAME')
    slack_channel = os.environ.get('SLACK_CHANNEL', 'purchase_request')
    slack_bot_name = os.environ.get('SLACK_BOT_NAME', 'Purchase Bot')
    slack_bot_emoji = os.environ.get('SLACK_BOT_EMOJI', ':moneybag:')

    # --- Custom Field IDs ---
    asset_name_field_id = os.environ.get('ASSET_NAME_FIELD_ID')
    requestor_name_field_id = os.environ.get('REQUESTOR_NAME_FIELD_ID')
    supplier_link_field_id = os.environ.get('SUPPLIER_LINK_FIELD_ID')
    workspace_field_id = os.environ.get('WORKSPACE_FIELD_ID')
    item_type_field_id = os.environ.get('ITEM_TYPE_FIELD_ID')
    slack_post_field_id = os.environ.get('SLACK_POST_FIELD_ID')

    try:
        body = json.loads(event.get('body', '{}'))
        task = body.get('payload')

        if not task:
            # Fail early if the payload is invalid, before making any API calls.
            return {'statusCode': 400, 'body': json.dumps('Invalid payload: missing payload.')}

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

        full_task = clickup.get_task(clickup_api_token, task_id)

        # --- Extract Custom Field Values ---
        asset_name = clickup.get_custom_field_value(full_task, asset_name_field_id)
        requestor_name = clickup.get_custom_field_value(full_task, requestor_name_field_id)
        supplier_link = clickup.get_custom_field_value(full_task, supplier_link_field_id)
        workspace = clickup.get_custom_field_value(full_task, workspace_field_id)
        item_type = clickup.get_custom_field_value(full_task, item_type_field_id)

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
            channel_to_attempt=slack_channel,
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
        if slack_post_url and slack_post_field_id:
            update_payload = {"custom_fields": [{"id": slack_post_field_id, "value": slack_post_url}]}
            clickup.update_task(clickup_api_token, task_id, update_payload)
            print(f"Successfully updated task {task_id} with Slack post URL.")

        return {'statusCode': 200, 'body': json.dumps('Successfully processed purchase request.')}

    except Exception as e:
        print(f"An error occurred: {e}")
        return {'statusCode': 500, 'body': json.dumps(f'An error occurred: {str(e)}')}