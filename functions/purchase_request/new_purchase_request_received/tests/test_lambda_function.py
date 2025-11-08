import json
import os
import unittest
from unittest.mock import patch

# Import the function to be tested
from functions.purchase_request.new_purchase_request_received.lambda_function import lambda_handler


class TestNewPurchaseRequestLambda(unittest.TestCase):

    def setUp(self):
        """Set up test environment before each test."""
        # Load the fixture data
        fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'clickup_payload.json')
        with open(fixture_path, 'r') as f:
            self.clickup_webhook_payload = json.load(f)

        # This is a mock of the response from clickup.get_task, which has a different 'custom_fields' structure
        self.mock_full_task_details = {
            "id": "86ad43ft6",
            "name": "New HVAC Parts",
            "text_content": "We need some new parts for the HVAC equipment.",
            "custom_fields": [
                {"id": "ASSET_NAME_FIELD_ID", "value": "Main AC Unit", "type": "text"},
                {"id": "REQUESTOR_NAME_FIELD_ID", "value": "Robert S", "type": "text"},
                {"id": "SUPPLIER_LINK_FIELD_ID", "value": "https://www.airstrike.com", "type": "url"},
                {
                    "id": "WORKSPACE_FIELD_ID", "value": "some-uuid", "type": "drop_down",
                    "type_config": {"options": [{"id": "some-uuid", "name": "Woodshop", "orderindex": 0}]}
                },
                {
                    "id": "ITEM_TYPE_FIELD_ID", "value": "another-uuid", "type": "drop_down",
                    "type_config": {"options": [{"id": "another-uuid", "name": "Consumable", "orderindex": 1}]}
                }
            ]
        }

        self.mock_env_vars = {
            'CLICKUP_SECRET_NAME': 'test_clickup_secret',
            'SLACK_MAINTENANCE_BOT_SECRET_NAME': 'test_slack_secret',
            'SLACK_CHANNEL_ID': 'C12345',
            'SLACK_BOT_NAME': 'Test Purchase Bot',
            'SLACK_BOT_EMOJI': ':test_tube:',
            'SLACK_WORKSPACE_URL': 'https://test-workspace.slack.com',
            'ASSET_NAME_FIELD_ID': 'ASSET_NAME_FIELD_ID',
            'REQUESTOR_NAME_FIELD_ID': 'REQUESTOR_NAME_FIELD_ID',
            'SUPPLIER_LINK_FIELD_ID': 'SUPPLIER_LINK_FIELD_ID',
            'WORKSPACE_FIELD_ID': 'WORKSPACE_FIELD_ID',
            'ITEM_TYPE_FIELD_ID': 'ITEM_TYPE_FIELD_ID',
            'SLACK_POST_FIELD_ID': 'SLACK_POST_FIELD_ID'
        }

    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.aws')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.clickup')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.slack')
    @patch.dict(os.environ, {})
    def test_lambda_handler_success(self, mock_slack, mock_clickup, mock_aws):
        """Test the successful execution path of the lambda handler."""
        os.environ.update(self.mock_env_vars)

        # --- Mock external calls ---
        mock_aws.get_secret.side_effect = [
            'fake-clickup-token',  # CLICKUP_API_TOKEN
            'fake-slack-token'     # SLACK_MAINTENANCE_BOT_TOKEN
        ]
        mock_clickup.get_task.return_value = self.mock_full_task_details

        # Configure the mock for get_custom_field_value to return specific values based on the field ID
        def get_custom_field_side_effect(task, field_id):
            if field_id == 'ASSET_NAME_FIELD_ID':
                return 'Main AC Unit'
            if field_id == 'REQUESTOR_NAME_FIELD_ID':
                return 'Robert S'
            if field_id == 'SUPPLIER_LINK_FIELD_ID':
                return 'https://www.airstrike.com'
            if field_id == 'WORKSPACE_FIELD_ID':
                return 'Woodshop'
            if field_id == 'ITEM_TYPE_FIELD_ID':
                return 'Consumable'
            return None
        mock_clickup.get_custom_field_value.side_effect = get_custom_field_side_effect

        mock_slack.send_slack_message.return_value = {
            'ok': True,
            'channel': 'C12345',
            'ts': '1234567890.123456'
        }
        mock_clickup.set_custom_field_value.return_value = {'id': '86ad43ft6'} # Mock a successful response

        # --- Create the event ---
        event = {'body': json.dumps(self.clickup_webhook_payload)}

        # --- Execute the handler ---
        result = lambda_handler(event, None)

        # --- Assertions ---
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(json.loads(result['body']), 'Successfully processed purchase request.')

        # Verify secrets were fetched
        mock_aws.get_secret.assert_any_call('test_clickup_secret', 'CLICKUP_API_TOKEN')
        mock_aws.get_secret.assert_any_call('test_slack_secret', 'SLACK_MAINTENANCE_BOT_TOKEN')

        # Verify ClickUp task was fetched
        mock_clickup.get_task.assert_called_once_with('fake-clickup-token', '86ad43ft6')

        # Verify Slack message was sent with correct details
        mock_slack.send_slack_message.assert_called_once()
        # The function is called with keyword arguments, so we inspect kwargs.
        _, kwargs = mock_slack.send_slack_message.call_args
        self.assertIn("Item Requested: New HVAC Parts", kwargs['text'])
        self.assertIn("Workspace: Woodshop", kwargs['text'])
        self.assertIn("Asset: Main AC Unit", kwargs['text'])
        self.assertIn("Item Type: Consumable", kwargs['text'])
        self.assertIn("Requested By: Robert S", kwargs['text'])

        # Verify ClickUp task was updated with the Slack permalink
        expected_slack_url = "https://test-workspace.slack.com/archives/C12345/p1234567890123456"
        mock_clickup.set_custom_field_value.assert_called_once_with('fake-clickup-token', '86ad43ft6', 'SLACK_POST_FIELD_ID', expected_slack_url)

    @patch.dict(os.environ, {})
    def test_lambda_handler_clickup_test_webhook(self):
        """Test that the handler correctly processes ClickUp's test webhook payload."""
        os.environ.update(self.mock_env_vars)

        # ClickUp's test payload is a simple JSON object without a 'trigger_id'
        test_payload = {"body": "Test message from ClickUp Webhooks Service"}
        event = {'body': json.dumps(test_payload)}

        result = lambda_handler(event, None)

        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(json.loads(result['body']), 'Webhook test successful or unhandled event type.')

    @patch.dict(os.environ, {})
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.aws')
    def test_lambda_handler_invalid_payload(self, mock_aws):
        """Test handler response when a real event payload is missing required keys."""
        os.environ.update(self.mock_env_vars)

        # A real event will have a trigger_id but might be missing the task payload
        event_no_payload = {'body': json.dumps({"trigger_id": "some-trigger-id"})}
        result_no_payload = lambda_handler(event_no_payload, None)
        self.assertEqual(result_no_payload['statusCode'], 400)
        self.assertIn('Invalid payload: missing task payload.', result_no_payload['body'])

        # Verify no secrets were fetched
        mock_aws.get_secret.assert_not_called()

    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.aws')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.clickup')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.slack')
    @patch.dict(os.environ, {})
    def test_lambda_handler_slack_api_failure(self, mock_slack, mock_clickup, mock_aws):
        """Test handler response when the Slack API call fails."""
        os.environ.update(self.mock_env_vars)

        # --- Mock external calls ---
        mock_aws.get_secret.return_value = 'fake-token'
        mock_clickup.get_task.return_value = self.mock_full_task_details
        mock_slack.send_slack_message.return_value = {'ok': False, 'error': 'channel_not_found'}

        event = {'body': json.dumps(self.clickup_webhook_payload)}
        result = lambda_handler(event, None)

        # --- Assertions ---
        self.assertEqual(result['statusCode'], 500)
        self.assertEqual(json.loads(result['body']), 'Failed to send Slack message.')
        
        # Ensure we did not try to update the ClickUp task
        mock_clickup.set_custom_field_value.assert_not_called()

    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.aws')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.clickup')
    @patch('functions.purchase_request.new_purchase_request_received.lambda_function.slack')
    @patch.dict(os.environ, {})
    def test_lambda_handler_clickup_get_task_failure(self, mock_slack, mock_clickup, mock_aws):
        """Test handler response when fetching the ClickUp task fails."""
        os.environ.update(self.mock_env_vars)

        # --- Mock external calls ---
        mock_aws.get_secret.return_value = 'fake-token'
        mock_clickup.get_task.side_effect = Exception("ClickUp API is down")

        event = {'body': json.dumps(self.clickup_webhook_payload)}
        result = lambda_handler(event, None)

        # --- Assertions ---
        self.assertEqual(result['statusCode'], 500)
        self.assertIn('An error occurred: ClickUp API is down', result['body'])

        # Ensure Slack message was not sent
        mock_slack.send_slack_message.assert_not_called()

    @patch.dict(os.environ, {})
    def test_missing_environment_variable(self):
        """Test that the function fails fast if a required environment variable is missing."""
        # Remove the specific env var for this test
        test_vars = self.mock_env_vars.copy()
        del test_vars['SLACK_WORKSPACE_URL']
        os.environ.update(test_vars)

        event = {'body': json.dumps(self.clickup_webhook_payload)}
        result = lambda_handler(event, None)

        self.assertEqual(result['statusCode'], 500)
        self.assertIn("Missing required environment variables: SLACK_WORKSPACE_URL", result['body'])

if __name__ == '__main__':
    unittest.main()