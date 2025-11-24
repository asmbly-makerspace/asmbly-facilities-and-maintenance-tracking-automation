import json
import os
import unittest
from unittest.mock import patch, MagicMock
import urllib.parse
import boto3
from moto import mock_aws

# Set environment variables before importing the lambda function
TABLE_NAME = "TestStateTable"
os.environ["STATE_TABLE_NAME"] = TABLE_NAME
os.environ["CLICKUP_SECRET_NAME"] = "fake_clickup_secret"
os.environ["SLACK_MAINTENANCE_BOT_SECRET_NAME"] = "fake_slack_secret"
os.environ["CLICKUP_MASTER_ITEMS_LIST_CONFIG_PARAM_NAME"] = "/test/param/master_items_list"
os.environ["CLICKUP_PURCHASE_REQUESTS_CONFIG_PARAM_NAME"] = "/test/param/purchase_requests"
os.environ["CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME"] = "/test/param/workspace_field_id"

# Now we can import the lambda function module directly
from functions.purchase_request.slack_slash_reorder import lambda_function

LAMBDA_FUNCTION_PATH = "functions.purchase_request.slack_slash_reorder.lambda_function"

@mock_aws
class TestFacilitiesSlackReorderLambdaFunctionWithDynamoDB(unittest.TestCase):

    def setUp(self):
        """Set up a mock DynamoDB table and other test data."""
        self.test_dir = os.path.dirname(__file__)
        os.environ['AWS_REGION'] = 'us-east-1'
        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'

        # Set up mock DynamoDB table
        self.dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        self.dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "view_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "view_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        lambda_function.state_table = boto3.resource('dynamodb').Table(TABLE_NAME)


        with open(os.path.join(self.test_dir, 'fixtures', 'clickup_master_items_response.json')) as f:
            self.clickup_master_items = json.load(f)
        
        self.purchase_requests_config = {
            "list_id": "fake_purchase_list_id",
            "supplier_link_field_id": "supplier_link_field_id",
            "requestor_name_field_id": "requestor_name_field_id",
            "item_type_field_id": "item_type_field_id"
        }
        
        self.mock_context = MagicMock()
        self.mock_context.function_name = "test_function"

    def tearDown(self):
        """Clean up mock DynamoDB table."""
        self.dynamodb.delete_table(TableName=TABLE_NAME)

    @patch(f"{LAMBDA_FUNCTION_PATH}.get_json_parameter")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_secret")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks")
    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    def test_handle_load_data_writes_to_dynamodb(self, mock_session, mock_get_all_clickup_tasks, mock_get_secret, mock_get_json_param):
        # --- GIVEN ---
        view_id = "V12345"
        mock_get_secret.return_value = "fake_token"
        mock_get_json_param.return_value = "fake_config_value"
        mock_get_all_clickup_tasks.return_value = [
            {"id": "task1", "name": "Test Item 1", "description": "Desc 1", "custom_fields": []}
        ]
        
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session
        mock_http_session.post.return_value.ok = True
        mock_http_session.post.return_value.json.return_value = {"ok": True}
        mock_http_session.post.return_value.raise_for_status.return_value = None

        # --- WHEN ---
        lambda_function.handle_load_data_and_update_view(view_id)

        # --- THEN ---
        table = boto3.resource('dynamodb').Table(TABLE_NAME)
        response = table.get_item(Key={'view_id': view_id})
        
        self.assertIn('Item', response)
        item = response['Item']
        self.assertEqual(item['view_id'], view_id)
        self.assertIn('ttl', item)
        
        tasks_data = json.loads(item['tasks_data'])
        self.assertEqual(len(tasks_data), 1)
        self.assertEqual(tasks_data[0]['id'], "task1")
        self.assertEqual(tasks_data[0]['description'], "Desc 1")

        mock_http_session.post.assert_called_once()

    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    def test_handle_block_actions_reads_from_dynamodb(self, mock_session):
        # --- GIVEN ---
        view_id = "V67890"
        task_id_selected = "task2"
        
        table = boto3.resource('dynamodb').Table(TABLE_NAME)
        tasks_state = [
            {"id": "task1", "name": "Test Item 1", "description": "Desc 1", "workspace_name": "Workspace A"},
            {"id": task_id_selected, "name": "Test Item 2", "description": "Eager-loaded description for task 2", "workspace_name": "Workspace B"},
        ]
        table.put_item(Item={'view_id': view_id, 'tasks_data': json.dumps(tasks_state)})

        payload = {
            "view": {"id": view_id, "state": {"values": {}}},
            "actions": [{"action_id": "selected_item", "selected_option": {"value": task_id_selected}}]
        }
        
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session

        # --- WHEN ---
        lambda_function.handle_block_actions(payload, mock_http_session, {})

        # --- THEN ---
        mock_http_session.post.assert_called_once()
        call_args = mock_http_session.post.call_args.kwargs
        self.assertEqual(call_args['json']['view_id'], view_id)
        
        updated_view_str = json.dumps(call_args['json']['view'])
        self.assertIn("Eager-loaded description for task 2", updated_view_str)
        self.assertIn("Test Item 1", updated_view_str)

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.requests.Session")
    @patch(f"{LAMBDA_FUNCTION_PATH}.get_secret")
    def test_initial_open_invokes_async_lambda(self, mock_get_secret, mock_session, mock_boto_client):
        # --- GIVEN ---
        mock_get_secret.return_value = "fake_slack_token"
        
        mock_http_session = MagicMock()
        mock_session.return_value = mock_http_session
        mock_http_session.post.return_value.json.return_value = {"ok": True, "view": {"id": "V_INITIAL"}}
        
        mock_lambda_client = MagicMock()
        mock_boto_client.return_value = mock_lambda_client

        event = {'body': 'trigger_id=fake_trigger_id'}

        # --- WHEN ---
        response = lambda_function.lambda_handler(event, self.mock_context)

        # --- THEN ---
        self.assertEqual(response['statusCode'], 200)
        
        # Assert loading modal was opened
        mock_http_session.post.assert_called_once_with(
            "https://slack.com/api/views.open",
            headers={'Authorization': 'Bearer fake_slack_token', 'Content-Type': 'application/json; charset=utf-8'},
            json={'trigger_id': 'fake_trigger_id', 'view': unittest.mock.ANY}
        )
        
        # Assert async invocation
        mock_lambda_client.invoke.assert_called_once()
        invoke_args = mock_lambda_client.invoke.call_args.kwargs
        self.assertEqual(invoke_args['FunctionName'], "test_function")
        self.assertEqual(invoke_args['InvocationType'], 'Event')
        self.assertEqual(json.loads(invoke_args['Payload']), {"action": "load_data_and_update_view", "view_id": "V_INITIAL"})

if __name__ == '__main__':
    unittest.main()
