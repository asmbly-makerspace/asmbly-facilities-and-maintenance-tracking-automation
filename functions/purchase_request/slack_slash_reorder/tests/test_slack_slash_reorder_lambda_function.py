import json
import os
import unittest
from unittest.mock import patch, MagicMock
import urllib.parse
import boto3
from moto import mock_aws

# Set environment variables before importing
TABLE_NAME = "TestStateTable"
os.environ["STATE_TABLE_NAME"] = TABLE_NAME
os.environ["CLICKUP_SECRET_NAME"] = "fake_clickup_secret"
os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"] = "fake_slack_secret"
os.environ["CLICKUP_MASTER_ITEMS_LIST_CONFIG_PARAM_NAME"] = "/test/param/master_items_list"
os.environ["CLICKUP_PURCHASE_REQUESTS_CONFIG_PARAM_NAME"] = "/test/param/purchase_requests"
os.environ["CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME"] = "/test/param/workspace_field_id"
os.environ["AWS_REGION"] = "us-east-1"

# Import the module under test
from functions.purchase_request.slack_slash_reorder import lambda_function

LAMBDA_FUNCTION_PATH = "functions.purchase_request.slack_slash_reorder.lambda_function"

@mock_aws
class TestSlackReorderWithDynamoDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        Load static data from disk ONCE for the whole test class.
        This significantly speeds up execution by reducing File I/O.
        """
        test_dir = os.path.dirname(__file__)

        # Load fixtures once
        with open(os.path.join(test_dir, 'fixtures', 'clickup_master_items_response.json')) as f:
            cls.clickup_master_items = json.load(f)

        cls.purchase_requests_config = {
            "list_id": "fake_purchase_list_id",
            "supplier_link_field_id": "supplier_link_field_id",
            "requestor_name_field_id": "requestor_name_field_id",
            "item_type_field_id": "item_type_field_id"
        }

    def setUp(self):
        """Set up a mock DynamoDB table per test to ensure isolation."""
        # Start DynamoDB Mock
        self.dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self.table = self.dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "view_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "view_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )

        # Bind the module's global table variable to the mock
        lambda_function.state_table = self.table

        self.mock_context = MagicMock()
        self.mock_context.function_name = "test_function"

        # Mock Session for API calls
        self.mock_http_session = MagicMock()
        self.mock_http_session.post.return_value.ok = True
        self.mock_http_session.post.return_value.status_code = 200
        self.mock_http_session.post.return_value.json.return_value = {"ok": True}

    def tearDown(self):
        pass

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_secret")
    def test_initial_open_invokes_async_lambda(self, mock_get_secret, mock_session_cls, mock_boto_client):
        # --- GIVEN ---
        mock_get_secret.return_value = "fake_slack_token"
        mock_session_cls.return_value = self.mock_http_session
        self.mock_http_session.post.return_value.json.return_value = {"ok": True, "view": {"id": "V_INITIAL"}}

        mock_lambda_client = MagicMock()
        mock_boto_client.return_value = mock_lambda_client

        # Standard Slash Command body
        event = {'body': 'trigger_id=fake_trigger_id&user_id=U123'}

        # --- WHEN ---
        response = lambda_function.lambda_handler(event, self.mock_context)

        # --- THEN ---
        self.assertEqual(response['statusCode'], 200)

        # Verify Slack API call
        self.mock_http_session.post.assert_called_once()
        self.assertIn("views.open", self.mock_http_session.post.call_args[0][0])

        # Verify Async Invoke
        mock_lambda_client.invoke.assert_called_once()
        invoke_args = mock_lambda_client.invoke.call_args.kwargs
        self.assertEqual(json.loads(invoke_args['Payload']), {"action": "load_data_and_update_view", "view_id": "V_INITIAL"})

    @patch(f"{LAMBDA_FUNCTION_PATH}.get_json_parameter")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_secret")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks")
    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    def test_handle_load_data_writes_to_dynamodb(self, mock_session_cls, mock_get_all_clickup_tasks, mock_get_secret, mock_get_json_param):
        # --- GIVEN ---
        view_id = "V12345"
        mock_get_secret.return_value = "fake_token"
        mock_get_json_param.return_value = "fake_config_value"
        mock_get_all_clickup_tasks.return_value = self.clickup_master_items['tasks']

        mock_session_cls.return_value = self.mock_http_session

        # --- WHEN ---
        lambda_function.handle_load_data_and_update_view(view_id)

        # --- THEN ---
        response = self.table.get_item(Key={'view_id': view_id})

        self.assertIn('Item', response)
        tasks_data = json.loads(response['Item']['tasks_data'])
        self.assertEqual(len(tasks_data), len(self.clickup_master_items['tasks']))

        # Ensure Slack update was called
        self.mock_http_session.post.assert_called_once()
        self.assertIn("views.update", self.mock_http_session.post.call_args[0][0])

    def test_block_actions_updates_via_api(self):
        # --- GIVEN ---
        view_id = "V67890"
        task_id_selected = self.clickup_master_items['tasks'][0]['id']

        # Seed DynamoDB state
        tasks_state = lambda_function.prepare_tasks_for_state(self.clickup_master_items['tasks'], "clickup_workspace_field_id")
        self.table.put_item(Item={'view_id': view_id, 'tasks_data': json.dumps(tasks_state)})

        payload = {
            "type": "block_actions",
            "view": {"id": view_id, "state": {"values": {}}},
            "actions": [{"action_id": "selected_item", "selected_option": {"value": task_id_selected}}]
        }

        # --- WHEN ---
        response = lambda_function.handle_block_actions(payload, self.mock_http_session, "fake_token")

        # --- THEN ---
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['body'], "")

        # Check that the API call was made to update the view
        self.mock_http_session.post.assert_called_once()
        call_args = self.mock_http_session.post.call_args
        self.assertIn("views.update", call_args[0][0])

        sent_view = call_args[1]['json']['view']

        # Verify Dynamic Description Logic
        description_block = next(b for b in sent_view['blocks'] if b['block_id'].startswith("description_block_"))
        self.assertIn(task_id_selected, description_block['block_id'])
        self.assertEqual(description_block['element']['initial_value'], self.clickup_master_items['tasks'][0]['description'])

    @patch(f"{LAMBDA_FUNCTION_PATH}.get_json_parameter")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_secret")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_slack_user_info")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_task")
    @patch(f"{LAMBDA_FUNCTION_PATH}.create_task")
    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    def test_successful_submission(self, mock_session_cls, mock_create_task, mock_get_task, mock_get_slack_user_info, mock_get_secret, mock_get_json_param):
        # --- GIVEN ---
        mock_session_cls.return_value = self.mock_http_session

        def get_param_side_effect(param_name, expected_key=None):
            if param_name == "/test/param/workspace_field_id": return 'clickup_workspace_field_id'
            if param_name == "/test/param/master_items_list": return 'fake_list_id'
            if param_name == "/test/param/purchase_requests": return self.purchase_requests_config
            return None
        mock_get_json_param.side_effect = get_param_side_effect
        mock_get_secret.side_effect = ['fake_clickup_token', 'fake_slack_token']
        mock_get_slack_user_info.return_value = {"user": {"real_name": "Test User"}}
        mock_get_task.return_value = self.clickup_master_items['tasks'][0]
        mock_create_task.return_value = {"id": "new_task_id"}

        selected_item_id = self.clickup_master_items['tasks'][0]["id"]
        # Simulate a submission where the description block has the dynamic ID
        payload = {
            "type": "view_submission",
            "user": {"id": "fake_user_id"},
            "view": {
                "state": {
                    "values": {
                        "item_selection": {"selected_item": {"selected_option": {"value": selected_item_id}}},
                        f"description_block_{selected_item_id}": {"description_action": {"value": "Custom description"}}
                    }
                }
            }
        }
        event = {'body': f'payload={urllib.parse.quote_plus(json.dumps(payload))}'}

        # --- WHEN ---
        response = lambda_function.lambda_handler(event, self.mock_context)

        # --- THEN ---
        self.assertEqual(response['statusCode'], 200)
        mock_create_task.assert_called_once()
        sent_payload = mock_create_task.call_args[0][2]
        self.assertEqual(sent_payload['description'], 'Custom description')

        response_body = json.loads(response['body'])
        self.assertEqual(response_body['response_action'], 'update')
        self.assertEqual(response_body['view']['title']['text'], 'Success!')

if __name__ == '__main__':
    unittest.main()