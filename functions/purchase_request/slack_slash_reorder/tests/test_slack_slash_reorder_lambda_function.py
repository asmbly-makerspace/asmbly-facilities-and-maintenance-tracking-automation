import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import urllib.parse

# Add the parent 'functions' directory to the path to allow direct import of the lambda_function
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
# Add the common layer's python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'layers', 'common', 'python')))

# Now we can import the lambda function module directly
from slack_slash_reorder import lambda_function

@patch.dict(os.environ, {
    "CLICKUP_SECRET_NAME": "fake_clickup_secret",
    "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake_slack_secret",
    "LIST_ID": "fake_list_id",
    "PURCHASE_REQUEST_LIST_ID": "fake_purchase_list_id",
    "WORKSPACE_FIELD_ID": "workspace_field_id",
    "SUPPLIER_LINK_FIELD_ID": "supplier_link_field_id",
    "REQUESTOR_NAME_FIELD_ID": "requestor_name_field_id",
    "ITEM_TYPE_FIELD_ID": "item_type_field_id"
})
class TestFacilitiesSlackReorderLambdaFunction(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.dirname(__file__)
        os.environ['AWS_REGION'] = 'us-east-1'

        with open(os.path.join(self.test_dir, 'fixtures', 'clickup_master_items_response.json')) as f:
            self.clickup_master_items = json.load(f)

    @patch('slack_slash_reorder.lambda_function.get_secret')
    @patch('slack_slash_reorder.lambda_function.get_all_clickup_tasks')
    @patch('requests.Session')
    def test_lambda_handler_initial_open(self, mock_session, mock_get_all_clickup_tasks, mock_get_secret):
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_get_all_clickup_tasks.return_value = self.clickup_master_items['tasks']

        event = {
            'body': 'trigger_id=fake_trigger_id'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        call_args, call_kwargs = mock_http_session.post.call_args
        self.assertEqual(call_args[0], 'https://slack.com/api/views.open')
        sent_json = call_kwargs['json']
        self.assertEqual(sent_json['trigger_id'], 'fake_trigger_id')
        self.assertEqual(sent_json['view']['title']['text'], 'Reorder Item')

    @patch('slack_slash_reorder.lambda_function.get_secret')
    @patch('slack_slash_reorder.lambda_function.get_all_clickup_tasks')
    @patch('requests.Session')
    def test_no_items_found(self, mock_session, mock_get_all_clickup_tasks, mock_get_secret):
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_get_all_clickup_tasks.return_value = []

        event = {
            'body': 'trigger_id=fake_trigger_id'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        call_args, call_kwargs = mock_http_session.post.call_args
        self.assertEqual(call_args[0], 'https://slack.com/api/views.open')
        sent_json = call_kwargs['json']
        self.assertEqual(sent_json['view']['title']['text'], 'No Items Found')

    @patch('slack_slash_reorder.lambda_function.get_secret')
    @patch('requests.Session')
    def test_workspace_filter(self, mock_session, mock_get_secret):
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session

        all_tasks_prepared = lambda_function.prepare_tasks_for_metadata(self.clickup_master_items.get('tasks', []), "workspace_field_id")
        private_metadata_str = json.dumps(all_tasks_prepared)

        payload = {
            "type": "block_actions",
            "actions": [{"action_id": "selected_workspace", "selected_option": {"value": "Clean Room"}}],
            "view": {
                "id": "fake_view_id",
                "private_metadata": private_metadata_str,
                "state": {"values": {}}
            }
        }
        event = {
            'body': f'payload={urllib.parse.quote_plus(json.dumps(payload))}'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        call_args, call_kwargs = mock_http_session.post.call_args
        self.assertEqual(call_args[0], 'https://slack.com/api/views.update')
        sent_json = call_kwargs['json']
        self.assertEqual(sent_json['view_id'], 'fake_view_id')
        item_options = sent_json['view']['blocks'][2]['element']['options']
        self.assertEqual(len(item_options), 0)

    @patch('slack_slash_reorder.lambda_function.get_secret')
    @patch('requests.Session')
    def test_item_selection_updates_description(self, mock_session, mock_get_secret):
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session

        all_tasks_prepared = lambda_function.prepare_tasks_for_metadata(self.clickup_master_items.get('tasks', []), "workspace_field_id")
        private_metadata_str = json.dumps(all_tasks_prepared)
        selected_task_id = self.clickup_master_items['tasks'][0]["id"]
        expected_description = self.clickup_master_items['tasks'][0]["description"]

        payload = {
            "type": "block_actions",
            "actions": [{"action_id": "selected_item", "selected_option": {"value": selected_task_id}}],
            "view": {
                "id": "fake_view_id",
                "private_metadata": private_metadata_str,
                "state": {"values": {}}
            }
        }
        event = {
            'body': f'payload={urllib.parse.quote_plus(json.dumps(payload))}'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        call_args, call_kwargs = mock_http_session.post.call_args
        self.assertEqual(call_args[0], 'https://slack.com/api/views.update')
        sent_json = call_kwargs['json']
        self.assertEqual(sent_json['view_id'], 'fake_view_id')

        description_block = next((b for b in sent_json['view']['blocks'] if b['block_id'].startswith('description_block')), None)
        self.assertIsNotNone(description_block)
        self.assertEqual(description_block['element']['initial_value'], expected_description)

    @patch('slack_slash_reorder.lambda_function.get_secret')
    @patch('slack_slash_reorder.lambda_function.get_slack_user_info')
    @patch('slack_slash_reorder.lambda_function.get_task')
    @patch('slack_slash_reorder.lambda_function.create_task')
    def test_successful_submission(self, mock_create_task, mock_get_task, mock_get_slack_user_info, mock_get_secret):
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_get_slack_user_info.return_value = {"user": {"real_name": "Test User"}}
        mock_get_task.return_value = self.clickup_master_items['tasks'][0]
        mock_create_task.return_value = {"id": "new_task_id"}

        selected_item_id = self.clickup_master_items['tasks'][0]["id"]
        payload = {
            "type": "view_submission",
            "user": {"id": "fake_user_id"},
            "view": {
                "state": {
                    "values": {
                        "item_selection": {"selected_item": {"selected_option": {"value": selected_item_id}}},
                        "delivery_date_block": {"delivery_date_action": {"selected_date": "2024-01-01"}},
                        "description_block_123": {"description_action": {"value": "Custom description"}}
                    }
                }
            }
        }
        event = {
            'body': f'payload={urllib.parse.quote_plus(json.dumps(payload))}'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 200)
        
        mock_create_task.assert_called_once()
        call_args, call_kwargs = mock_create_task.call_args
        self.assertEqual(call_args[1], os.environ["PURCHASE_REQUEST_LIST_ID"])
        sent_payload = call_args[2]
        self.assertEqual(sent_payload['name'], self.clickup_master_items['tasks'][0]["name"])
        self.assertEqual(sent_payload['description'], 'Custom description')
        self.assertEqual(sent_payload['due_date'], 1704067200000)

        response_body = json.loads(response['body'])
        self.assertEqual(response_body['response_action'], 'update')
        self.assertEqual(response_body['view']['title']['text'], 'Success!')

    @patch('slack_slash_reorder.lambda_function.get_secret')
    def test_error_handling(self, mock_get_secret):
        mock_get_secret.side_effect = Exception("AWS Error")

        event = {
            'body': 'trigger_id=fake_trigger_id'
        }

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response['statusCode'], 500)
        self.assertIn("error", json.loads(response['body']))

if __name__ == '__main__':
    unittest.main()
