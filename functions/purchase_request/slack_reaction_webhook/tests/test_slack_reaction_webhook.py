import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

# The lambda_function import remains the same
from functions.purchase_request.slack_reaction_webhook import lambda_function

LAMBDA_FUNCTION_PATH = "functions.purchase_request.slack_reaction_webhook.lambda_function"


class TestSlackReactionWebhook(TestCase):

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    # CORRECTED: Patch the client where it is used in the lambda_function module
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_success(self, mock_boto3_client, mock_reaction_processing):
        # 1. Mock the SSM Parameter Store call
        mock_ssm_instance = MagicMock()
        mock_boto3_client.return_value = mock_ssm_instance

        fake_reaction_map = { "truck": "purchased" }
        mock_ssm_instance.get_parameter.return_value = {
            'Parameter': {
                'Value': json.dumps(fake_reaction_map)
            }
        }

        # 2. Mock the result of the shared helper function
        mock_reaction_processing.process_base_reaction.return_value = {"status": "success"}

        # 3. Define the test event
        event = {
            "body": json.dumps({
                "event": {
                    "type": "reaction_added", "reaction": "truck",
                    "item": {"channel": "C123", "ts": "12345.678"}
                }
            })
        }

        # 4. Execute the handler
        response = lambda_function.lambda_handler(event, None)

        # 5. Assert the results
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], json.dumps("Request processed successfully."))

        # Assert that SSM was called correctly
        mock_boto3_client.assert_called_once_with('ssm')
        mock_ssm_instance.get_parameter.assert_called_once_with(Name="/fake/ssm/param-name")

        # Assert that our shared helper was called with the correct arguments
        mock_reaction_processing.process_base_reaction.assert_called_once_with(
            json.loads(event["body"]),
            fake_reaction_map,
            'slack-maintenance-bot-token',
            'clickup/api/token'
        )

    def test_lambda_handler_challenge(self):
        event = {"body": json.dumps({"challenge": "test_challenge"})}
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge", response["body"])

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    # CORRECTED: Also update the patch target here
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_general_exception(self, mock_boto3_client, mock_reaction_processing):
        # Mocks
        mock_ssm_instance = MagicMock()
        mock_boto3_client.return_value = mock_ssm_instance
        mock_ssm_instance.get_parameter.return_value = {
            'Parameter': {'Value': '{"truck": "purchased"}'}
        }

        # Make the shared helper raise an error
        mock_reaction_processing.process_base_reaction.side_effect = Exception("Something went wrong")

        # Event
        event = {
            "body": json.dumps({
                "event": {
                    "type": "reaction_added", "reaction": "truck",
                    "item": {"channel": "C123", "ts": "12345.678"}
                }
            })
        }

        # Execute
        response = lambda_function.lambda_handler(event, None)

        # Assert that the handler caught the exception and returned a 500 error
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Internal server error", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_missing_env_var(self, mock_boto3_client):
        """
        Tests that the handler fails gracefully if REACTION_MAP_PARAMETER_NAME is missing.
        """
        # Event
        event = {
            "body": json.dumps({
                "event": {
                    "type": "reaction_added", "reaction": "truck",
                    "item": {"channel": "C123", "ts": "12345.678"}
                }
            })
        }

        # Use an empty patch.dict to ensure the env var is not set
        with patch.dict(os.environ, {}, clear=True):
            response = lambda_function.lambda_handler(event, None)

        # Assert
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("REACTION_MAP_PARAMETER_NAME environment variable not set", response["body"])