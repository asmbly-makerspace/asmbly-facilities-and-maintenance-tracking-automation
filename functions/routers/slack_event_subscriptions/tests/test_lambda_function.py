import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from functions.routers.slack_event_subscriptions import lambda_function

LAMBDA_FUNCTION_PATH = "functions.routers.slack_event_subscriptions.lambda_function"

# This decorator will mock boto3.client for all tests in the class
@patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
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
        # Set up the mock clients that will be used across tests
        self.mock_ssm = MagicMock()
        self.mock_lambda = MagicMock()
        self.mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_router_config)}
        }
        # The handler caches its boto3 clients per container; start each test without them.
        lambda_function._ssm_client = None
        lambda_function._lambda_client = None

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

    def test_lambda_handler_challenge(self, mock_boto3_client):
        """Tests that the handler correctly responds to a Slack URL verification challenge."""
        event = {"body": json.dumps({"challenge": "test_challenge_code"})}
        with self.assertLogs(lambda_function.logger, level="INFO") as logs:
            response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge_code", response["body"])
        mock_boto3_client.assert_not_called() # No AWS clients should be called for a challenge
        # No headers at all: the retry number is logged as None.
        self.assertIn("retry_num=None", "\n".join(logs.output))

    def test_logs_ids_but_not_request_body_or_headers(self, mock_boto3_client):
        """Tests that only the event type, channel and retry number reach the log."""
        clients = {'ssm': self.mock_ssm, 'lambda': self.mock_lambda}
        mock_boto3_client.side_effect = lambda service, *args, **kwargs: clients[service]
        event = {
            # Lower-case, as some proxies send it: the lookup ignores case.
            "headers": {
                "x-slack-retry-num": "2",
                "X-Slack-Signature": "v0=SIGNATURE_SECRET",
                "X-Slack-Request-Timestamp": "1700000000",
            },
            "body": json.dumps({
                "token": "VERIFICATION_TOKEN_SECRET",
                "type": "event_callback",
                "event": {
                    "type": "reaction_added",
                    "user": "U_REACTOR",
                    "reaction": "white_check_mark",
                    "item": {"type": "message", "channel": "C_PURCHASE", "ts": "1.2"},
                },
            }),
        }

        with (
            patch.dict(os.environ, self.env_vars),
            self.assertLogs(lambda_function.logger, level="INFO") as logs,
        ):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["body"], json.dumps("Request forwarded successfully."))
        output = "\n".join(logs.output)
        self.assertIn("type=reaction_added channel=C_PURCHASE retry_num=2", output)
        for leaked in ("VERIFICATION_TOKEN_SECRET", "SIGNATURE_SECRET", "1700000000",
                       "U_REACTOR", "white_check_mark", event["body"]):
            self.assertNotIn(leaked, output)

    def test_routes_to_purchase_request_lambda(self, mock_boto3_client):
        """Tests routing to the purchase request handler."""
        mock_boto3_client.side_effect = [self.mock_ssm, self.mock_lambda]
        event = self._create_slack_event("C_PURCHASE")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        mock_boto3_client.assert_any_call('ssm')
        mock_boto3_client.assert_any_call('lambda')
        self.mock_ssm.get_parameter.assert_called_once_with(Name="/fake/router/config")
        self.mock_lambda.invoke.assert_called_once_with(
            FunctionName=self.env_vars["PURCHASE_REQUEST_LAMBDA_ARN"],
            InvocationType='Event',
            Payload=event["body"]
        )

    def test_routes_to_problem_report_lambda(self, mock_boto3_client):
        """Tests routing to the problem report handler."""
        mock_boto3_client.side_effect = [self.mock_ssm, self.mock_lambda]
        event = self._create_slack_event("C_PROBLEM")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        mock_boto3_client.assert_any_call('ssm')
        mock_boto3_client.assert_any_call('lambda')
        self.mock_ssm.get_parameter.assert_called_once_with(Name="/fake/router/config")
        self.mock_lambda.invoke.assert_called_once_with(
            FunctionName=self.env_vars["PROBLEM_REPORT_LAMBDA_ARN"],
            InvocationType='Event',
            Payload=event["body"]
        )

    def test_ignores_unconfigured_channel(self, mock_boto3_client):
        """Tests that reactions in other channels are ignored."""
        mock_boto3_client.return_value = self.mock_ssm
        event = self._create_slack_event("C_RANDOM_CHANNEL")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("No action taken", response["body"])
        self.mock_lambda.invoke.assert_not_called()

    def test_ignores_non_reaction_event(self, mock_boto3_client):
        """Tests that events other than 'reaction_added' are ignored."""
        event = self._create_slack_event("C_PURCHASE", event_type="message")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Event ignored", response["body"])
        mock_boto3_client.assert_not_called()

    def test_missing_router_config_env_var(self, mock_boto3_client):
        """Tests graceful failure when ROUTER_CONFIG_PARAMETER_NAME is not set."""
        event = self._create_slack_event("C_PURCHASE")
        test_env = self.env_vars.copy()
        del test_env["ROUTER_CONFIG_PARAMETER_NAME"]
        
        with patch.dict(os.environ, test_env, clear=True):
            response = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Internal configuration error", response["body"])

    def test_missing_target_lambda_arn(self, mock_boto3_client):
        """Tests that nothing is invoked if the target ARN env var is missing."""
        mock_boto3_client.return_value = self.mock_ssm
        event = self._create_slack_event("C_PURCHASE")
        test_env = self.env_vars.copy()
        del test_env["PURCHASE_REQUEST_LAMBDA_ARN"]
        
        with patch.dict(os.environ, test_env, clear=True):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("No action taken", response["body"])
        self.mock_lambda.invoke.assert_not_called()

    def test_general_exception_handling(self, mock_boto3_client):
        """Tests that a 200 is returned to Slack even if an unexpected error occurs."""
        mock_boto3_client.return_value = self.mock_ssm
        self.mock_ssm.get_parameter.side_effect = Exception("AWS is having a bad day")
        event = self._create_slack_event("C_PURCHASE")

        with patch.dict(os.environ, self.env_vars):
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Internal server error", response["body"])

    def test_reuses_boto3_clients_across_invocations(self, mock_boto3_client):
        """Tests that a warm container builds its SSM and Lambda clients only once."""
        clients = {'ssm': self.mock_ssm, 'lambda': self.mock_lambda}
        mock_boto3_client.side_effect = lambda service, *args, **kwargs: clients[service]
        event = self._create_slack_event("C_PURCHASE")

        with patch.dict(os.environ, self.env_vars):
            first = lambda_function.lambda_handler(event, None)
            second = lambda_function.lambda_handler(event, None)

        self.assertEqual(first["body"], json.dumps("Request forwarded successfully."))
        self.assertEqual(second["body"], json.dumps("Request forwarded successfully."))
        services = [call.args[0] for call in mock_boto3_client.call_args_list]
        self.assertEqual(services.count('ssm'), 1)
        self.assertEqual(services.count('lambda'), 1)
        self.assertEqual(self.mock_lambda.invoke.call_count, 2)
        # The routing config is read on every invocation, not cached.
        self.assertEqual(self.mock_ssm.get_parameter.call_count, 2)
