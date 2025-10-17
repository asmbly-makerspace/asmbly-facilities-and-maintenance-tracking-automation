import json
import logging
import os
import boto3
from common import reaction_processing, aws

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')

# Fetch configuration from SSM Parameter Store
REACTION_MAP_PARAMETER_NAME = os.environ.get("REACTION_MAP_PARAMETER_NAME")
parameter = ssm_client.get_parameter(Name=REACTION_MAP_PARAMETER_NAME)
REACTION_TO_STATUS = json.loads(parameter['Parameter']['Value'])

SLACK_SECRET_NAME = 'slack-maintenance-bot-token'
CLICKUP_SECRET_NAME = 'clickup/api/token'
DISCOURSE_SECRET_NAME = 'discourse/api/token' # Example secret name

def lambda_handler(event, context):
    """Handles problem report reactions, including Discourse integration."""
    logger.info(f"Received event: {event}")
    try:
        body = json.loads(event.get("body", "{}"))
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        # --- Call the shared logic first ---
        result = reaction_processing.process_base_reaction(
            body, REACTION_TO_STATUS, SLACK_SECRET_NAME, CLICKUP_SECRET_NAME
        )
        logger.info(f"Base processing result: {result}")

        # --- Execute specific logic for this handler ---
        if result.get("status") == "success" and result.get("reaction") == "white_check_mark":
            logger.info("Attempting to close associated Discourse post.")
            # Your custom logic to parse the Discourse post ID from result["message_text"] goes here
            # For example: discourse_post_id = parse_discourse_id(result["message_text"])

            # Example call to a discourse helper
            # if discourse_post_id:
            #     discourse_api_key = aws.get_secret(DISCOURSE_SECRET_NAME, "API_KEY")
            #     discourse.close_post(discourse_api_key, discourse_post_id)

        return {"statusCode": 200, "body": json.dumps("Request processed successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}