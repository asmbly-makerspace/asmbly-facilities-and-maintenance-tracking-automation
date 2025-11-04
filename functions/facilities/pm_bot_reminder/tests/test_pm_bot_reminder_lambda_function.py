import json
import importlib
import pathlib
from unittest.mock import patch

import pytest

# Now we can import the lambda function module directly
from functions.facilities.pm_bot_reminder import lambda_function

LAMBDA_FUNCTION_PATH = "functions.facilities.pm_bot_reminder.lambda_function"


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
    assert followup.channel == 'woodshop'
    assert followup.asset_name == 'Saw'
    assert followup.frequency == 'Weekly'
    assert followup.task_name == 'Task 1'
    assert followup.task_description == 'Description 1'

@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.send_slack_message')
def test_lambda_handler_no_tasks(mock_send_slack, mock_get_tasks, mock_get_secret, reload_lambda_function):
    """Test the lambda handler when no tasks are found."""
    mock_get_secret.side_effect = ['clickup-token', 'slack-token']
    mock_get_tasks.return_value = []

    result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 200
    assert "No tasks to process" in result['body']
    mock_get_tasks.assert_called()
    mock_send_slack.assert_not_called()


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.send_slack_message')
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


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
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


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch('functions.facilities.pm_bot_reminder.lambda_function.requests.post')
def test_lambda_handler_dry_run_mode(mock_requests_post, mock_get_tasks, mock_get_secret, monkeypatch, reload_lambda_function, capsys):
    """Test that DRY_RUN=true prevents actual Slack API calls and prints to stdout."""
    # --- Mocks & Fixture Setup ---
    # Instead of reloading the module, directly patch the DRY_RUN flag within it.
    monkeypatch.setattr(lambda_function, 'DRY_RUN', True)
 
    overdue_tasks = [{
        'id': 't1', 'name': 'Overdue Task', 'text_content': 'Overdue Description', 'time_status': 'Overdue',
        'custom_fields': [
            {'id': 'ws-field-id', 'type': 'drop_down', 'value': 0, 'type_config': {'options': [{'name': 'Woodshop', 'orderindex': 0}]}},
            {'id': 'asset-field-id', 'value': 'Table Saw'},
            {'id': 'freq-field-id', 'value': 'Weekly'}
        ]
    }]
 
    # Configure mocks (now passed in as arguments)
    mock_get_secret.side_effect = ['clickup-token', 'slack-token']
    # The handler calls get_tasks twice (overdue, upcoming).
    # Provide the data for the first call and an empty list for the second.
    mock_get_tasks.side_effect = [overdue_tasks, []]

    # --- Execute ---
    result = lambda_function.lambda_handler({}, None)

    # --- Assertions ---
    assert result['statusCode'] == 200
    assert "Successfully processed 1 tasks" in result['body']

    # Crucially, assert that no web requests were made
    mock_requests_post.assert_not_called()

    # Check that the dry run output was printed to the console
    captured = capsys.readouterr()
    stdout = captured.out
    assert "--- DRY RUN MODE ---" in stdout
    assert "Would send to channel: woodshop" in stdout
    assert "[OVERDUE] woodshop - Table Saw" in stdout # Check main message
    assert "Overdue Description" in stdout # Check threaded reply
