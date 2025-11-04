import json
import logging
import os
import boto3
from common import reaction_processing, aws, clickup, discourse

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_SECRET_NAME = 'slack-maintenance-bot-token'
CLICKUP_SECRET_NAME = 'clickup/api/token'
# The secret name is the same across all stages as requested.
DISCOURSE_SECRET_NAME = 'prod/discourse-facilities-bot'


def lambda_handler(event, context):
    """Handles problem report reactions, including Discourse integration."""
    logger.info(f"Received event: {event}")
    try:
        # The router function passes the body of the original request directly.
        body = event

        # Handle Slack's URL verification challenge
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        # --- Load Configuration ---
        ssm_client = boto3.client('ssm')
        reaction_map_param_name = os.environ.get("REACTION_MAP_PARAMETER_NAME")
        if not reaction_map_param_name:
            raise ValueError("REACTION_MAP_PARAMETER_NAME environment variable not set.")

        parameter = ssm_client.get_parameter(Name=reaction_map_param_name)
        # This map is more complex: {"reaction": {"clickup_status": "...", "discourse_post_message": "...", ...}}
        reaction_config_map = json.loads(parameter['Parameter']['Value'])

        # --- Process Reaction ---
        # The base processor will find the message, parse the ClickUp ID, and check if the reaction is relevant.
        result = reaction_processing.process_base_reaction(
            body,
            # Pass the keys of the config map so the base processor knows which reactions are valid.
            list(reaction_config_map.keys()),
            SLACK_SECRET_NAME,
            CLICKUP_SECRET_NAME
        )
        logger.info(f"Base processing result: {result}")

        # If the reaction was processed and a ClickUp task was found...
        if result.get("status") == "success":
            reaction = result["reaction"]
            task_id = result["task_id"]
            message_text = result["message_text"]
            config = reaction_config_map.get(reaction, {})

            # --- 1. Update ClickUp Task ---
            clickup_status = config.get("clickup_status")
            if clickup_status:
                logger.info(f"Updating ClickUp task {task_id} to status '{clickup_status}'")
                clickup_api_token = aws.get_secret(CLICKUP_SECRET_NAME, "CLICKUP_API_TOKEN")
                clickup.update_task(clickup_api_token, task_id, {"status": clickup_status})
            else:
                logger.warning(f"No 'clickup_status' defined for reaction '{reaction}'")

            # --- 2. Update Discourse Post ---
            discourse_info = discourse.parse_discourse_url(message_text)
            discourse_message_config = config.get("discourse_post_message")
            discourse_message = None

            if isinstance(discourse_message_config, list):
                discourse_message = "\n".join(discourse_message_config)
            elif isinstance(discourse_message_config, str):
                discourse_message = discourse_message_config

            if discourse_info and discourse_message:
                logger.info(f"Found Discourse link. Preparing to post reply. Info: {discourse_info}")
                discourse_api_key = aws.get_secret(DISCOURSE_SECRET_NAME, "DISCOURSE_FACILITIES_BOT_API_KEY")
                discourse_api_user = aws.get_secret(DISCOURSE_SECRET_NAME, "DISCOURSE_FACILITIES_BOT_API_USERNAME")

                # Post the reply message
                reply_response = discourse.post_reply(
                    base_url=discourse_info["base_url"],
                    topic_id=discourse_info["topic_id"],
                    post_number=discourse_info["post_number"],
                    message=discourse_message,
                    api_key=discourse_api_key,
                    api_username=discourse_api_user
                )
                logger.info(f"Discourse reply response: {reply_response}")

                # Mark as solution if configured and the reply was successful
                if config.get("discourse_mark_solution") and reply_response.get("id"):
                    new_post_id = reply_response["id"]
                    logger.info(f"Marking new Discourse post {new_post_id} as solution.")
                    discourse.mark_solution(
                        base_url=discourse_info["base_url"],
                        post_id=new_post_id,
                        api_key=discourse_api_key,
                        api_username=discourse_api_user
                    )

        return {"statusCode": 200, "body": json.dumps("Request processed successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}