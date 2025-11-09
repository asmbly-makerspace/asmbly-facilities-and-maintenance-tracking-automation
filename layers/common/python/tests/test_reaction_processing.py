import unittest
from unittest.mock import patch, Mock
from common import reaction_processing

class TestReactionProcessing(unittest.TestCase):

    def setUp(self):
        self.reaction_to_status = {"white_check_mark": "done", "eyes": "in_progress"}
        self.slack_secret_name = "slack_secret"
        self.clickup_secret_name = "clickup_secret"
        self.base_event_body = {
            "event": {
                "reaction": "white_check_mark",
                "item": {
                    "channel": "C12345",
                    "ts": "1629876543.000100"
                }
            }
        }

    @patch('common.reaction_processing.aws.get_secret')
    @patch('common.reaction_processing.WebClient')
    def test_process_base_reaction_success(self, mock_web_client, mock_get_secret):
        """Test successful processing of a relevant reaction."""
        # Mock AWS secrets
        mock_get_secret.side_effect = lambda name, key: {
            (self.slack_secret_name, "SLACK_MAINTENANCE_BOT_TOKEN"): "fake_slack_token",
            (self.clickup_secret_name, "CLICKUP_API_TOKEN"): "fake_clickup_token"
        }[name, key]

        # Mock Slack client and its history call
        mock_slack_instance = Mock()
        mock_slack_instance.conversations_history.return_value = {
            "ok": True,
            "messages": [{
                "text": "Task created: https://app.clickup.com/t/abc1234"
            }]
        }
        mock_web_client.return_value = mock_slack_instance

        result = reaction_processing.process_base_reaction(
            self.base_event_body, self.reaction_to_status, self.slack_secret_name, self.clickup_secret_name
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "abc1234")
        self.assertEqual(result["reaction"], "white_check_mark")
        self.assertIn("https://app.clickup.com/t/abc1234", result["message_text"])

        mock_get_secret.assert_any_call(self.slack_secret_name, "SLACK_MAINTENANCE_BOT_TOKEN")
        mock_get_secret.assert_any_call(self.clickup_secret_name, "CLICKUP_API_TOKEN")
        mock_web_client.assert_called_once_with(token="fake_slack_token")
        mock_slack_instance.conversations_history.assert_called_once_with(
            channel="C12345",
            latest="1629876543.000100",
            inclusive=True,
            limit=1
        )

    def test_process_base_reaction_irrelevant_reaction(self):
        """Test that an irrelevant reaction is ignored."""
        event_body = self.base_event_body.copy()
        event_body["event"]["reaction"] = "thumbsup"

        result = reaction_processing.process_base_reaction(
            event_body, self.reaction_to_status, self.slack_secret_name, self.clickup_secret_name
        )

        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["reason"], "Irrelevant reaction: thumbsup")

    @patch('common.reaction_processing.aws.get_secret')
    @patch('common.reaction_processing.WebClient')
    def test_process_base_reaction_no_clickup_url(self, mock_web_client, mock_get_secret):
        """Test that a message without a ClickUp URL is ignored."""
        mock_get_secret.return_value = "fake_token"
        mock_slack_instance = Mock()
        mock_slack_instance.conversations_history.return_value = {
            "ok": True,
            "messages": [{"text": "Just a regular message"}]
        }
        mock_web_client.return_value = mock_slack_instance

        result = reaction_processing.process_base_reaction(
            self.base_event_body, self.reaction_to_status, self.slack_secret_name, self.clickup_secret_name
        )

        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["reason"], "No ClickUp task URL found in the message.")

    @patch('common.reaction_processing.aws.get_secret')
    @patch('common.reaction_processing.WebClient')
    def test_process_base_reaction_no_message_found(self, mock_web_client, mock_get_secret):
        """Test that a RuntimeError is raised if the message cannot be fetched."""
        mock_get_secret.return_value = "fake_token"
        mock_slack_instance = Mock()
        mock_slack_instance.conversations_history.return_value = {
            "ok": True,
            "messages": [] # Empty messages list
        }
        mock_web_client.return_value = mock_slack_instance

        with self.assertRaisesRegex(RuntimeError, "Could not find message from reaction event."):
            reaction_processing.process_base_reaction(
                self.base_event_body, self.reaction_to_status, self.slack_secret_name, self.clickup_secret_name
            )


if __name__ == '__main__':
    unittest.main()