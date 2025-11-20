import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add the parent directory to the Python path to allow importing lambda_function
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from lambda_function import lambda_handler

class TestLambdaHandler(unittest.TestCase):

    def setUp(self):
        """Set up environment variables for tests."""
        self.original_environ = dict(os.environ)
        os.environ['SECRETS_ARN'] = 'test_secrets_arn'
        os.environ['CLICKUP_PROBLEM_REPORTS_CONFIG_PARAM_NAME'] = 'test_param'

    def tearDown(self):
        """Restore environment variables."""
        os.environ.clear()
        os.environ.update(self.original_environ)

    @patch('lambda_function.aws.get_json_parameter')
    @patch('lambda_function.slack.send_slack_message')
    @patch('lambda_function.discourse.create_post')
    @patch('lambda_function.clickup.create_task')
    @patch('lambda_function.clickup.update_task')
    @patch('lambda_function.aws.get_secret')
    def test_handler_with_discourse_post(self, mock_get_secret, mock_update_task, mock_create_task, mock_create_discourse_post, mock_send_slack_message, mock_get_json_parameter):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            form_data = json.load(f)
        # Ensure this test case correctly simulates opting IN to a Discourse post
        form_data['data']['Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.'] = ['Yes']
        event = {'body': json.dumps(form_data)}

        mock_get_secret.return_value = {
            "CLICKUP_API_KEY": "test_clickup_key",
            "DISCOURSE_API_KEY": "test_discourse_key",
            "DISCOURSE_API_USERNAME": "test_discourse_user",
            "DISCOURSE_URL": "https://test.discourse.url",
            "SLACK_WEBHOOK_URL": "https://test.slack.url"
        }
        mock_get_json_parameter.return_value = {
            "list_id": "12345",
            "problem_type_field_id": "field1",
            "contact_details_field_id": "field2",
            "discourse_post_field_id": "field3",
            "slack_post_field_id": "field4"
        }

        mock_create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}
        mock_create_discourse_post.return_value = "https://test.discourse.url/t/test-post/123"
        mock_send_slack_message.return_value = {"url": "https://test.slack.url/archives/C12345/p12345"}

        response = lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['body'], json.dumps("Problem report processed successfully."))

        mock_create_task.assert_called_once()
        mock_create_discourse_post.assert_called_once()
        mock_send_slack_message.assert_called_once()
        mock_update_task.assert_called_once()

    @patch('lambda_function.aws.get_json_parameter')
    @patch('lambda_function.slack.send_slack_message')
    @patch('lambda_function.discourse.create_post')
    @patch('lambda_function.clickup.create_task')
    @patch('lambda_function.clickup.update_task')
    @patch('lambda_function.aws.get_secret')
    def test_handler_no_discourse_post(self, mock_get_secret, mock_update_task, mock_create_task, mock_create_discourse_post, mock_send_slack_message, mock_get_json_parameter):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            form_data = json.load(f)
        # Ensure this test case correctly simulates opting OUT of a Discourse post
        form_data['data']['Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.'] = ['No']
        event = {'body': json.dumps(form_data)}

        mock_get_secret.return_value = {
            "CLICKUP_API_KEY": "test_clickup_key",
            "DISCOURSE_API_KEY": "test_discourse_key",
            "DISCOURSE_API_USERNAME": "test_discourse_user",
            "DISCOURSE_URL": "https://test.discourse.url",
            "SLACK_WEBHOOK_URL": "https://test.slack.url"
        }
        mock_get_json_parameter.return_value = {
            "list_id": "12345",
            "problem_type_field_id": "field1",
            "contact_details_field_id": "field2",
            "discourse_post_field_id": "field3",
            "slack_post_field_id": "field4"
        }

        mock_create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}
        mock_send_slack_message.return_value = {"url": "https://test.slack.url/archives/C12345/p12345"}

        response = lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['body'], json.dumps("Problem report processed successfully."))

        mock_create_task.assert_called_once()
        mock_create_discourse_post.assert_not_called()
        mock_send_slack_message.assert_called_once()
        mock_update_task.assert_called_once()

if __name__ == '__main__':
    unittest.main()
