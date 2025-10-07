import json
import os
import importlib
import sys
import pathlib
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

# Add the parent directory to the path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import lambda_function
from lambda_function import ( # Keep this for other tests
    get_secret,
    get_custom_field_value,
    fetch_clickup_tasks_page,
    get_all_clickup_tasks,
    process_tasks_for_slack,
    send_slack_message,
    lambda_handler
)


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for the Lambda function."""
    monkeypatch.setenv('CLICKUP_SECRET_NAME', 'test/clickup/token')
    monkeypatch.setenv('SLACK_MAINTENANCE_BOT_SECRET_NAME', 'test/slack/token')
    monkeypatch.setenv('CLICKUP_LIST_ID', '12345')
    monkeypatch.setenv('CLICKUP_WORKSPACE_FIELD_ID', 'ws-field-id')
    monkeypatch.setenv('CLICKUP_ASSET_FIELD_ID', 'asset-field-id')
    monkeypatch.setenv('CLICKUP_FREQUENCY_FIELD_ID', 'freq-field-id')
    monkeypatch.setenv('BOT_NAME', 'Test Bot')
    monkeypatch.setenv('BOT_ICON_EMOJI', ':test_tube:')
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setenv('TEST_CHANNEL_OVERRIDE', '')

@pytest.fixture
def reload_lambda_function(mock_env_vars):
    """
    Fixture to reload the lambda_function module after env vars are mocked.
    This is crucial because the module loads env vars at the global scope on initial import.
    """
    importlib.reload(lambda_function)
    yield

@pytest.fixture
def mock_clickup_fields_from_file():
    """Loads mock ClickUp field definition data from a JSON file."""
    # Construct a path to the fixture file relative to this test file
    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "clickup_tasks_response.json"
    with open(fixture_path, 'r') as f:
        tasks = json.load(f)
    # The JSON file contains a list of fields under the "fields" key.
    return tasks['fields']

def test_get_secret_success(mocker):
    """Test successful retrieval of a secret from AWS Secrets Manager."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'MY_KEY': 'supersecret'})
    }
    mocker.patch('boto3.session.Session.client', return_value=mock_secrets_client)

    secret = lambda_function.get_secret('some-secret', 'MY_KEY')
    assert secret == 'supersecret'
    mock_secrets_client.get_secret_value.assert_called_once_with(SecretId='some-secret')


