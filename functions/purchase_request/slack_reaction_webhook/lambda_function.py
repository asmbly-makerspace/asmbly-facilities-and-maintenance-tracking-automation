import json
import logging
import os
import boto3
from common import reaction_processing

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')
SLACK_SECRET_NAME = 'slack-maintenance-bot-token'
CLICKUP_SECRET_NAME = 'clickup/api/token'

def lambda_handler(event, context):
    """Handles purchase request reactions by calling the shared processor."""
    logger.info(f"Received event: {event}")
    try:
        reaction_map_parameter_name = os.environ.get("REACTION_MAP_PARAMETER_NAME")
        parameter = ssm_client.get_parameter(Name=reaction_map_parameter_name)
        reaction_to_status = json.loads(parameter['Parameter']['Value'])

        body = json.loads(event.get("body", "{}"))
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        result = reaction_processing.process_base_reaction(
            body, reaction_to_status, SLACK_SECRET_NAME, CLICKUP_SECRET_NAME
        )

        logger.info(f"Processing result: {result}")
        return {"statusCode": 200, "body": json.dumps("Request processed successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}