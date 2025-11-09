import json
import os
import logging
from datetime import datetime

from common.neoncrm import NeonCRM
from common import aws

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def parse_smartwaiver_payload(body: dict) -> tuple[str | None, str | None]:
    """
    Parses a webhook payload from SmartWaiver to extract email and formatted date.

    Args:
        body: The parsed JSON body of the webhook.

    Returns:
        A tuple containing (email, waiver_date in YYYY-MM-DD format) or (None, None) if parsing fails.
    """
    email = body.get("email")
    signed_date_str = body.get("signed_date")

    if not email or not signed_date_str:
        logger.error("Missing 'email' or 'signed_date' in SmartWaiver payload.")
        return None, None
    
    try:
        # Format date to MM/DD/YYYY
        waiver_date = datetime.fromisoformat(signed_date_str.replace("Z", "+00:00")).strftime("%m/%d/%Y")
        return email, waiver_date
    except (ValueError, TypeError) as e:
        logger.error(f"Could not parse date string '{signed_date_str}': {e}")
        return None, None


def update_neon_with_waiver_info(email: str, waiver_date: str) -> dict:
    """
    Updates the 'WaverDate' for a NeonCRM account identified by email.

    Args:
        email: The email of the account to update.
        waiver_date: The waiver date in 'MM/DD/YYYY' format.

    Returns:
        A dictionary with the result of the operation.
    """
    # Get NeonCRM credentials from Secrets Manager using the common aws layer
    secret_name = os.environ["NEON_SECRET_NAME"]
    neoncrm_org_id = aws.get_secret(secret_name, "NEON_ORG_ID")
    neoncrm_api_key = aws.get_secret(secret_name, "NEON_API_KEY")

    # Initialize NeonCRM client and find account
    neoncrm_client = NeonCRM(org_id=neoncrm_org_id, api_key=neoncrm_api_key)
    account_id = neoncrm_client.get_account_by_email(email)

    if not account_id:
        logger.info(f"Clean exit: No NeonCRM account found for email '{email}'. No update performed.")
        return {"statusCode": 404, "body": json.dumps(f"Account not found for email: {email}.")}

    # Update 'WaverDate' custom field
    neoncrm_client.update_account_custom_field(
        account_id=account_id,
        field_name="WaverDate",
        field_value=waiver_date
    )
    return {"statusCode": 200, "body": json.dumps(f"Successfully updated waiver date for {email}.")}


def lambda_handler(event, context):
    """
    Handles a new waiver completion webhook from Smartwaiver.
    Updates the 'WaverDate' custom field in the corresponding NeonCRM account.
    """
    try:
        body = json.loads(event.get("body", "{}"))

        # --- Platform-Specific Parsing ---
        # If you switch from SmartWaiver, you only need to change this one line
        # to call a different parsing function (e.g., parse_otherwaiver_payload).
        email, waiver_date = parse_smartwaiver_payload(body)

        if not email or not waiver_date:
            return {"statusCode": 400, "body": json.dumps("Could not parse required fields from webhook.")}

        # --- Agnostic Business Logic ---
        return update_neon_with_waiver_info(email, waiver_date)

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return {"statusCode": 500, "body": json.dumps("Internal Server Error")}