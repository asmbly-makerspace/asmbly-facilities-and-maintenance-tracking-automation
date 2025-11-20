import json
import logging
import os
from typing import Any, Dict, List, Optional

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
    "timestamp": "Timestamp",
    "additional_info": "Any more details that we should know?",
}
# Static disclaimer text to be used across services
DISCLAIMER_TEXT = "Report generated from a filing. This report has also been sent to Asmbly staff, leadership, and space leads with any contact info that was provided. Provide additional photos or resources here to help. When the problem is resolved, ensure it is marked."

# --- HELPER FUNCTIONS ---

def _get_form_value(form_data: Dict[str, List[str]], key: str, default: Optional[str] = None) -> Optional[str]:
    """Safely retrieves a value from the parsed form data using the FORM_FIELD_MAP."""
    return form_data.get(FORM_FIELD_MAP[key], [default])[0]

def _generate_base_message(report_data: Dict[str, Any]) -> str:
    """Generates the core message content from report data, used by all services."""
    return f"""Problem Type: {report_data['problem_type']}
Workspace:  {report_data['workspace']}
Asset:  {report_data['asset']}
Summary:  {report_data['summary']}
Additional Info:  {report_data['additional_info']}"""

def _get_dropdown_option_id(custom_fields: List[Dict[str, Any]], field_id: str, option_name: str) -> Optional[int]:
    """Finds the orderindex for a dropdown option by its name."""
    for field in custom_fields:
        if field.get('id') == field_id and field.get('type') == 'drop_down':
            options = field.get('type_config', {}).get('options', [])
            for option in options:
                # Case-insensitive and whitespace-insensitive comparison
                if isinstance(option.get('name'), str) and option['name'].strip().lower() == option_name.strip().lower():
                    return option.get('orderindex')
    return None

# --- MAIN HANDLER ---

