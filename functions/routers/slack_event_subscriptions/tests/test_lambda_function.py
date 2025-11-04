import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from functions.routers.slack_event_subscriptions import lambda_function

LAMBDA_FUNCTION_PATH = "functions.routers.slack_event_subscriptions.lambda_function"


class TestSlackEventRouter(TestCase):

    def setUp(self):
        """Set up common mock data and environment variables."""
        self.fake_router_config = {
            "purchase_request_channel_id": "C_PURCHASE",
            "problem_report_channel_id": "C_PROBLEM"
        }
        self.env_vars = {
            "ROUTER_CONFIG_PARAMETER_NAME": "/fake/router/config",
            "PURCHASE_REQUEST_LAMBDA_ARN": "arn:aws:lambda:us-east-1:123:function:purchase-request-fn",
            "PROBLEM_REPORT_LAMBDA_ARN": "arn:aws:lambda:us-east-1:123:function:problem-report-fn"
        }

    def _create_slack_event(self, channel_id, event_type="reaction_added"):
        """Helper to create a mock Slack event."""
        return {
            "body": json.dumps({
                "event": {
                    "type": event_type,
                    "item": {"channel": channel_id}
                }
            })
        }

    def test_lambda_handler_challenge(self):
        """Tests that the handler correctly responds to a Slack URL verification challenge."""
        event = {"body": json.dumps({"challenge": "test_challenge_code"})}
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge_code", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_routes_to_purchase_request_lambda(self, mock_boto3_client):
        """Tests routing to the purchase request handler."""
        # Mocks
        mock_ssm = MagicMock()
        mock_lambda = MagicMock()
        # Configure the mock to return the correct client mock based on the service name
        def client_side_effect(service_name):
            if service_name == 'ssm':
                return mock_ssm
            return mock_lambda
        mock_boto3_client.side_effect = client_side_effect
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_router_config)}
        }

        event = self._create_slack_event("C_PURCHASE")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        # Verify that boto3.client was called for both ssm and lambda
        mock_boto3_client.assert_any_call('ssm')
        mock_boto3_client.assert_any_call('lambda')

        mock_ssm.get_parameter.assert_called_once_with(Name="/fake/router/config")
        mock_lambda.invoke.assert_called_once_with(
            FunctionName=self.env_vars["PURCHASE_REQUEST_LAMBDA_ARN"],
            InvocationType='Event',
            Payload=event["body"]
        )

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_routes_to_problem_report_lambda(self, mock_boto3_client):
        """Tests routing to the problem report handler."""
        # Mocks
        mock_ssm = MagicMock()
        mock_lambda = MagicMock()
        def client_side_effect(service_name):
            if service_name == 'ssm':
                return mock_ssm
            return mock_lambda
        mock_boto3_client.side_effect = client_side_effect
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_router_config)}
        }

        event = self._create_slack_event("C_PROBLEM")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        mock_boto3_client.assert_any_call('ssm')
        mock_boto3_client.assert_any_call('lambda')

        mock_ssm.get_parameter.assert_called_once_with(Name="/fake/router/config")
        mock_lambda.invoke.assert_called_once_with(
            FunctionName=self.env_vars["PROBLEM_REPORT_LAMBDA_ARN"],
            InvocationType='Event',
            Payload=event["body"]
        )

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_ignores_unconfigured_channel(self, mock_boto3_client):
        """Tests that reactions in other channels are ignored."""
        # Mocks
        mock_ssm = MagicMock()
        mock_lambda = MagicMock()
        def client_side_effect(service_name):
            if service_name == 'ssm':
                return mock_ssm
            return mock_lambda
        mock_boto3_client.side_effect = client_side_effect
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_router_config)}
        }

        event = self._create_slack_event("C_RANDOM_CHANNEL")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("No action taken", response["body"])
        mock_lambda.invoke.assert_not_called()

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_ignores_non_reaction_event(self, mock_boto3_client):
        """Tests that events other than 'reaction_added' are ignored."""
        event = self._create_slack_event("C_PURCHASE", event_type="message")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Event ignored", response["body"])
        # boto3.client should not be called at all for non-reaction events
        mock_boto3_client.assert_not_called()

    def test_missing_router_config_env_var(self):
        """Tests graceful failure when ROUTER_CONFIG_PARAMETER_NAME is not set."""
        event = self._create_slack_event("C_PURCHASE")

        # Use a copy of env_vars and remove the key to test this specific case
        test_env = self.env_vars.copy()
        del test_env["ROUTER_CONFIG_PARAMETER_NAME"]
        with patch.dict(os.environ, test_env, clear=True):
            response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Internal server error occurred.", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_missing_target_lambda_arn(self, mock_boto3_client):
        """Tests that nothing is invoked if the target ARN env var is missing."""
        # Mocks
        mock_ssm = MagicMock()
        mock_lambda = MagicMock()
        def client_side_effect(service_name):
            if service_name == 'ssm':
                return mock_ssm
            return mock_lambda
        mock_boto3_client.side_effect = client_side_effect
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_router_config)}
        }

        event = self._create_slack_event("C_PURCHASE")

        # Remove the purchase request ARN from env
        test_env = self.env_vars.copy()
        del test_env["PURCHASE_REQUEST_LAMBDA_ARN"]
        with patch.dict(os.environ, test_env, clear=True):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("No action taken", response["body"])
        mock_lambda.invoke.assert_not_called()

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_general_exception_handling(self, mock_boto3_client):
        """Tests that a 200 is returned to Slack even if an unexpected error occurs."""
        # Mocks
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        # Simulate an error during SSM call
        mock_ssm.get_parameter.side_effect = Exception("AWS is having a bad day")

        event = self._create_slack_event("C_PURCHASE")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        # The router should always return 200 to Slack to prevent retries
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Internal server error", response["body"])