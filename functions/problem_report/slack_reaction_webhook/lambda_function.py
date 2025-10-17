import json
import logging
from common import reaction_processing, discourse # <-- Import shared helpers

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration specific to Problem Reports
REACTION_TO_STATUS = {
    "loading": "in progress",
    "truck": "parts ordered",
    "white_check_mark": "Closed",
}
SLACK_SECRET_NAME = 'slack-maintenance-bot-token'
CLICKUP_SECRET_NAME = 'clickup/api/token'

def lambda_handler(event, context):
    """Handles problem report reactions, including Discourse integration."""
    logger.info(f"Received event: {event}")
    try:
        body = json.loads(event.get("body", "{}"))
        if "challenge" in body:
            return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}

        # --- CORE WORKFLOW ---
        result = reaction_processing.process_base_reaction(
            body, REACTION_TO_STATUS, SLACK_SECRET_NAME, CLICKUP_SECRET_NAME
        )
        logger.info(f"Processing result: {result}")

        # --- SPECIFIC BUSINESS LOGIC ---
        if result.get("status") == "success" and result.get("reaction") == "white_check_mark":
            logger.info("Attempting to close associated Discourse post.")
            # Your logic to parse the Discourse post ID from result["message_text"]
            # discourse_post_id = parse_discourse_id(result["message_text"])
            # discourse.close_post(discourse_post_id)

        return {"statusCode": 200, "body": json.dumps("Request processed successfully.")}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps(f"Internal server error: {e}")}