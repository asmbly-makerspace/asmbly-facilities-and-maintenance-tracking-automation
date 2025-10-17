import json
import logging
import os
import re

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from common import aws, clickup

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Constants ---
REACTION_TO_STATUS = {
    "loading": "in review",
    "truck": "purchased",
    "house": "delivered",
    "no_entry_sign": "declined",
    "white_check_mark": "Closed",
}

# --- Helper Function for Configuration ---
def _get_config():
    """
    Loads and validates all required environment variables.
    Raises ValueError if a required variable is missing.
    """
    clickup_secret_name = os.environ.get("CLICKUP_SECRET_NAME")
    slack_secret_name = os.environ.get("SLACK_MAINTENANCE_BOT_SECRET_NAME")

    if not all([clickup_secret_name, slack_secret_name]):
        logger.error("Missing required environment variables: CLICKUP_SECRET_NAME or SLACK_MAINTENANCE_BOT_SECRET_NAME")
        raise ValueError("Missing required environment variables for secret names.")

    return {
        "clickup_secret_name": clickup_secret_name,
        "slack_secret_name": slack_secret_name,
    }

# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    Handles a Slack reaction webhook to update a ClickUp task status.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        body = json.loads(event.get("body", "{}"))

        # Handle Slack URL verification challenge immediately.
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        # Now, load the configuration for all other event types.
        config = _get_config()

        slack_event = body.get("event", {})
        if not slack_event or slack_event.get("type") != "reaction_added":
            return {"statusCode": 200, "body": json.dumps("Event is not a reaction_added event.")}

        reaction = slack_event.get("reaction")
        if reaction not in REACTION_TO_STATUS:
            return {"statusCode": 200, "body": json.dumps(f"Ignoring irrelevant reaction: {reaction}")}

        # Get Slack token and initialize client
        slack_bot_token = aws.get_secret(config["slack_secret_name"], "SLACK_MAINTENANCE_BOT_TOKEN")
        slack_client = WebClient(token=slack_bot_token)

        # Fetch the message that was reacted to
        item = slack_event.get("item", {})
        history = slack_client.conversations_history(
            channel=item.get("channel"),
            latest=item.get("ts"),
            inclusive=True,
            limit=1
        )

        if not history.get("messages"):
            logger.error("Could not find message from reaction event.")
            return {"statusCode": 404, "body": json.dumps("Message not found.")}

        # Parse ClickUp task ID from the message
        message_text = history["messages"][0].get("text", "")
        match = re.search(r"https://app\.clickup\.com/t/(\w+)", message_text)
        if not match:
            return {"statusCode": 200, "body": json.dumps("No ClickUp task URL found in the message.")}

        task_id = match.group(1)

        # Get new status name from the reaction
        new_status_name = REACTION_TO_STATUS[reaction]

        # Get ClickUp token and update the task
        clickup_api_token = aws.get_secret(config["clickup_secret_name"], "CLICKUP_API_TOKEN")

        # Construct the payload using the status NAME, which is confirmed to work
        payload = {"status": new_status_name}
        clickup.update_task(clickup_api_token, task_id, payload)

        logger.info(f"Updated ClickUp task {task_id} to status '{new_status_name}'")
        return {"statusCode": 200, "body": json.dumps("Task status updated successfully.")}

    except (ValueError, SlackApiError) as e:
        logger.error(f"A handled error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Server error: {e}")}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}