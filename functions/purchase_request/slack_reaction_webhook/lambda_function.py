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

# Reaction to status mapping from reaction to ClickUp status name
REACTION_TO_STATUS = {
    "loading": "in review",
    "truck": "purchased",
    "house": "delivered",
    "no_entry_sign": "declined",
    "white_check_mark": "Closed",
}

# Mapping from status name to ClickUp status ID
STATUS_NAME_TO_ID = {
    "in review": "sc901310302436_af0Y5Erf",
    "purchased": "sc901310302436_2E6Zn1Xp",
    "delivered": "sc901310302436_EWDBr1Jw",
    "declined": "sc901310302436_WBeguowd",
    "Closed": "sc901310302436_xYvx2MbY",
}

def lambda_handler(event, context):
    """
    Handles a Slack reaction webhook to update a ClickUp task status.
    """
    logger.info(f"Received event: {json.dumps(event)}")
    body = json.loads(event.get("body", "{}"))

    # Handle Slack URL verification
    if "challenge" in body:
        return {
            "statusCode": 200,
            "body": json.dumps({"challenge": body["challenge"]})
        }

    slack_event = body.get("event", {})
    if not slack_event or slack_event.get("type") != "reaction_added":
        logger.info("Not a reaction_added event.")
        return {"statusCode": 200, "body": json.dumps("Event received.")}

    reaction = slack_event.get("reaction")
    if reaction not in REACTION_TO_STATUS:
        logger.info(f"Ignoring reaction: {reaction}")
        return {"statusCode": 200, "body": json.dumps("Irrelevant reaction.")}

    try:
        # Get environment variables within the handler for testability
        clickup_secret_name = os.environ.get("CLICKUP_SECRET_NAME")
        slack_secret_name = os.environ.get("SLACK_MAINTENANCE_BOT_SECRET_NAME")

        # Get Slack token from AWS Secrets Manager
        slack_bot_token = aws.get_secret(slack_secret_name, "SLACK_BOT_TOKEN")
        slack_client = WebClient(token=slack_bot_token)

        item = slack_event.get("item", {})
        channel_id = item.get("channel")
        message_ts = item.get("ts")

        # Fetch the message that was reacted to
        history = slack_client.conversations_history(
            channel=channel_id,
            latest=message_ts,
            inclusive=True,
            limit=1
        )

        if not history["messages"]:
            logger.error("Could not find message from reaction event.")
            return {"statusCode": 404, "body": json.dumps("Message not found.")}

        message_text = history["messages"][0].get("text", "")

        # Parse ClickUp task ID from the message
        match = re.search(r"https://app\.clickup\.com/t/(\w+)", message_text)
        if not match:
            logger.info("No ClickUp task URL found in the message.")
            return {"statusCode": 200, "body": json.dumps("No ClickUp task ID found.")}

        task_id = match.group(1)

        # Get new status from reaction
        new_status_name = REACTION_TO_STATUS[reaction]
        new_status_id = STATUS_NAME_TO_ID[new_status_name]

        # Get ClickUp token from AWS Secrets Manager
        clickup_api_token = aws.get_secret(clickup_secret_name, "CLICKUP_API_TOKEN")

        # Update ClickUp task status
        payload = {"status": new_status_id}
        clickup.update_task(clickup_api_token, task_id, payload)

        logger.info(f"Updated ClickUp task {task_id} to status '{new_status_name}'")
        return {"statusCode": 200, "body": json.dumps("Task status updated successfully.")}

    except SlackApiError as e:
        logger.error(f"Slack API error: {e.response['error']}")
        return {"statusCode": 500, "body": json.dumps("Error communicating with Slack.")}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}