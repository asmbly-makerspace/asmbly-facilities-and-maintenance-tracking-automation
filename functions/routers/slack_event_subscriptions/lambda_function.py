import json
import logging
import os
import boto3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Routes Slack reaction events to the appropriate Lambda function
    based on the content of the message that was reacted to.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        body = json.loads(event.get("body", "{}"))

        # Handle Slack's URL verification challenge
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        event_data = body.get("event", {})
        if event_data.get("type") != "reaction_added":
            logger.info("Ignoring event that is not 'reaction_added'.")
            return {"statusCode": 200, "body": json.dumps("Event ignored.")}

        # --- Determine Target Function ---
        item = event_data.get("item", {})
        channel_id = item.get("channel")

        if not channel_id:
            logger.warning("Event is missing channel ID.")
            return {"statusCode": 200, "body": json.dumps("Event ignored.")}

        target_lambda_arn = None
        if channel_id == os.environ.get("PURCHASE_REQUEST_CHANNEL_ID"):
            target_lambda_arn = os.environ.get("PURCHASE_REQUEST_LAMBDA_ARN")
        elif channel_id == os.environ.get("PROBLEM_REPORT_CHANNEL_ID"):
            target_lambda_arn = os.environ.get("PROBLEM_REPORT_LAMBDA_ARN")

        if not target_lambda_arn:
            logger.info(
                f"No target function determined for reaction in channel {channel_id}. This may be expected."
            )
            return {"statusCode": 200, "body": json.dumps("No action taken for this reaction.")}

        # --- Invoke Target Lambda ---
        logger.info(f"Invoking target Lambda: {target_lambda_arn}")
        lambda_client = boto3.client('lambda')
        lambda_client.invoke(
            FunctionName=target_lambda_arn,
            InvocationType='Event',  # Asynchronous invocation
            Payload=event["body"]
        )

        return {"statusCode": 200, "body": json.dumps("Request forwarded successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        # Return 200 to Slack to prevent retries for failed processing
        return {"statusCode": 200, "body": json.dumps(f"Internal server error occurred.")}