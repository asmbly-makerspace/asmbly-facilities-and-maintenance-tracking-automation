import json
import logging
import os
import boto3
from common import reaction_processing, aws, clickup

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This is static and can remain in the global scope (removed as it will be an env var)

def lambda_handler(event, context):
    """Handles purchase request reactions by calling the shared processor."""
    logger.info(f"Received event: {event}")
    try:
        # The router function passes the body of the original request directly.
        body = event

        # Immediately handle the challenge before doing anything else
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        # --- Load Configuration Inside the Handler ---
        # Initialize the client here so it can be mocked during tests
        ssm_client = boto3.client('ssm')

        reaction_map_parameter_name = os.environ.get("REACTION_MAP_PARAMETER_NAME")
        if not reaction_map_parameter_name:
            raise ValueError("REACTION_MAP_PARAMETER_NAME environment variable not set.")
        
        slack_secret_name = os.environ.get("SLACK_MAINTENANCE_BOT_SECRET_NAME")
        if not slack_secret_name:
            raise ValueError("SLACK_MAINTENANCE_BOT_SECRET_NAME environment variable not set.")

        clickup_secret_name = os.environ.get("CLICKUP_SECRET_NAME")
        if not clickup_secret_name:
            raise ValueError("CLICKUP_SECRET_NAME environment variable not set.")

        parameter = ssm_client.get_parameter(Name=reaction_map_parameter_name)
        reaction_to_status = json.loads(parameter['Parameter']['Value'])

        # Call the shared logic to parse the event
        result = reaction_processing.process_base_reaction(
            body, reaction_to_status, slack_secret_name, clickup_secret_name
        )

        # If the base processing was successful, perform the ClickUp update
        if result.get("status") == "success":
            task_id = result["task_id"]
            reaction = result["reaction"]
            new_status = reaction_to_status[reaction] # This assumes reaction_to_status is a dict

            clickup_api_token = aws.get_secret(clickup_secret_name, "CLICKUP_API_TOKEN")
            clickup.update_task(clickup_api_token, task_id, {"status": new_status})

        logger.info(f"Processing result: {result}")
        return {"statusCode": 200, "body": json.dumps("Request processed successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}