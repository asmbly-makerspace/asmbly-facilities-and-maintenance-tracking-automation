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
    @patch("functions.purchase_request.slack_reaction_webhook.lambda_function.get_secret")
    @patch("functions.purchase_request.slack_reaction_webhook.lambda_function.WebClient")
    @patch("requests.put")
    def test_lambda_handler_success(self, mock_requests_put, mock_web_client, mock_get_secret):
        # Mock secrets
        mock_get_secret.side_effect = [
            {"SLACK_BOT_TOKEN": "fake_slack_token"},
            {"CLICKUP_API_TOKEN": "fake_clickup_token"}
        ]

        # Mock Slack client
        mock_slack_instance = MagicMock()
        mock_web_client.return_value = mock_slack_instance
        mock_slack_instance.conversations_history.return_value = {
            "messages": [
                {"text": "some text https://app.clickup.com/t/12345 some other text"}
            ]
        }

        # Mock requests.put
        mock_requests_put.return_value.status_code = 200

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
        mock_requests_put.assert_called_once()

    def test_lambda_handler_challenge(self):
        event = {
            "body": json.dumps({"challenge": "test_challenge"})
        }
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge", response["body"])