def lambda_handler(event: Dict[str, Any], context: object) -> Dict[str, Any]:
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
    
    # Load configurations and secrets at the beginning
    logger.info("Loading configurations and secrets...")
    clickup_config_param_name = os.environ['CLICKUP_PROBLEM_REPORTS_CONFIG_PARAM_NAME']
    CLICKUP_CONFIG = aws.get_json_parameter(clickup_config_param_name)
    
    clickup_secret_name = os.environ['CLICKUP_SECRET_NAME']
    clickup_api_token = aws.get_secret(clickup_secret_name, "CLICKUP_API_TOKEN")

    discourse_secret_name = os.environ['DISCOURSE_SECRET_NAME']
    discourse_api_key = aws.get_secret(discourse_secret_name, "DISCOURSE_FACILITIES_BOT_API_KEY")
    discourse_api_username = aws.get_secret(discourse_secret_name, "DISCOURSE_FACILITIES_BOT_API_USERNAME")
    discourse_url = os.environ['DISCOURSE_URL']
    discourse_category_id = os.environ['DISCOURSE_PROBLEM_REPORT_CATEGORY']
    
    slack_secret_name = os.environ['SLACK_MAINTENANCE_BOT_SECRET_NAME']
    slack_bot_token = aws.get_secret(slack_secret_name, "SLACK_MAINTENANCE_BOT_TOKEN")

    # Load Slack configuration from environment variables
    slack_channel_id = os.environ['SLACK_CHANNEL_ID']
    slack_bot_name = os.environ['SLACK_BOT_NAME']
    slack_bot_emoji = os.environ['SLACK_BOT_EMOJI']
    slack_workspace_url = os.environ['SLACK_WORKSPACE_URL']
    logger.info("Configuration and secrets loaded.")

    # Parse form data and build a structured report dictionary
    logger.info("Parsing form data...")
    form_data = google_forms.parse_form_response(event["body"])
    report_data: Dict[str, Any] = {key: _get_form_value(form_data, key) for key in FORM_FIELD_MAP}
    report_data["create_discourse_post"] = _get_form_value(form_data, "create_discourse_post", "No").lower() == "yes"
    logger.info("Parsed report data. Summary: '%s'. Create Discourse post: %s", report_data['summary'], report_data['create_discourse_post'])

    # Generate message content for different platforms
    base_message = _generate_base_message(report_data)
    clickup_disclaimer = f"*{DISCLAIMER_TEXT}*"
    slack_disclaimer = f"_{DISCLAIMER_TEXT}_"

    # Step 1: Create ClickUp Task
    logger.info("Step 1: Creating ClickUp task...")
    initial_task_description = f'{base_message}\n\nDiscourse Link: {"Pending" if report_data["create_discourse_post"] else "Opted Out. Slack notification Only."}\nSlack Post: Pending\n\n{clickup_disclaimer}'
    clickup_task = None
    try:
        # Fetch custom fields to map dropdowns
        list_custom_fields = clickup.get_list_custom_fields(clickup_api_token, CLICKUP_CONFIG["list_id"])
        
        # Map form text values to ClickUp dropdown option IDs (orderindex)
        custom_fields_payload = []
        
        # Safely add fields to payload only if their config ID exists
        if contact_details_field_id := CLICKUP_CONFIG.get("contact_details_field_id"):
            custom_fields_payload.append({"id": contact_details_field_id, "value": report_data["contact_details"]})
        
        if asset_field_id := CLICKUP_CONFIG.get("asset_field_id"):
            custom_fields_payload.append({"id": asset_field_id, "value": report_data["asset"]})
            
        if problem_type_field_id := CLICKUP_CONFIG.get("problem_type_field_id"):
            problem_type_option_id = _get_dropdown_option_id(list_custom_fields, problem_type_field_id, report_data["problem_type"])
            if problem_type_option_id is not None:
                custom_fields_payload.append({"id": problem_type_field_id, "value": problem_type_option_id})
        
        if workspace_field_id := CLICKUP_CONFIG.get("workspace_field_id"):
            workspace_option_id = _get_dropdown_option_id(list_custom_fields, workspace_field_id, report_data["workspace"])
            if workspace_option_id is not None:
                custom_fields_payload.append({"id": workspace_field_id, "value": workspace_option_id})
                
        task_payload = {
            "name": report_data["summary"],
            "description": initial_task_description,
            "custom_fields": custom_fields_payload
        }
        clickup_task = clickup.create_task(clickup_api_token, CLICKUP_CONFIG["list_id"], task_payload)
        logger.info("Successfully created ClickUp task: %s", clickup_task.get('url'))
    except Exception as e:
        logger.error("Error creating ClickUp task: %s", e)

    # Step 2: Create Discourse Post if requested
    discourse_post_url = None
    if report_data["create_discourse_post"]:
        logger.info("Step 2: Creating Discourse post...")
        try:
            discourse_content = f"{base_message}\n\n{clickup_disclaimer}"
            discourse_title = f"{report_data['timestamp']} - {report_data['workspace']} - {report_data['asset']}"
            discourse_post_url = discourse.create_post(
                base_url=discourse_url, 
                title=discourse_title, 
                content=discourse_content, 
                api_key=discourse_api_key, 
                api_username=discourse_api_username,
                category_id=discourse_category_id
            )
            logger.info("Successfully created Discourse post: %s", discourse_post_url)
        except Exception as e:
            logger.error("Error creating Discourse post: %s", e)
    else:
        logger.info("Step 2: Skipping Discourse post creation as per user request.")

    # Step 3: Send Slack Message
    logger.info("Step 3: Sending Slack notification...")
    discourse_link_text = discourse_post_url or ("Error creating post" if report_data["create_discourse_post"] else "Opted Out. Slack notification Only.")
    clickup_task_url = clickup_task['url'] if clickup_task else "Error creating task"
    slack_message_text = f'{base_message}\nContact Details: {report_data["contact_details"]}\n\nDiscourse Link: {discourse_link_text}\nClickUp Task: {clickup_task_url}\n\n{slack_disclaimer}'
    slack_post_url = None
    try:
        slack_response = slack.send_slack_message(
            token=slack_bot_token,
            channel_to_attempt=slack_channel_id,
            text=slack_message_text,
            bot_name=slack_bot_name,
            icon_emoji=slack_bot_emoji
        )
        if slack_response.get('ok'):
            slack_post_url = slack.get_slack_post_url(slack_workspace_url, slack_response['channel'], slack_response['ts'])
            logger.info("Successfully sent Slack notification: %s", slack_post_url)
        else:
            logger.error("Failed to send Slack message: %s", slack_response.get('error'))
    except Exception as e:
        logger.error("Error sending Slack message: %s", e)

    # Step 4: Update ClickUp Task with final details
    if clickup_task:
        logger.info("Step 4: Updating ClickUp task with final URLs...")
        try:
            slack_link_text = slack_post_url or "Error sending notification"
            final_task_description = f'{base_message}\n\nDiscourse Link: {discourse_link_text}\nSlack Post: {slack_link_text}\n\n{clickup_disclaimer}'
            
            # Start with the description update
            update_payload: Dict[str, Any] = {"description": final_task_description}
            
            # Conditionally build the list of custom fields to update
            custom_fields_to_update = []
            if discourse_post_url:
                custom_fields_to_update.append({"id": CLICKUP_CONFIG["discourse_post_field_id"], "value": discourse_post_url})
            if slack_post_url:
                custom_fields_to_update.append({"id": CLICKUP_CONFIG["slack_post_field_id"], "value": slack_post_url})
            
            # Only add the 'custom_fields' key to the payload if there are fields to update
            if custom_fields_to_update:
                update_payload["custom_fields"] = custom_fields_to_update

            clickup.update_task(clickup_api_token, clickup_task["id"], update_payload)
            logger.info("Successfully updated ClickUp task.")
        except Exception as e:
            logger.error("Error updating ClickUp task: %s", e)
    else:
        logger.warning("Step 4: Skipping ClickUp task update because task creation failed.")

    logger.info("Problem report processing finished.")
    return {"statusCode": 200, "body": json.dumps("Problem report processed successfully.")}
