import json
import logging
import importlib
import pathlib
from unittest.mock import patch

import pytest

# Now we can import the lambda function module directly
from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function

LAMBDA_FUNCTION_PATH = "functions.ceramics.kiln_dropoff_recent_entries_viewer.lambda_function"


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for the Lambda function."""
    monkeypatch.setenv('SECRET_NAME', 'test/clickup/token')
    monkeypatch.setenv('CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME', '/test/config/clickup/ceramics')


@pytest.fixture
def reload_lambda_function(mock_env_vars):
    """Reloads the lambda function module to apply mocked environment variables."""
    importlib.reload(lambda_function)
    yield


@pytest.fixture
def mock_tasks_from_file():
    """Loads mock ClickUp task data from the provided JSON fixture."""
    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "clickup_dropofftasks_response.json"
    # Return a function that re-opens and re-loads the file to ensure a fresh, deep copy for each test
    def _loader():
        with open(fixture_path, 'r') as f:
            return json.load(f)
    return _loader


def test_generate_html_page_with_tasks(mock_tasks_from_file):
    """Test HTML page generation with a list of tasks."""
    mock_data = mock_tasks_from_file()
    tasks = mock_data['tasks']
    
    # The fixture has 10 tasks. Let's create timestamps for them.
    # Base timestamp: 2024-01-01 00:00:00 UTC
    base_ts = 1704067200000 
    for i, task in enumerate(tasks):
        task['date_created'] = str(base_ts + i * 1000) # Increment by 1 second

    # Mimic the sorting that happens in the lambda_handler
    tasks.sort(key=lambda x: int(x.get('date_created', 0)), reverse=True)

    html = lambda_function.generate_html_page(tasks)

    assert "<h1>Recent Kiln Drop-Offs</h1>" in html
    # The last task in the fixture ('Customer J') has the latest date and should appear first.
    # The first task ('Customer A') has the earliest date and should appear last.
    # After sorting, the last task in the fixture ('Customer J') should appear first in the HTML.
    assert html.find("Customer J") < html.find("Customer A")
    assert "No submissions found" not in html


def test_generate_html_page_no_tasks():
    """Test HTML page generation with no tasks."""
    html = lambda_function.generate_html_page([])
    assert "<h1>Recent Kiln Drop-Offs</h1>" in html
    assert 'No submissions found in the last 24 hours' in html


def test_generate_error_page():
    """Test the generation of a user-friendly error page."""
    html = lambda_function.generate_error_page()
    assert "<h2>An Error Occurred</h2>" in html
    assert "Could not retrieve the list of submissions." in html
    assert "Error details" not in html


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_success(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, mock_tasks_from_file):
    """Test the full success path of the lambda_handler."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_data = mock_tasks_from_file() # Get a fresh copy of the data
    mock_get_json_param.return_value = '123456789' # Mock the list ID

    # We need to add date_created to all tasks for this to work because the fixture lacks it.
    for i, task in enumerate(mock_data['tasks']):
        task['date_created'] = str(1704067200000 + i * 1000)  # Staggered timestamps
    mock_get_all_clickup_tasks.return_value = mock_data['tasks']

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert mocks were called
    mock_get_json_param.assert_called_with('/test/config/clickup/ceramics', 'list_id')

    # Assert
    assert result['statusCode'] == 200
    assert result['headers']['Content-Type'] == 'text/html'
    assert "<h1>Recent Kiln Drop-Offs</h1>" in result['body']
    assert "KO-FAKE-001" in result['body'] # Check for task data
    assert "Customer A" in result['body']
    
    # Check that sorting happened (the fixture is not sorted by date)
    # The last task in the fixture ('Customer J') has the latest timestamp, so it should appear first in the HTML.
    assert result['body'].find('Customer J') < result['body'].find('Customer A')


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_clickup_api_error(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function):
    """Test the handler's response to a ClickUp API error."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_get_json_param.return_value = '123456789'
    mock_get_all_clickup_tasks.side_effect = ValueError("401 Client Error: Unauthorized for url")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "401 Client Error: Unauthorized for url" not in result['body']

def test_lambda_handler_missing_env_var(reload_lambda_function, monkeypatch, caplog):
    """Test the handler's response when a required environment variable is missing."""
    # Arrange
    monkeypatch.delenv('CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME')
    importlib.reload(lambda_function) # Reload to pick up the deleted env var

    # Act
    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME" not in result['body']
    assert "Server configuration error" not in result['body']
    assert "CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME" in caplog.text


