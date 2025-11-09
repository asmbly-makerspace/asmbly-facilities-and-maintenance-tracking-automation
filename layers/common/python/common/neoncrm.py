import os
import requests
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
        self.headers = {
            "Content-Type": "application/json",
            "NEON-API-KEY": self.api_key,
        }

    def get_account_by_email(self, email):
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
                logger.info(f"Found NeonCRM account ID: {account_id} for email: {email}")
                return account_id
            logger.warning(f"No NeonCRM account found for email: {email}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching for NeonCRM account by email: {e}")
            return None

    def update_account_custom_field(self, account_id, field_name, field_value):
        """
        Updates a custom field for a given account.

        Args:
            account_id (str): The ID of the account to update.
            field_name (str): The name of the custom field to update.
            field_value (str): The new value for the custom field.
        """
        url = f"{self.base_url}/accounts/{account_id}"
        update_payload = {
            "individualAccount": {
                "accountCustomFields": [{"name": field_name, "value": field_value}]
            }
        }
        try:
            response = requests.patch(url, headers=self.headers, json=update_payload)
            response.raise_for_status()
            logger.info(f"Successfully updated custom field '{field_name}' for account ID: {account_id}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating NeonCRM account {account_id}: {e}")