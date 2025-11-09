import unittest
from unittest.mock import patch, Mock
import base64
import requests
from common.neoncrm import NeonCRM

class TestNeonCRM(unittest.TestCase):

    def setUp(self):
        self.org_id = "test_org"
        self.api_key = "test_key"
        self.client = NeonCRM(self.org_id, self.api_key)

    def test_init(self):
        """Test that the NeonCRM client is initialized correctly."""
        self.assertEqual(self.client.org_id, self.org_id)
        self.assertEqual(self.client.api_key, self.api_key)
        self.assertEqual(self.client.base_url, "https://api.neoncrm.com/v2")

        auth_string = f"{self.org_id}:{self.api_key}"
        expected_auth_header = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

        self.assertIn("Authorization", self.client.headers)
        self.assertEqual(self.client.headers["Authorization"], f"Basic {expected_auth_header}")
        self.assertEqual(self.client.headers["Content-Type"], "application/json")

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_found(self, mock_post):
        """Test retrieving an account by email when the account exists."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "searchResults": [{"Account ID": "12345"}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        account_id = self.client.get_account_by_email("test@example.com")

        self.assertEqual(account_id, "12345")
        expected_url = f"{self.client.base_url}/accounts/search"
        expected_payload = {
            "searchFields": [{"field": "Email 1", "operator": "EQUAL", "value": "test@example.com"}],
            "outputFields": ["Account ID"],
            "pagination": {"currentPage": 0, "pageSize": 1},
        }
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_not_found(self, mock_post):
        """Test retrieving an account by email when the account does not exist."""
        mock_response = Mock()
        mock_response.json.return_value = {"searchResults": []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        account_id = self.client.get_account_by_email("notfound@example.com")

        self.assertIsNone(account_id)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_api_error(self, mock_post):
        """Test handling of API errors when searching for an account."""
        mock_post.side_effect = requests.exceptions.RequestException("API Error")

        account_id = self.client.get_account_by_email("test@example.com")

        self.assertIsNone(account_id)

    @patch('common.neoncrm.requests.patch')
    def test_update_account_custom_field_success(self, mock_patch):
        """Test successfully updating a custom field for an account."""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_patch.return_value = mock_response

        account_id = "12345"
        field_id = "10"
        field_value = "New Value"

        # This method doesn't return anything, so we just check for no exceptions
        self.client.update_account_custom_field(account_id, field_id, field_value)

        expected_url = f"{self.client.base_url}/accounts/{account_id}"
        expected_payload = {
            "individualAccount": {
                "accountCustomFields": [{"id": field_id, "value": field_value}]
            }
        }
        mock_patch.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch('common.neoncrm.requests.patch')
    def test_update_account_custom_field_api_error(self, mock_patch):
        """Test handling of API errors when updating a custom field."""
        mock_patch.side_effect = requests.exceptions.RequestException("API Error")

        account_id = "12345"
        field_id = "10"
        field_value = "New Value"

        # We expect this to fail silently and log an error, not raise an exception
        try:
            self.client.update_account_custom_field(account_id, field_id, field_value)
        except Exception as e:
            self.fail(f"update_account_custom_field raised an unexpected exception: {e}")