def test_get_secret_key_not_found(mocker):
    """Test that a KeyError is raised if the key is not in the secret."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'OTHER_KEY': 'supersecret'})
    }
    mocker.patch('boto3.session.Session.client', return_value=mock_secrets_client)

    with pytest.raises(KeyError, match="Key 'MISSING_KEY' not found in secret 'some-secret'"):
        lambda_function.get_secret('some-secret', 'MISSING_KEY')


@pytest.mark.parametrize("task, field_id, expected_value", [
    # Test case 1: Simple string value
    ({'custom_fields': [{'id': 'field1', 'value': '  Value  '}]}, 'field1', 'Value'),
    # Test case 2: Dropdown value by orderindex
    ({'custom_fields': [{'id': 'field2', 'type': 'drop_down', 'value': 0, 'type_config': {'options': [{'name': 'Option A', 'orderindex': 0}]}}]}, 'field2', 'Option A'),
    # Test case 3: Field not found
    ({'custom_fields': [{'id': 'field1', 'value': 'Value'}]}, 'field_nonexistent', None),
    # Test case 4: No custom fields
    ({}, 'field1', None),
    # Test case 5: Value is None
    ({'custom_fields': [{'id': 'field1', 'value': None}]}, 'field1', None),
    # Test case 6: Integer value
    ({'custom_fields': [{'id': 'field3', 'value': 123}]}, 'field3', '123'),
])
def test_get_custom_field_value(task, field_id, expected_value):
    """Test extraction of custom field values from a task."""
    assert lambda_function.get_custom_field_value(task, field_id) == expected_value


def test_fetch_clickup_tasks_page_success(requests_mock):
    """Test successfully fetching a page of tasks from ClickUp."""
    list_id = '123'
    api_token = 'token'
    page_num = 0
    mock_response = {'tasks': [{'id': 'task1'}], 'last_page': True}
    requests_mock.get(f"https://api.clickup.com/api/v2/list/{list_id}/task", json=mock_response)

    tasks, last_page = lambda_function.fetch_clickup_tasks_page(list_id, api_token, page_num)

    assert len(tasks) == 1
    assert tasks[0]['id'] == 'task1'
    assert last_page is True


def test_fetch_clickup_tasks_page_http_error(requests_mock):
    """Test that an HTTP error from ClickUp API is handled."""
    list_id = '123'
    api_token = 'token'
    page_num = 0
    requests_mock.get(f"https://api.clickup.com/api/v2/list/{list_id}/task", status_code=401, reason="Unauthorized", json={'err': 'Invalid token'})

    with pytest.raises(ValueError, match="ClickUp API HTTP Error: 401 Unauthorized"):
        lambda_function.fetch_clickup_tasks_page(list_id, api_token, page_num)


@patch('lambda_function.fetch_clickup_tasks_page')
def test_get_all_clickup_tasks_pagination(mock_fetch_page):
    """Test that get_all_clickup_tasks paginates correctly."""
    mock_fetch_page.side_effect = [
        ([{'id': 'task1'}], False),  # Page 0
        ([{'id': 'task2'}], True),   # Page 1 (last page)
    ]

    tasks = lambda_function.get_all_clickup_tasks('list-id', 'api-token')

    assert len(tasks) == 2
    assert tasks[0]['id'] == 'task1'
    assert tasks[1]['id'] == 'task2'
    assert mock_fetch_page.call_count == 2


@patch('lambda_function.fetch_clickup_tasks_page')
def test_get_all_clickup_tasks_max_pages(mock_fetch_page):
    """Test that pagination stops at the max_pages limit."""
    mock_fetch_page.return_value = ([{'id': 'task_on_page'}], False)

    tasks = lambda_function.get_all_clickup_tasks('list-id', 'api-token', max_pages=3)

    assert len(tasks) == 3
    assert mock_fetch_page.call_count == 3


def test_process_tasks_for_slack():
    """Test the processing and transformation of tasks for Slack messaging."""
    tasks = [
        {
            'id': 't1', 'name': 'Task 1', 'url': 'http://task1.com', 'time_status': 'Overdue',
            'text_content': 'Description 1',
            'custom_fields': [
                {'id': 'ws-field-id', 'type': 'drop_down', 'value': 0, 'type_config': {'options': [{'name': 'Woodshop', 'orderindex': 0}]}},
                {'id': 'asset-field-id', 'value': 'Saw'},
                {'id': 'freq-field-id', 'value': 'Weekly'}
            ]
        },
        { # Task with no workspace, should be skipped
            'id': 't2', 'name': 'Task 2',
            'custom_fields': [
                {'id': 'asset-field-id', 'value': 'Laser'}
            ]
        }
    ]

    unique_channels, task_followups = lambda_function.process_tasks_for_slack(tasks, 'ws-field-id', 'asset-field-id', 'freq-field-id')

    assert unique_channels == ['woodshop']
    assert len(task_followups) == 1
    followup = task_followups[0]
    assert followup['channel'] == 'woodshop'
    assert followup['asset_name'] == 'Saw'
    assert followup['frequency'] == 'Weekly'
    assert followup['task_name'] == 'Task 1'
    assert followup['task_description'] == 'Description 1'


def test_send_slack_message_success(requests_mock):
    """Test successfully sending a message to Slack."""
    requests_mock.post("https://slack.com/api/chat.postMessage", json={"ok": True, "ts": "123.456"})

    response = lambda_function.send_slack_message('slack-token', '#general', 'Hello', 'Bot', ':emoji:')

    assert response['ok'] is True
    assert response['ts'] == "123.456"
    sent_payload = requests_mock.last_request.json()
    assert sent_payload['channel'] == 'general'
    assert sent_payload['text'] == 'Hello'


def test_send_slack_message_dry_run(capsys):
    """Test that DRY_RUN mode prints to console instead of sending."""
    with patch('lambda_function.DRY_RUN', True):
        response = lambda_function.send_slack_message('slack-token', '#general', 'Dry run message', 'Bot', ':emoji:')

    assert response['ok'] is True
    assert response['ts'] == "DRY_RUN_TIMESTAMP"
    captured = capsys.readouterr()
    assert "--- DRY RUN MODE ---" in captured.out
    assert "Would send to channel: #general" in captured.out
    assert "Message: Dry run message" in captured.out


@patch('lambda_function.get_secret')
@patch('lambda_function.get_all_clickup_tasks')
@patch('lambda_function.send_slack_message')
def test_lambda_handler_no_tasks(mock_send_slack, mock_get_tasks, mock_get_secret, reload_lambda_function):
    """Test the lambda handler when no tasks are found."""
    mock_get_secret.side_effect = ['clickup-token', 'slack-token']
    mock_get_tasks.return_value = []

    result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 200
    assert "No tasks to process" in result['body']
    mock_get_tasks.assert_called()
    mock_send_slack.assert_not_called()


@patch('lambda_function.get_secret')
@patch('lambda_function.get_all_clickup_tasks')
@patch('lambda_function.send_slack_message')
def test_lambda_handler_with_tasks(mock_send_slack, mock_get_tasks, mock_get_secret, reload_lambda_function):
    """Test the full lambda handler flow with tasks and threaded replies."""
    # --- Mocks Setup ---
    mock_get_secret.side_effect = ['clickup-token', 'slack-token']

    # This test requires mock *tasks*, not field definitions.
    overdue_tasks = [{
        'id': 't1', 'name': 'Overdue Task', 'date_created': '1672531200000',
        'text_content': 'Overdue Description',
        'custom_fields': [
            {'id': 'ws-field-id', 'type': 'drop_down', 'value': 0, 'type_config': {'options': [{'name': 'Woodshop', 'orderindex': 0}]}},
            {'id': 'asset-field-id', 'value': 'Table Saw'},
            {'id': 'freq-field-id', 'value': 'Monthly'}
        ]
    }]
    upcoming_tasks = [{
        'id': 't2', 'name': 'Upcoming Task', 'date_created': '1672531200001',
        'text_content': '',  # No description
        'custom_fields': [
            {'id': 'ws-field-id', 'type': 'drop_down', 'value': 1, 'type_config': {'options': [{'name': 'Lasers', 'orderindex': 1}]}},
            {'id': 'asset-field-id', 'value': 'Glowforge'},
            {'id': 'freq-field-id', 'value': 'Weekly'}
        ]
    }]
    mock_get_tasks.side_effect = [overdue_tasks, upcoming_tasks]

    # Mock Slack responses
    mock_send_slack.side_effect = [
        # Response for main message of task 2 (Glowforge, sorts first)
        {'ok': True, 'ts': '333.333', 'channel': 'lasers'},
        # Response for main message of task 1 (Table Saw)
        {'ok': True, 'ts': '111.111', 'channel': 'woodshop'},
        # Response for threaded reply of task 1
        {'ok': True, 'ts': '111.222', 'channel': 'woodshop'},
    ]

    # --- Execute ---
    result = lambda_function.lambda_handler({}, None)

    # --- Assertions ---
    assert result['statusCode'] == 200
    assert "Successfully processed 2 tasks" in result['body']

    # Check secrets were fetched
    assert mock_get_secret.call_count == 2

    # Check ClickUp tasks were fetched for overdue and upcoming
    assert mock_get_tasks.call_count == 2

    # Check Slack messages
    assert mock_send_slack.call_count == 3

    # Call 1: Main message for upcoming task (Glowforge)
    call1_args = mock_send_slack.call_args_list[0].kwargs
    assert call1_args['channel_to_attempt'] == 'lasers'
    assert '[UPCOMING]' in call1_args['text']
    assert 'Glowforge' in call1_args['text']
    assert call1_args.get('thread_ts') is None

    # Call 2: Main message for overdue task (Table Saw)
    call2_args = mock_send_slack.call_args_list[1].kwargs
    assert call2_args['channel_to_attempt'] == 'woodshop'
    assert '[OVERDUE]' in call2_args['text']
    assert 'Table Saw' in call2_args['text']
    assert call2_args.get('thread_ts') is None

    # Call 3: Threaded reply for overdue task
    call3_args = mock_send_slack.call_args_list[2].kwargs
    assert call3_args['channel_to_attempt'] == 'woodshop'
    assert call3_args['text'] == 'Overdue Description'
    assert call3_args['thread_ts'] == '111.111'


@patch('lambda_function.get_secret')
def test_lambda_handler_fatal_error(mock_get_secret, reload_lambda_function, capsys):
    """Test the main exception handler for unexpected errors."""
    # --- Mocks Setup ---
    # Force the first call to get_secret to raise a generic exception
    mock_get_secret.side_effect = Exception("Something went terribly wrong")

    # --- Execute ---
    result = lambda_function.lambda_handler({}, None)

    # --- Assertions ---
    assert result['statusCode'] == 500
    assert "Something went terribly wrong" in result['body']
    captured = capsys.readouterr()
    assert "--- FATAL ERROR in handler:" in captured.out
    assert "Traceback (most recent call last):" in captured.err