def test_lambda_handler_missing_secret_name(reload_lambda_function, monkeypatch, caplog):
    """A missing SECRET_NAME gives the generic error page and names the variable only in the log."""
    monkeypatch.delenv('SECRET_NAME')
    importlib.reload(lambda_function)

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 500
    assert "Could not retrieve the list of submissions." in result['body']
    assert "SECRET_NAME" not in result['body']
    assert "Server configuration error" not in result['body']
    assert "SECRET_NAME" in caplog.text


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_secret_manager_error(mock_get_json_param, mock_get_secret, reload_lambda_function):
    """Test the handler's response to a Secrets Manager error."""
    # Arrange
    # We need to mock the SSM call so the function can proceed to the secrets call
    mock_get_json_param.return_value = '123456789'
    mock_get_secret.side_effect = Exception("Could not connect to Secrets Manager")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not retrieve the list of submissions." in result['body']
    assert "Could not connect to Secrets Manager" not in result['body']


def test_generate_html_page_escapes_task_name_and_id():
    """Form text and IDs are escaped before they go into the page (#74)."""
    tasks = [{
        'id': 'abc123',
        'custom_id': 'KO-<b>1</b>',
        'name': '<script>alert(1)</script>',
        'date_created': '1704067200000',
    }]

    page = lambda_function.generate_html_page(tasks)

    assert '<script>alert(1)</script>' not in page
    assert 'KO-<b>1</b>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert 'KO-&lt;b&gt;1&lt;/b&gt;' in page


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_error_page_hides_exception_text(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, caplog):
    """The error page never shows the exception's text; it goes to the log instead (#74)."""
    marker = "ClickUp API HTTP Error: 401 Unauthorized - Details: {\"err\": \"Token invalid\", \"url\": \"list/123456789/task\"}"
    mock_get_secret.return_value = 'fake-token'
    mock_get_json_param.return_value = '123456789'
    mock_get_all_clickup_tasks.side_effect = ValueError(marker)

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    assert result['statusCode'] == 500
    body = result['body']
    assert "Could not retrieve the list of submissions." in body
    assert marker not in body
    assert "Token invalid" not in body
    assert "401" not in body
    assert "123456789" not in body
    assert "Error details" not in body
    assert any(r.exc_info and marker in str(r.exc_info[1]) for r in caplog.records)


@patch(f'{LAMBDA_FUNCTION_PATH}.get_secret')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_all_clickup_tasks')
@patch(f'{LAMBDA_FUNCTION_PATH}.get_json_parameter')
def test_lambda_handler_empty_token_returns_generic_500(mock_get_json_param, mock_get_all_clickup_tasks, mock_get_secret, reload_lambda_function, caplog):
    """An empty API token stops before ClickUp is called and shows the generic error page."""
    mock_get_json_param.return_value = '123456789'
    mock_get_secret.return_value = ""

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler({}, None)

    mock_get_all_clickup_tasks.assert_not_called()
    assert result['statusCode'] == 500
    assert "Could not retrieve the list of submissions." in result['body']
    assert "ClickUp API token missing from secret" in caplog.text


def test_generate_html_page_null_custom_id_shows_task_id():
    """ClickUp sends "custom_id": null on lists without custom IDs; the task ID is shown instead."""
    tasks = [{'id': 'abc123', 'custom_id': None, 'name': 'Customer Z', 'date_created': '1704067200000'}]

    page = lambda_function.generate_html_page(tasks)

    assert '<td class="task-id">abc123</td>' in page
    assert 'None' not in page


def test_generate_html_page_escapes_quotes_and_ampersands():
    """Ampersands and quotes in a name are escaped."""
    tasks = [{'id': 'abc123', 'custom_id': 'KO-1', 'name': 'O\'Brien & "Sons"', 'date_created': '1704067200000'}]

    page = lambda_function.generate_html_page(tasks)

    assert 'O&#x27;Brien &amp; &quot;Sons&quot;' in page
    assert 'O\'Brien & "Sons"' not in page
