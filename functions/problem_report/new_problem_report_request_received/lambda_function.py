import json
import logging
import os

from common import aws, clickup, discourse, google_forms, slack

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- CONFIGURATIONS ---
# Map human-readable names to the exact (and potentially long) field names from the Google Form
FORM_FIELD_MAP = {
    "problem_type": "What kind of problem would you like to report?",
    "contact_details": "Please leave your name and phone number (optional). We may be able to resolve by phone or text and can follow up with you, especially if we need more information.  ",
    "create_discourse_post": "Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.",
    "workspace": "What Area is this in?",
    "asset": "Which piece of equipment, if applicable?  ",
    "summary": "In a few words, what is the problem?",
    "additional_info": "Any more details that we should know?",
}
# Static disclaimer text to be used across services
DISCLAIMER_TEXT = "Report generated from a filing. This report has also been sent to Asmbly staff, leadership, and space leads with any contact info that was provided. Provide additional photos or resources here to help. When the problem is resolved, ensure it is marked."

# --- HELPER FUNCTIONS ---

def _get_form_value(form_data, key, default=None):
    """Safely retrieves a value from the parsed form data using the FORM_FIELD_MAP."""
    return form_data.get(FORM_FIELD_MAP[key], [default])[0]

def _generate_base_message(report_data):
    """Generates the core message content from report data, used by all services."""
    return f"""Problem Type: {report_data['problem_type']}
Workspace:  {report_data['workspace']}
Asset:  {report_data['asset']}
Summary:  {report_data['summary']}
Additional Info:  {report_data['additional_info']}"""

# --- MAIN HANDLER ---

def lambda_handler(event, context):
    """
    Main Lambda entry point.
    Orchestrates the entire process of handling a new problem report:
    1. Parses the incoming Google Form data.
    2. Creates a ClickUp task.
    3. Creates a Discourse post (if requested).
    4. Sends a Slack notification.
    5. Updates the ClickUp task with the Discourse and Slack post URLs.
    """
    logger.info("New problem report request received. Starting processing.")
    
    # Load configurations from SSM Parameter Store
    clickup_config_param_name = os.environ['CLICKUP_PROBLEM_REPORTS_CONFIG_PARAM_NAME']
    CLICKUP_CONFIG = aws.get_json_parameter(clickup_config_param_name)

    # Initialize APIs with secrets
    secrets = aws.get_secret(os.environ["SECRETS_ARN"])
    clickup_api = clickup.ClickUp(secrets["CLICKUP_API_KEY"])
    discourse_api = discourse.Discourse(secrets["DISCOURSE_API_KEY"], secrets["DISCOURSE_API_USERNAME"], secrets["DISCOURSE_URL"])

    # Parse form data and build a structured report dictionary
    form_data = google_forms.parse_form_response(event["body"])
    report_data = {key: _get_form_value(form_data, key) for key in FORM_FIELD_MAP}
    report_data["create_discourse_post"] = _get_form_value(form_data, "create_discourse_post", "No").lower() == "yes"
    logger.info(f"Parsed report data. Summary: '{report_data['summary']}'. Create Discourse post: {report_data['create_discourse_post']}")

    # Generate message content for different platforms
    base_message = _generate_base_message(report_data)
    clickup_disclaimer = f"*{DISCLAIMER_TEXT}*"
    slack_disclaimer = f"_{DISCLAIMER_TEXT}_"

    # Step 1: Create ClickUp Task with initial description
    logger.info("Step 1: Creating ClickUp task...")
    initial_task_description = f'{base_message}\n\nDiscourse Link: {"Pending" if report_data["create_discourse_post"] else "Opted Out. Slack notification Only."}\nSlack Post: Pending\n\n{clickup_disclaimer}'
    clickup_task = None
    try:
        clickup_task = clickup_api.create_task(
            CLICKUP_CONFIG["list_id"],
            report_data["summary"],
            initial_task_description,
            custom_fields=[
                {"id": CLICKUP_CONFIG["problem_type_field_id"], "value": report_data["problem_type"]},
                {"id": CLICKUP_CONFIG["contact_details_field_id"], "value": report_data["contact_details"]},
            ]
        )
        logger.info(f"Successfully created ClickUp task: {clickup_task.get('url')}")
    except Exception as e:
        logger.error(f"Error creating ClickUp task: {e}")

    # Step 2: Create Discourse Post if requested
    discourse_post_url = None
    if report_data["create_discourse_post"]:
        logger.info("Step 2: Creating Discourse post...")
        try:
            discourse_content = f"{base_message}\n\n{clickup_disclaimer}"
            discourse_post_url = discourse_api.create_post(title=f"Problem Report: {report_data['summary']}", content=discourse_content)
            logger.info(f"Successfully created Discourse post: {discourse_post_url}")
        except Exception as e:
            logger.error(f"Error creating Discourse post: {e}")
    else:
        logger.info("Step 2: Skipping Discourse post creation as per user request.")

    # Step 3: Send Slack Message
    logger.info("Step 3: Sending Slack notification...")
    discourse_link_text = discourse_post_url or ("Error creating post" if report_data["create_discourse_post"] else "Opted Out. Slack notification Only.")
    clickup_task_url = clickup_task['url'] if clickup_task else "Error creating task"
    slack_message_text = f'{base_message}\nContact Details: {report_data["contact_details"]}\n\nDiscourse Link: {discourse_link_text}\nClickUp Task: {clickup_task_url}\n\n{slack_disclaimer}'
    slack_post_url = None
    try:
        slack_response = slack.send_slack_message(secrets["SLACK_WEBHOOK_URL"], slack_message_text)
        slack_post_url = slack_response.get('url')
        logger.info(f"Successfully sent Slack notification: {slack_post_url}")
    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")

    # Step 4: Update ClickUp Task with final details
    if clickup_task:
        logger.info("Step 4: Updating ClickUp task with final URLs...")
        try:
            slack_link_text = slack_post_url or "Error sending notification"
            final_task_description = f'{base_message}\n\nDiscourse Link: {discourse_link_text}\nSlack Post: {slack_link_text}\n\n{clickup_disclaimer}'
            
            update_payload = {"description": final_task_description}
            custom_fields_to_update = []
            if discourse_post_url:
                custom_fields_to_update.append({"id": CLICKUP_CONFIG["discourse_post_field_id"], "value": discourse_post_url})
            if slack_post_url:
                custom_fields_to_update.append({"id": CLICKUP_CONFIG["slack_post_field_id"], "value": slack_post_url})
            
            if custom_fields_to_update:
                update_payload["custom_fields"] = custom_fields_to_update

            clickup_api.update_task(clickup_task["id"], update_payload)
            logger.info("Successfully updated ClickUp task.")
        except Exception as e:
            logger.error(f"Error updating ClickUp task: {e}")
    else:
        logger.warning("Step 4: Skipping ClickUp task update because task creation failed.")

    logger.info("Problem report processing finished.")
    return {"statusCode": 200, "body": json.dumps("Problem report processed successfully.")}
