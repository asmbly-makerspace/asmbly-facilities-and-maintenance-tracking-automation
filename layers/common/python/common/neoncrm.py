import requests
import base64
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Seconds per account request (to connect, and between bytes of the answer), the same
# limit as the ClickUp and Slack helpers. The events search keeps its own 10 seconds.
DEFAULT_TIMEOUT_SECONDS = 8.0

# Stop paginating after this many pages of an events search, so a bad
# `totalPages` can't keep a function calling Neon until it times out.
MAX_SEARCH_PAGES = 50


# Neon v2 answers a rejected request with a JSON list of {"code", "message"} errors. A
# message can quote values from the account (Neon validates the whole account on a
# PATCH), so only this much of it is logged, with emails and long numbers masked.
MAX_LOGGED_ERRORS = 5
MAX_LOGGED_MESSAGE_CHARS = 200
_NEON_ERROR_CODE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+")
# Phone numbers, dates and other IDs: a digit, then 3 or more digits or separators, then a digit.
_LONG_NUMBER_PATTERN = re.compile(r"\d[\d\s().+/-]{3,}\d")
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")


class NeonCRMError(Exception):
    """A Neon call failed. The message carries the operation and HTTP status only."""


def _mask_message(message: str) -> str:
    """Masks emails and long numbers in a Neon error message, flattens it to one line, truncates it."""
    message = _CONTROL_CHARS_PATTERN.sub(" ", message)
    message = _EMAIL_PATTERN.sub("<email>", message)
    message = _LONG_NUMBER_PATTERN.sub("<number>", message)
    if len(message) > MAX_LOGGED_MESSAGE_CHARS:
        message = message[:MAX_LOGGED_MESSAGE_CHARS] + "..."
    return message


def _neon_errors_for_log(response: requests.Response | None) -> str:
    """
    Summarizes Neon's error body for a log line: each error's code (if it looks like a
    code, '<invalid>' if not) and its masked message. Never returns the raw body.
    """
    if response is None:
        return "no body"
    try:
        body = response.json()
    except ValueError:
        return "body is not JSON"
    errors = body if isinstance(body, list) else [body]
    parts = []
    for error in errors[:MAX_LOGGED_ERRORS]:
        if not isinstance(error, dict):
            parts.append("<invalid>")
            continue
        code = error.get("code")
        code = str(code) if isinstance(code, (str, int)) and _NEON_ERROR_CODE_PATTERN.fullmatch(str(code)) else "<invalid>"
        message = error.get("message")
        parts.append(f"{code}: {_mask_message(message)}" if isinstance(message, str) else code)
    if len(errors) > MAX_LOGGED_ERRORS:
        parts.append(f"and {len(errors) - MAX_LOGGED_ERRORS} more")
    return "; ".join(parts) if parts else "no errors listed"


class NeonCRM:
    """A client for interacting with the NeonCRM API v2."""

    def __init__(self, org_id, api_key):
        """
        Initializes the NeonCRM client.

        Args:
            org_id (str): The NeonCRM organization ID.
            api_key (str): The NeonCRM API key.
        """
        self.org_id = org_id
        self.api_key = api_key
        self.base_url = "https://api.neoncrm.com/v2"
        # NeonCRM v2 API requires Basic Authentication.
        auth_string = f"{self.org_id}:{self.api_key}"
        auth_header = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_header}",
        }

    def get_account_by_email(self, email: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str | None:
        """
        Retrieves an account ID by email address.

        Args:
            email (str): The email address to search for.

        Returns:
            str: The account ID if found, otherwise None.
        """
        url = f"{self.base_url}/accounts/search"
        search_payload = {
            "searchFields": [
                {"field": "Email 1", "operator": "EQUAL", "value": email}
            ],
            "outputFields": ["Account ID"],
            "pagination": {"currentPage": 0, "pageSize": 1},
        }
        try:
            response = requests.post(url, headers=self.headers, json=search_payload, timeout=timeout)
            response.raise_for_status()
            results = response.json().get("searchResults", [])
            if results:
                account_id = results[0].get("Account ID")
                logger.info("Found NeonCRM account ID: %s", account_id)
                return account_id
            logger.warning("No NeonCRM account matches the searched email")
            return None
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "no response"
            logger.error("Error searching for NeonCRM account: %s (status %s)", type(e).__name__, status)
            return None

    def update_account_custom_field(
        self, account_id: str, field_id: str, field_value: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """
        Updates a custom field for a given account.

        Args:
            account_id (str): The ID of the account to update.
            field_id (str): The ID of the custom field to update.
            field_value (str): The new value for the custom field.

        Raises:
            NeonCRMError: the update failed, timed out, or Neon rejected it. The log line
                has the status and Neon's masked error codes and messages; the exception's
                message has the HTTP status only.
        """
        url = f"{self.base_url}/accounts/{account_id}"
        update_payload = {
            "individualAccount": {
                "accountCustomFields": [{"id": field_id, "value": field_value}]
            }
        }
        try:
            response = requests.patch(url, headers=self.headers, json=update_payload, timeout=timeout)
            response.raise_for_status()
            logger.info("Updated custom field %s for NeonCRM account %s", field_id, account_id)
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "no response"
            logger.error(
                "Error updating NeonCRM account %s: %s (status %s): %s",
                account_id, type(e).__name__, status, _neon_errors_for_log(e.response),
            )
            raise NeonCRMError(f"accounts/{account_id} update failed (status {status})") from None

    def search_events(
        self,
        search_fields: list[dict[str, str]],
        output_fields: list[str],
        page_size: int = 200,
        timeout: float = 10.0,
        max_pages: int = MAX_SEARCH_PAGES,
    ) -> list[dict[str, Any]]:
        """
        Searches events (read only) and returns the results of every page, up to
        ``max_pages`` pages. ``timeout`` is the requests timeout of each page (to connect,
        and between bytes of the answer).

        Raises:
            NeonCRMError: a call failed, timed out, or returned something other
                than a search result. The message has the HTTP status only.
        """
        url = f"{self.base_url}/events/search"
        results: list[dict[str, Any]] = []
        page = 0
        while True:
            payload = {
                "searchFields": search_fields,
                "outputFields": output_fields,
                "pagination": {"currentPage": page, "pageSize": page_size},
            }
            body = self._post_search(url, payload, timeout)
            results.extend(body["searchResults"])
            pagination = body.get("pagination")
            total_pages = pagination.get("totalPages") if isinstance(pagination, dict) else None
            if not isinstance(total_pages, int) or page + 1 >= total_pages:
                return results
            page += 1
            if page >= max_pages:
                logger.warning("Neon event search stopped at %d of %d pages", max_pages, total_pages)
                return results

    def _post_search(self, url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        """POSTs one page of an events search and returns its JSON body."""
        status = "no response"
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)
            status = f"status {response.status_code}"
            response.raise_for_status()
            body = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error("Neon event search failed: %s (%s)", type(e).__name__, status)
            raise NeonCRMError(f"events/search failed ({status})") from None
        if not isinstance(body, dict) or not isinstance(body.get("searchResults"), list):
            logger.error("Neon event search failed: no searchResults (%s)", status)
            raise NeonCRMError(f"events/search failed ({status})")
        return body
