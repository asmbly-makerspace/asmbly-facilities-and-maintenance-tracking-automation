import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock
from slack_sdk.errors import SlackApiError

from functions.purchase_request.slack_reaction_webhook import lambda_function

LAMBDA_FUNCTION_PATH = "functions.purchase_request.slack_reaction_webhook.lambda_function"


class TestSlackReactionWebhook(TestCase):

    @patch.dict(os.environ, {
        "CLICKUP_SECRET_NAME": "fake_clickup_secret",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake_slack_secret",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws.get_secret")
    @patch(f"{LAMBDA_FUNCTION_PATH}.WebClient")
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup.update_task")
    def test_lambda_handler_success(self, mock_update_task, mock_web_client, mock_get_secret):
        # Mocks
        mock_get_secret.side_effect = ["fake_slack_token", "fake_clickup_token"]
        mock_slack_instance = MagicMock()
        mock_web_client.return_value = mock_slack_instance
        mock_slack_instance.conversations_history.return_value = {
            "ok": True,
            "messages": [{"text": "some text https://app.clickup.com/t/12345 some other text"}]
        }

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

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], json.dumps("Task status updated successfully."))
        mock_get_secret.assert_any_call("fake_slack_secret", "SLACK_BOT_TOKEN")
        mock_get_secret.assert_any_call("fake_clickup_secret", "CLICKUP_API_TOKEN")
        mock_update_task.assert_called_once_with(
            "fake_clickup_token", "12345", {"status": "sc901310302436_2E6Zn1Xp"}
        )

    def test_lambda_handler_challenge(self):
        event = {"body": json.dumps({"challenge": "test_challenge"})}
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge", response["body"])

    @patch.dict(os.environ, {
        "CLICKUP_SECRET_NAME": "fake_clickup_secret",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake_slack_secret",
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws.get_secret")
    @patch(f"{LAMBDA_FUNCTION_PATH}.WebClient")
    def test_lambda_handler_slack_api_error(self, mock_web_client, mock_get_secret):
        # Mocks
        mock_get_secret.return_value = "fake_slack_token"
        mock_slack_instance = MagicMock()
        mock_web_client.return_value = mock_slack_instance
        mock_slack_instance.conversations_history.side_effect = SlackApiError(
            message="invalid_auth", response={"ok": False, "error": "invalid_auth"}
        )

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

        # Assert
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Server error", response["body"])

    def test_lambda_handler_missing_env_var(self):
        """
        Tests that the handler fails gracefully if environment variables are missing.
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

        # Using an empty patch.dict to ensure no env vars are set
        with patch.dict(os.environ, {}, clear=True):
            # Execute
            response = lambda_function.lambda_handler(event, None)

        # Assert
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Missing required environment variables", response["body"])