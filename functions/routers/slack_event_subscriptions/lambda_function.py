import json
import logging
import os
from typing import Any, Optional

import boto3
from botocore.client import BaseClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Built on first use and kept for the life of the container, so a warm invocation
# reuses the client and its connection instead of paying for both again. Not built at
# import, so a URL-verification challenge creates no client.
_ssm_client: Optional[BaseClient] = None
_lambda_client: Optional[BaseClient] = None


def _get_ssm_client() -> BaseClient:
    """Returns the SSM client, creating it on first use."""
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client('ssm')
    return _ssm_client


def _get_lambda_client() -> BaseClient:
    """Returns the Lambda client, creating it on first use."""
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client('lambda')
    return _lambda_client


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
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

        # --- Load Configuration from SSM ---
        config_param_name = os.environ.get("ROUTER_CONFIG_PARAMETER_NAME")
        if not config_param_name:
            # Log an error but return 200 to Slack to prevent retries.
            logger.error("ROUTER_CONFIG_PARAMETER_NAME environment variable not set.")
            return {"statusCode": 200, "body": json.dumps("Internal configuration error.")}

        # A direct client, not common.aws.get_json_parameter: that helper builds a new
        # boto3 session on every call, which would undo the client reuse above.
        parameter = _get_ssm_client().get_parameter(Name=config_param_name)
        router_config = json.loads(parameter['Parameter']['Value'])

        purchase_request_channel_id = router_config.get("purchase_request_channel_id")
        problem_report_channel_id = router_config.get("problem_report_channel_id")

        # --- Determine Target Function ---
        item = event_data.get("item", {})
        channel_id = item.get("channel")

        if not channel_id:
            logger.warning("Event is missing channel ID.")
            return {"statusCode": 200, "body": json.dumps("Event ignored.")}

        target_lambda_arn = None
        if channel_id == purchase_request_channel_id:
            target_lambda_arn = os.environ.get("PURCHASE_REQUEST_LAMBDA_ARN")
        elif channel_id == problem_report_channel_id:
            target_lambda_arn = os.environ.get("PROBLEM_REPORT_LAMBDA_ARN")

        if not target_lambda_arn:
            logger.info(
                "No target function determined for reaction in channel %s. This may be expected.",
                channel_id,
            )
            return {"statusCode": 200, "body": json.dumps("No action taken for this reaction.")}

        # --- Invoke Target Lambda ---
        logger.info("Invoking target Lambda: %s", target_lambda_arn)
        _get_lambda_client().invoke(
            FunctionName=target_lambda_arn,
            InvocationType='Event',  # Asynchronous invocation
            Payload=event["body"]
        )

        return {"statusCode": 200, "body": json.dumps("Request forwarded successfully.")}

    except Exception as e:
        logger.error("An unexpected error occurred: %s", e, exc_info=True)
        # Return 200 to Slack to prevent retries for failed processing
        return {"statusCode": 200, "body": json.dumps("Internal server error occurred.")}
