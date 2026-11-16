import json
import os
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import aws, neoncrm

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The waiver ID arrives on an unauthenticated route, so only a plain ID is logged as-is.
_WAIVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _loggable_waiver_id(raw: object) -> str | None:
    """Returns the waiver ID if it looks like an ID, None if absent, otherwise "invalid"."""
    if raw is None:
        return None
    if isinstance(raw, str) and _WAIVER_ID_PATTERN.fullmatch(raw):
        return raw
    return "invalid"


def parse_smartwaiver_payload(body: dict) -> tuple[str | None, str | None, str | None]:
    """
    Parses a webhook payload from SmartWaiver to extract email, formatted date and waiver ID.

    Args:
        body: The parsed JSON body of the webhook.

    Returns:
        A tuple (email, waiver_date in MM/DD/YYYY format, waiver_id). On a parsing failure
        email and waiver_date are None. waiver_id is for logging only: it is None when the
        payload has none, and "invalid" when it doesn't look like an ID. It never decides
        whether the payload is accepted.
    """
    waiver_id = _loggable_waiver_id(body.get("waiver_id"))
    email = body.get("email")
    signed_date_str = body.get("signed_date")

    if not email or not signed_date_str:
        logger.error("Missing 'email' or 'signed_date' in SmartWaiver payload.")
        return None, None, waiver_id

    try:
        # Parse the UTC timestamp
        utc_time = datetime.fromisoformat(signed_date_str.replace("Z", "+00:00"))
        # Convert to Central Time and then format the date
        central_time = utc_time.astimezone(ZoneInfo("America/Chicago"))
        waiver_date = central_time.strftime("%m/%d/%Y")
        return email, waiver_date, waiver_id
    except (ValueError, TypeError) as e:
        # Not the raw string: it comes from an unauthenticated payload.
        logger.error("Could not parse signed_date for waiver %s: %s", waiver_id, type(e).__name__)
        return None, None, waiver_id


def update_neon_with_waiver_info(email: str, waiver_date: str, waiver_id: str | None) -> dict:
    """
    Finds a NeonCRM account by email and updates its 'WaiverDate' custom field.

    This function makes a single PATCH request to the NeonCRM v2 API, which
    is more efficient than making separate GET and PATCH requests.

    Args:
        email: The email of the account to update.
        waiver_date: The waiver date in 'MM/DD/YYYY' format.
        waiver_id: The waiver's ID, used only in log lines.

    Returns:
        An API Gateway response dictionary.
    """
    logger.info("Updating NeonCRM waiver date for waiver %s to %s", waiver_id, waiver_date)

    secret_name = os.environ["NEON_SECRET_NAME"]
    neoncrm_org_id = aws.get_secret(secret_name, "NEON_ORG_ID")
    neoncrm_api_key = aws.get_secret(secret_name, "NEON_API_KEY")

    if not neoncrm_org_id or not neoncrm_api_key:
        logger.error(
            "Failed to retrieve NeonCRM credentials from Secrets Manager secret '%s'. "
            "Please ensure the secret exists and contains the keys 'NEON_ORG_ID' and 'NEON_API_KEY'.",
            secret_name,
        )
        return {"statusCode": 500, "body": json.dumps("Internal Server Error: Missing NeonCRM credentials.")}

    # Initialize the corrected NeonCRM client
    client = neoncrm.NeonCRM(org_id=neoncrm_org_id, api_key=neoncrm_api_key)

    # 1. Get the account ID by email
    account_id = client.get_account_by_email(email)

    if not account_id:
        logger.info("Clean exit: No NeonCRM account found for waiver %s. No update performed.", waiver_id)
        return {"statusCode": 404, "body": json.dumps(f"Account not found for email: {email}")}

    logger.info("Waiver %s matches NeonCRM account %s", waiver_id, account_id)

    # 2. Update the custom field for that account ID
    # Note: The NeonCRM API requires the ID for the custom field, not the name, for PATCH updates.
    try:
        client.update_account_custom_field(account_id=account_id, field_id="179", field_value=waiver_date)
    except neoncrm.NeonCRMError as e:
        # The helper already logged the status and Neon's masked errors. A non-2xx answer
        # makes Smartwaiver retry the webhook (every 5 minutes, up to five times).
        logger.error("WaiverDate not saved for waiver %s on NeonCRM account %s: %s", waiver_id, account_id, e)
        return {"statusCode": 502, "body": json.dumps("Bad Gateway: the NeonCRM update failed.")}

    return {"statusCode": 200, "body": json.dumps(f"Successfully updated waiver date for {email}.")}


def lambda_handler(event: dict, context: object) -> dict:
    """
    Handles a new waiver completion webhook from Smartwaiver.
    Updates the 'WaiverDate' custom field in the corresponding NeonCRM account.
    """
    waiver_id = None
    try:
        logger.info("New waiver webhook received. Processing...")
        body = json.loads(event.get("body", "{}"))

        # --- Platform-Specific Parsing ---
        # If you switch from SmartWaiver, you only need to change this one line
        # to call a different parsing function (e.g., parse_otherwaiver_payload).
        email, waiver_date, waiver_id = parse_smartwaiver_payload(body)

        if not email or not waiver_date:
            logger.warning("Webhook parsing failed for waiver %s. Could not extract required fields.", waiver_id)
            return {"statusCode": 400, "body": json.dumps("Could not parse required fields from webhook.")}

        logger.info("Parsed waiver %s", waiver_id)
        # --- Agnostic Business Logic ---
        response = update_neon_with_waiver_info(email, waiver_date, waiver_id)
        logger.info("Webhook processing completed with status code: %s", response.get("statusCode"))
        return response

    except Exception as e:
        # Log the class only: the exception's text could carry the signer's details.
        logger.error("Unhandled %s while processing waiver %s", type(e).__name__, waiver_id)
        return {"statusCode": 500, "body": json.dumps("Internal Server Error")}
