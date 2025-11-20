import json
import os
import unittest
from unittest.mock import patch
# Use an absolute import path from the project root
from functions.problem_report.new_problem_report_request_received.lambda_function import lambda_handler

class TestLambdaHandler(unittest.TestCase):

    def setUp(self):
        """
        Set up environment variables for tests.
        This method is called before each test function is executed.
        """
        self.original_environ = dict(os.environ)
        os.environ['CLICKUP_SECRET_NAME'] = 'clickup_secret'
        os.environ['DISCOURSE_SECRET_NAME'] = 'test/discourse_bot_secret'
        os.environ['SLACK_MAINTENANCE_BOT_SECRET_NAME'] = 'slack_secret'
        os.environ['CLICKUP_PROBLEM_REPORTS_CONFIG_PARAM_NAME'] = 'test_param'
        os.environ['SLACK_CHANNEL_ID'] = 'C12345'
        os.environ['SLACK_BOT_NAME'] = 'Test Bot'
        os.environ['SLACK_BOT_EMOJI'] = ':test:'
        os.environ['SLACK_WORKSPACE_URL'] = 'https://test.slack.com'
        os.environ['DISCOURSE_URL'] = 'https://test.discourse.url'
        os.environ['DISCOURSE_PROBLEM_REPORT_CATEGORY'] = '59'

    def tearDown(self):
        """
        Restore environment variables to their original state.
        This method is called after each test function is executed.
        """
        os.environ.clear()
        os.environ.update(self.original_environ)

    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.aws')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.slack')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.discourse')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.clickup')
    def test_handler_with_discourse_post(self, mock_clickup, mock_discourse, mock_slack, mock_aws):
        """
        Tests the full handler flow when the user opts to create a Discourse post.
        Verifies that ClickUp task is created, Discourse post is made, Slack is notified,
        and the ClickUp task is updated with the resulting URLs.
        """
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            form_data = json.load(f)
        form_data['data']['Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.'] = ['Yes']
        event = {'body': json.dumps(form_data)}

        # Mock all external dependencies
        def get_secret_side_effect(secret_name, secret_key):
            secrets = {
                'clickup_secret': {"CLICKUP_API_TOKEN": "test_clickup_key"},
                'test/discourse_bot_secret': {
                    "DISCOURSE_FACILITIES_BOT_API_KEY": "test_discourse_key",
                    "DISCOURSE_FACILITIES_BOT_API_USERNAME": "test_discourse_user",
                },
                'slack_secret': {"SLACK_MAINTENANCE_BOT_TOKEN": "test_slack_token"}
            }
            return secrets[secret_name][secret_key]
        mock_aws.get_secret.side_effect = get_secret_side_effect
        
        mock_aws.get_json_parameter.return_value = {
            "list_id": "12345",
            "problem_type_field_id": "field1",
            "contact_details_field_id": "field2",
            "discourse_post_field_id": "field3",
            "slack_post_field_id": "field4",
            "workspace_field_id": "field_workspace",
            "asset_field_id": "field_asset"
        }
        mock_clickup.get_list_custom_fields.return_value = [
            {
                "id": "field1", "name": "Problem Type", "type": "drop_down",
                "type_config": {"options": [
                    {"name": "Equipment", "orderindex": 0},
                    {"name": "Electrical", "orderindex": 1}
                ]}
            },
            {
                "id": "field_workspace", "name": "Workspace", "type": "drop_down",
                "type_config": {"options": [
                    {"name": "General Areas", "orderindex": 5},
                    {"name": "Metalshop", "orderindex": 6}
                ]}
            }
        ]
        mock_clickup.create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}
        mock_discourse.create_post.return_value = "https://test.discourse.url/t/test-post/123"
        mock_slack.send_slack_message.return_value = {"ok": True, "channel": "C12345", "ts": "12345.67890"}
        mock_slack.get_slack_post_url.return_value = "https://test.slack.com/archives/C12345/p1234567890"

        # Execute the handler
        response = lambda_handler(event, None)

        # Verify the response and that all mocks were called as expected
        self.assertEqual(response['statusCode'], 200)
        mock_clickup.get_list_custom_fields.assert_called_once_with("test_clickup_key", "12345")
        mock_clickup.create_task.assert_called_once()
        mock_discourse.create_post.assert_called_once()
        mock_slack.send_slack_message.assert_called_once()
        mock_clickup.update_task.assert_called_once()

        # Assert the payload for create_task
        create_task_call_args = mock_clickup.create_task.call_args
        task_payload = create_task_call_args[0][2] # payload is the 3rd argument

        self.assertEqual(task_payload['name'], "ErrorCheck and rethread the upper thread")
        
        # Check custom fields payload for correct dropdown mapping and other values
        custom_fields = {field['id']: field['value'] for field in task_payload['custom_fields']}
        self.assertEqual(custom_fields.get('field2'), "Bob James") # contact_details
        self.assertEqual(custom_fields.get('field_asset'), "Embroidery / Sewing Machine 2") # asset
        self.assertEqual(custom_fields.get('field1'), 0) # problem_type "Equipment" -> orderindex 0
        self.assertEqual(custom_fields.get('field_workspace'), 5) # workspace "General Areas" -> orderindex 5

        # Assert the payload for update_task
        update_task_call_args = mock_clickup.update_task.call_args
        self.assertIsNotNone(update_task_call_args, "update_task was not called")
        update_payload = update_task_call_args.kwargs.get('payload') or update_task_call_args.args[2]

        self.assertIn("Discourse Link: https://test.discourse.url/t/test-post/123", update_payload['description'])
        self.assertIn("Slack Post: https://test.slack.com/archives/C12345/p1234567890", update_payload['description'])

        update_custom_fields = {field['id']: field['value'] for field in update_payload.get('custom_fields', [])}
        self.assertEqual(update_custom_fields.get('field3'), "https://test.discourse.url/t/test-post/123") # discourse_post_field_id
        self.assertEqual(update_custom_fields.get('field4'), "https://test.slack.com/archives/C12345/p1234567890") # slack_post_field_id

    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.aws')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.slack')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.discourse')
    @patch('functions.problem_report.new_problem_report_request_received.lambda_function.clickup')
    def test_handler_no_discourse_post(self, mock_clickup, mock_discourse, mock_slack, mock_aws):
        """
        Tests the handler flow when the user opts NOT to create a Discourse post.
        Verifies that the Discourse post creation is skipped and all other actions proceed.
        """
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'example_google_forms_response.json')) as f:
            form_data = json.load(f)
        form_data['data']['Create Discourse Post? Asmbly stewards and leads will always be notified of problem reports. Creating a discourse post will make the problem report public for wider interaction and feedback on yo.asmbly.org.'] = ['No']
        event = {'body': json.dumps(form_data)}

        # Mock all external dependencies
        def get_secret_side_effect(secret_name, secret_key):
            secrets = {
                'clickup_secret': {"CLICKUP_API_TOKEN": "test_clickup_key"},
                'test/discourse_bot_secret': {
                    "DISCOURSE_FACILITIES_BOT_API_KEY": "test_discourse_key",
                    "DISCOURSE_FACILITIES_BOT_API_USERNAME": "test_discourse_user",
                },
                'slack_secret': {"SLACK_MAINTENANCE_BOT_TOKEN": "test_slack_token"}
            }
            return secrets[secret_name][secret_key]
        mock_aws.get_secret.side_effect = get_secret_side_effect

        mock_aws.get_json_parameter.return_value = {
            "list_id": "12345",
            "problem_type_field_id": "field1",
            "contact_details_field_id": "field2",
            "discourse_post_field_id": "field3",
            "slack_post_field_id": "field4",
            "workspace_field_id": "field_workspace",
            "asset_field_id": "field_asset"
        }
        mock_clickup.get_list_custom_fields.return_value = [
            {
                "id": "field1", "name": "Problem Type", "type": "drop_down",
                "type_config": {"options": [
                    {"name": "Equipment", "orderindex": 0},
                    {"name": "Electrical", "orderindex": 1}
                ]}
            },
            {
                "id": "field_workspace", "name": "Workspace", "type": "drop_down",
                "type_config": {"options": [
                    {"name": "General Areas", "orderindex": 5},
                    {"name": "Metalshop", "orderindex": 6}
                ]}
            }
        ]
        mock_clickup.create_task.return_value = {"id": "test_task_id", "url": "https://app.clickup.com/t/test_task_id"}
        mock_slack.send_slack_message.return_value = {"ok": True, "channel": "C12345", "ts": "12345.67890"}
        mock_slack.get_slack_post_url.return_value = "https://test.slack.com/archives/C12345/p1234567890"

        # Execute the handler
        response = lambda_handler(event, None)

        # Verify the response and that the Discourse mock was NOT called
        self.assertEqual(response['statusCode'], 200)
        mock_clickup.create_task.assert_called_once()
        mock_discourse.create_post.assert_not_called()
        mock_slack.send_slack_message.assert_called_once()
        mock_clickup.update_task.assert_called_once()

if __name__ == '__main__':
    unittest.main()
