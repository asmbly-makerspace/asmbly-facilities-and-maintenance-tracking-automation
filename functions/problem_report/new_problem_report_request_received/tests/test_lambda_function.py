import json
import os
import unittest
from unittest.mock import patch, MagicMock, call

from lambda_function import lambda_handler

class TestLambdaHandler(unittest.TestCase):

    @patch('lambda_function.get_secret')
    @patch('lambda_function.ClickUp')
    @patch('lambda_function.Discourse')
    @patch('lambda_function.send_slack_message')
    def test_handler_with_discourse_post(self, mock_send_slack_message, mock_discourse, mock_clickup, mock_get_secret):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            event = {'body': f.read()}

        mock_get_secret.return_value = {
            "CLICKUP_API_KEY": "test_clickup_key",
            "DISCOURSE_API_KEY": "test_discourse_key",
            "DISCOURSE_API_USERNAME": "test_discourse_user",
            "DISCOURSE_URL": "https://test.discourse.url",
            "SLACK_WEBHOOK_URL": "https://test.slack.url"
        }

        mock_clickup_instance = MagicMock()
        mock_clickup.return_value = mock_clickup_instance
        mock_clickup_instance.create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}

        mock_discourse_instance = MagicMock()
        mock_discourse.return_value = mock_discourse_instance
        mock_discourse_instance.create_post.return_value = "https://test.discourse.url/t/test-post/123"

        mock_send_slack_message.return_value = {"url": "https://test.slack.url/archives/C12345/p12345"}

        response = lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['body'], json.dumps("Problem report processed successfully."))

        mock_clickup_instance.create_task.assert_called_once()
        mock_discourse_instance.create_post.assert_called_once()
        mock_send_slack_message.assert_called_once()
        mock_clickup_instance.update_task_custom_fields.assert_called_once()

    @patch('lambda_function.get_secret')
    @patch('lambda_function.ClickUp')
    @patch('lambda_function.Discourse')
    @patch('lambda_function.send_slack_message')
    def test_handler_no_discourse_post(self, mock_send_slack_message, mock_discourse, mock_clickup, mock_get_secret):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            form_data = json.load(f)
        form_data['data']['Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.'] = ['No']
        event = {'body': json.dumps(form_data)}

        mock_get_secret.return_value = {
            "CLICKUP_API_KEY": "test_clickup_key",
            "DISCOURSE_API_KEY": "test_discourse_key",
            "DISCOURSE_API_USERNAME": "test_discourse_user",
            "DISCOURSE_URL": "https://test.discourse.url",
            "SLACK_WEBHOOK_URL": "https://test.slack.url"
        }

        mock_clickup_instance = MagicMock()
        mock_clickup.return_value = mock_clickup_instance
        mock_clickup_instance.create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}

        mock_discourse_instance = MagicMock()
        mock_discourse.return_value = mock_discourse_instance

        mock_send_slack_message.return_value = {"url": "https://test.slack.url/archives/C12345/p12345"}

        response = lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['body'], json.dumps("Problem report processed successfully."))

        mock_clickup_instance.create_task.assert_called_once()
        mock_discourse_instance.create_post.assert_not_called()
        mock_send_slack_message.assert_called_once()
        mock_clickup_instance.update_task_custom_fields.assert_called_once()

if __name__ == '__main__':
    unittest.main()
