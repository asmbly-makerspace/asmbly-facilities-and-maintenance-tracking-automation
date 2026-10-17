import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

# The lambda_function import remains the same
from functions.purchase_request.slack_reaction_webhook import lambda_function

LAMBDA_FUNCTION_PATH = "functions.purchase_request.slack_reaction_webhook.lambda_function"


class TestSlackReactionWebhook(TestCase):

    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    # CORRECTED: Patch the client where it is used in the lambda_function module
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_success(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup):
        # 1. Mock the SSM Parameter Store call
        mock_ssm_instance = MagicMock()
        mock_boto3_client.return_value = mock_ssm_instance

        fake_reaction_map = { "truck": "purchased" }
        mock_ssm_instance.get_parameter.return_value = {
            'Parameter': {
                'Value': json.dumps(fake_reaction_map)
            }
        }

        # Mock secret fetching
        mock_aws.get_secret.return_value = 'fake-clickup-token'

        # 2. Mock the result of the shared helper function
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "truck"
        }

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
        event_body = json.loads(event['body'])
        response = lambda_function.lambda_handler(event_body, None)

        # 5. Assert the results
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], json.dumps("Request processed successfully."))

        # Assert that SSM was called correctly
        mock_boto3_client.assert_called_once_with('ssm')
        mock_ssm_instance.get_parameter.assert_called_once_with(Name="/fake/ssm/param-name")

        # Assert that our shared helper was called with the correct arguments
        mock_reaction_processing.process_base_reaction.assert_called_once_with(
            event_body,
            fake_reaction_map, # reaction_to_status
            'slack-maintenancebot-token', # slack_secret_name
            'clickup/api/token'
        )

        # Assert that the ClickUp task was updated
        mock_aws.get_secret.assert_called_once_with('clickup/api/token', 'CLICKUP_API_TOKEN')
        mock_clickup.update_task.assert_called_once_with(
            'fake-clickup-token', 'abcde123', {"status": "purchased"}
        )

    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_result_log_omits_message_text(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup):
        """The result log line carries the task ID, not the requester's name from the message."""
        mock_ssm_instance = MagicMock()
        mock_boto3_client.return_value = mock_ssm_instance
        mock_ssm_instance.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps({"truck": "purchased"})}
        }
        mock_aws.get_secret.return_value = 'fake-clickup-token'
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "truck",
            "message_text": "Requested By: Jane Doe\nhttps://app.clickup.com/t/abcde123",
        }
        event_body = {"event": {"type": "reaction_added", "reaction": "truck",
                                "item": {"channel": "C123", "ts": "12345.678"}}}

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertNotIn("Jane Doe", "\n".join(logs.output))
        results = [r.getMessage() for r in logs.records if "Processing result" in r.getMessage()]
        self.assertEqual(len(results), 1, results)
        self.assertIn("abcde123", results[0])
        self.assertIn("truck", results[0])

    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_ignored_result_log_has_status_and_reason(self, mock_boto3_client, mock_reaction_processing):
        """An ignored reaction logs its status and reason."""
        mock_ssm_instance = MagicMock()
        mock_boto3_client.return_value = mock_ssm_instance
        mock_ssm_instance.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps({"truck": "purchased"})}
        }
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "ignored", "reason": "No ClickUp task URL found in the message."
        }
        event_body = {"event": {"type": "reaction_added", "reaction": "truck",
                                "item": {"channel": "C123", "ts": "12345.678"}}}

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        self.assertEqual(response["statusCode"], 200)
        results = [r.getMessage() for r in logs.records if "Processing result" in r.getMessage()]
        self.assertEqual(len(results), 1, results)
        self.assertIn("ignored", results[0])
        self.assertIn("No ClickUp task URL found in the message.", results[0])

    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_received_event_log_omits_token_and_body(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup):
        """The 'Received event' line carries the event's IDs, never Slack's token or the whole event."""
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {'Parameter': {'Value': json.dumps({"truck": "purchased"})}}
        mock_aws.get_secret.return_value = 'fake-clickup-token'
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "ignored", "reason": "No ClickUp task URL found in the message.",
        }
        event_body = {
            "token": "pk_VERIFY_MARKER",
            "team_id": "T999",
            "event_id": "Ev123ABC",
            "type": "event_callback",
            "event": {
                "type": "reaction_added", "reaction": "truck", "user": "U555",
                "item": {"type": "message", "channel": "C123", "ts": "123.456"},
            },
        }

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        self.assertEqual(response["statusCode"], 200)
        output = "\n".join(logs.output)
        self.assertNotIn("pk_VERIFY_MARKER", output)
        self.assertNotIn("T999", output)
        received = [r.getMessage() for r in logs.records if r.getMessage().startswith("Received event")]
        self.assertEqual(received, [
            "Received event: type=reaction_added reaction=truck channel=C123 ts=123.456 event_id=Ev123ABC"
        ])

    def test_received_event_log_handles_non_dict_shapes(self):
        """The log line never raises before the handler's try, whatever shape the event has."""
        with self.assertLogs(level="INFO") as logs:
            lambda_function._log_received_event("pk_STRING_MARKER")
            lambda_function._log_received_event({"event": "not-a-dict", "token": "pk_VERIFY_MARKER"})
            lambda_function._log_received_event({"event": {"type": "reaction_added", "item": ["x"]}})

        self.assertEqual([r.getMessage() for r in logs.records], [
            "Received event: not a dict",
            "Received event: type=None reaction=None channel=None ts=None event_id=None",
            "Received event: type=reaction_added reaction=None channel=None ts=None event_id=None",
        ])
        self.assertNotIn("pk_", "\n".join(logs.output))

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_challenge(self, mock_boto3_client):
        # The router passes the body directly
        event_body = {"challenge": "test_challenge"}
        response = lambda_function.lambda_handler(event_body, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge", response["body"])

    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
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
        event_body = json.loads(event['body'])
        event_body["event_id"] = "Ev500ERR"
        with self.assertLogs(level="ERROR") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        # Assert that the handler caught the exception and returned a plain 500 error
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"], json.dumps("Internal server error."))
        self.assertNotIn("Something went wrong", response["body"])
        errors = [r for r in logs.records if r.levelname == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIsNotNone(errors[0].exc_info)
        self.assertIn("Ev500ERR", errors[0].getMessage())

    # Test cases for missing environment variables
    @patch.dict(os.environ, {
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
    }, clear=True) # Clear ensures only these are set
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_missing_reaction_map_env_var(self, mock_boto3_client):
        """
        Tests that the handler fails gracefully if REACTION_MAP_PARAMETER_NAME is missing.
        """
        event_body = {"event": {"type": "reaction_added", "reaction": "truck", "item": {"channel": "C123", "ts": "12345.678"}}}
        with self.assertLogs(level="ERROR") as logs:
            response = lambda_function.lambda_handler(event_body, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"], json.dumps("Internal server error."))
        self.assertIn("REACTION_MAP_PARAMETER_NAME environment variable not set", "\n".join(logs.output))

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
        "CLICKUP_SECRET_NAME": "clickup/api/token",
    }, clear=True)
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_missing_slack_secret_env_var(self, mock_boto3_client):
        """
        Tests that the handler fails gracefully if SLACK_MAINTENANCE_BOT_SECRET_NAME is missing.
        """
        event_body = {"event": {"type": "reaction_added", "reaction": "truck", "item": {"channel": "C123", "ts": "12345.678"}}}
        with self.assertLogs(level="ERROR") as logs:
            response = lambda_function.lambda_handler(event_body, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"], json.dumps("Internal server error."))
        self.assertIn("SLACK_MAINTENANCE_BOT_SECRET_NAME environment variable not set", "\n".join(logs.output))

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param-name",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "slack-maintenancebot-token",
    }, clear=True)
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_lambda_handler_missing_clickup_secret_env_var(self, mock_boto3_client):
        """
        Tests that the handler fails gracefully if CLICKUP_SECRET_NAME is missing.
        """
        event_body = {"event": {"type": "reaction_added", "reaction": "truck", "item": {"channel": "C123", "ts": "12345.678"}}}
        with self.assertLogs(level="ERROR") as logs:
            response = lambda_function.lambda_handler(event_body, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"], json.dumps("Internal server error."))
        self.assertIn("CLICKUP_SECRET_NAME environment variable not set", "\n".join(logs.output))