import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from functions.purchase_request.slack_reaction_webhook import lambda_function


class TestSlackReactionWebhook(TestCase):

    @patch.dict(os.environ, {
        "CLICKUP_SECRET_NAME": "fake_clickup_secret",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake_slack_secret",
    })
    @patch("common.aws.get_secret")
    @patch("slack_sdk.WebClient")
    @patch("common.clickup.update_task")
    def test_lambda_handler_success(self, mock_update_task, mock_web_client, mock_get_secret):
        # Mock secrets
        mock_get_secret.side_effect = [
            "fake_slack_token",
            "fake_clickup_token"
        ]

        # Mock Slack client
        mock_slack_instance = MagicMock()
        mock_web_client.return_value = mock_slack_instance
        mock_slack_instance.conversations_history.return_value = {
            "messages": [
                {"text": "some text https://app.clickup.com/t/12345 some other text"}
            ]
        }

        # Test event
        event = {
            "body": json.dumps({
                "event": {
                    "type": "reaction_added",
                    "reaction": "truck",
                    "item": {"channel": "C123", "ts": "12345.678"}
                }
            })
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], json.dumps("Task status updated successfully."))

        # Assert that secrets were fetched correctly
        self.assertEqual(mock_get_secret.call_count, 2)
        mock_get_secret.assert_any_call("fake_slack_secret", "SLACK_BOT_TOKEN")
        mock_get_secret.assert_any_call("fake_clickup_secret", "CLICKUP_API_TOKEN")

        # Assert that the ClickUp task was updated with the correct status
        mock_update_task.assert_called_once_with(
            "fake_clickup_token",
            "12345",
            {"status": "sc901310302436_2E6Zn1Xp"} # ID for 'purchased'
        )

    def test_lambda_handler_challenge(self):
        event = {
            "body": json.dumps({"challenge": "test_challenge"})
        }
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge", response["body"])
