import requests
import base64
import logging
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Stop paginating after this many pages of an events search, so a bad
# `totalPages` can't keep a function calling Neon until it times out.
MAX_SEARCH_PAGES = 50


class NeonCRMError(Exception):
    """A Neon call failed. The message carries the operation and HTTP status only."""


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

    def get_account_by_email(self, email: str) -> str | None:
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
            response = requests.post(url, headers=self.headers, json=search_payload)
            response.raise_for_status()
            results = response.json().get("searchResults", [])
            if results:
                account_id = results[0].get("Account ID")
                logger.info("Found NeonCRM account ID: %s", account_id)
                return account_id
            logger.warning("No NeonCRM account matches the searched email")
            return None
        except requests.exceptions.RequestException as e:
            logger.error("Error searching for NeonCRM account: %s", type(e).__name__)
            return None

    def update_account_custom_field(self, account_id, field_id, field_value):
        """
        Updates a custom field for a given account.

        Args:
            account_id (str): The ID of the account to update.
            field_id (str): The ID of the custom field to update.
            field_value (str): The new value for the custom field.
        """
        url = f"{self.base_url}/accounts/{account_id}"
        update_payload = {
            "individualAccount": {
                "accountCustomFields": [{"id": field_id, "value": field_value}]
            }
        }
        try:
            response = requests.patch(url, headers=self.headers, json=update_payload)
            response.raise_for_status()
            logger.info(f"Successfully updated custom field for account ID: {account_id}")
        except requests.exceptions.RequestException as e:
            body = e.response.text if e.response is not None else ""
            logger.error(f"Error updating NeonCRM account {account_id}: {e} {body}")

    def search_events(
        self,
        search_fields: list[dict[str, str]],
        output_fields: list[str],
        page_size: int = 200,
        timeout: float = 10.0,
    ) -> list[dict[str, Any]]:
        """
        Searches events (read only) and returns the results of every page.

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
            if page >= MAX_SEARCH_PAGES:
                logger.warning(
                    "Neon event search stopped at %d of %d pages", MAX_SEARCH_PAGES, total_pages
                )
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
