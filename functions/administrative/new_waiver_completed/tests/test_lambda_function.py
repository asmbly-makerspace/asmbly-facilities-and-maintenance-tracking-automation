import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from functions.administrative.new_waiver_completed import lambda_function

LAMBDA_FUNCTION_PATH = "functions.administrative.new_waiver_completed.lambda_function"


class TestNewWaiverCompleted(TestCase):

    def setUp(self):
        """Set up common test data."""
        self.valid_payload = {
            "email": "test@example.com",
            "signed_date": "2023-10-27T10:00:00.000Z"
        }
        self.env_vars = {
            "NEON_SECRET_NAME": "prod/neon_token"
        }

    # --- Test `parse_smartwaiver_payload` ---

    def test_parse_smartwaiver_payload_success(self):
        """Tests successful parsing of a valid Smartwaiver payload."""
        email, waiver_date = lambda_function.parse_smartwaiver_payload(self.valid_payload)
        self.assertEqual(email, "test@example.com")
        self.assertEqual(waiver_date, "10/26/2023") # 10:00 UTC is 05:00 CDT on the previous day

    def test_parse_smartwaiver_payload_timezone_conversion(self):
        """Tests that a UTC timestamp is correctly converted to Central Time."""
        # This timestamp is 00:52 UTC on Nov 9, which is 19:52 CT on Nov 8 (during CDT)
        payload = {"email": "test@example.com", "signed_date": "2025-11-09T00:52:12.007Z"}
        email, waiver_date = lambda_function.parse_smartwaiver_payload(payload)
        self.assertEqual(email, "test@example.com")
        self.assertEqual(waiver_date, "11/08/2025")

    def test_parse_smartwaiver_payload_missing_email(self):
        """Tests payload parsing when 'email' is missing."""
        payload = {"signed_date": "2023-10-27T10:00:00.000Z"}
        email, waiver_date = lambda_function.parse_smartwaiver_payload(payload)
        self.assertIsNone(email)
        self.assertIsNone(waiver_date)

    def test_parse_smartwaiver_payload_invalid_date(self):
        """Tests payload parsing with an invalid date format."""
        payload = {"email": "test@example.com", "signed_date": "not-a-date"}
        email, waiver_date = lambda_function.parse_smartwaiver_payload(payload)
        self.assertIsNone(email)
        self.assertIsNone(waiver_date)

    # --- Test `update_neon_with_waiver_info` ---

    @patch(f"{LAMBDA_FUNCTION_PATH}.NeonCRM")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_update_neon_success(self, mock_aws, mock_neoncrm_class):
        """Tests the happy path for updating a NeonCRM account."""
        # Mocks
        mock_aws.get_secret.side_effect = ["test_org_id", "test_api_key"]
        mock_neon_client = MagicMock()
        mock_neon_client.get_account_by_email.return_value = "12345"
        mock_neoncrm_class.return_value = mock_neon_client

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.update_neon_with_waiver_info("test@example.com", "10/26/2023")

        # Assertions
        self.assertEqual(response["statusCode"], 200)
        mock_neoncrm_class.assert_called_once_with(org_id="test_org_id", api_key="test_api_key")
        mock_neon_client.get_account_by_email.assert_called_once_with("test@example.com")
        mock_neon_client.update_account_custom_field.assert_called_once_with(
            account_id="12345",
            field_name="WaverDate",
            field_value="10/26/2023"
        )

    @patch(f"{LAMBDA_FUNCTION_PATH}.NeonCRM")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_update_neon_account_not_found(self, mock_aws, mock_neoncrm_class):
        """Tests the case where the NeonCRM account does not exist."""
        # Mocks
        mock_aws.get_secret.side_effect = ["test_org_id", "test_api_key"]
        mock_neon_client = MagicMock()
        mock_neon_client.get_account_by_email.return_value = None  # Simulate account not found
        mock_neoncrm_class.return_value = mock_neon_client

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.update_neon_with_waiver_info("notfound@example.com", "10/26/2023")

        # Assertions
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("Account not found", response["body"])
        mock_neon_client.get_account_by_email.assert_called_once_with("notfound@example.com")
        mock_neon_client.update_account_custom_field.assert_not_called()

    # --- Test `lambda_handler` ---

    @patch(f"{LAMBDA_FUNCTION_PATH}.update_neon_with_waiver_info")
    @patch(f"{LAMBDA_FUNCTION_PATH}.parse_smartwaiver_payload")
    def test_lambda_handler_success(self, mock_parse, mock_update):
        """Tests the main handler's success path."""
        # Mocks
        mock_parse.return_value = ("test@example.com", "10/26/2023")
        mock_update.return_value = {"statusCode": 200, "body": "Success"}

        event = {"body": json.dumps(self.valid_payload)}
        response = lambda_function.lambda_handler(event, None)

        # Assertions
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "Success")
        mock_parse.assert_called_once_with(self.valid_payload)
        mock_update.assert_called_once_with("test@example.com", "10/26/2023")

    @patch(f"{LAMBDA_FUNCTION_PATH}.update_neon_with_waiver_info")
    @patch(f"{LAMBDA_FUNCTION_PATH}.parse_smartwaiver_payload")
    def test_lambda_handler_parsing_fails(self, mock_parse, mock_update):
        """Tests the main handler when payload parsing fails."""
        # Mocks
        mock_parse.return_value = (None, None)  # Simulate parsing failure

        event = {"body": json.dumps({"invalid": "payload"})}
        response = lambda_function.lambda_handler(event, None)

        # Assertions
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Could not parse required fields", response["body"])
        mock_update.assert_not_called()

    def test_lambda_handler_invalid_json_body(self):
        """Tests the main handler with a malformed JSON body."""
        event = {"body": "this is not json"}
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Internal Server Error", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.parse_smartwaiver_payload")
    def test_lambda_handler_general_exception(self, mock_parse):
        """Tests the main handler's general exception catch-all."""
        # Mocks
        mock_parse.side_effect = Exception("A wild error appeared!")

        event = {"body": json.dumps(self.valid_payload)}
        response = lambda_function.lambda_handler(event, None)

        # Assertions
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Internal Server Error", response["body"])