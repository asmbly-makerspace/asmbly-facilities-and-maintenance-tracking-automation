import json
import os
import importlib
import sys
import pathlib
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest
from requests.exceptions import HTTPError

# Add the parent 'functions' directory to the path to allow direct import of the lambda_function
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Now we can import the lambda function module directly
from kiln_dropoff_recent_entries_viewer import lambda_function


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for the Lambda function."""
    monkeypatch.setenv('SECRET_NAME', 'test/clickup/token')
    monkeypatch.setenv('CLICKUP_LIST_KILNDROP_ID', '123456789')


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
    html = lambda_function.generate_error_page("Test error message")
    assert "<h2>An Error Occurred</h2>" in html
    assert "Could not retrieve the list of submissions." in html
    assert "Test error message" in html


@patch('common.aws.get_secret')
@patch('kiln_dropoff_recent_entries_viewer.lambda_function.requests.get')
def test_lambda_handler_success(mock_requests_get, mock_get_secret, reload_lambda_function, mock_tasks_from_file):
    """Test the full success path of the lambda_handler."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_data = mock_tasks_from_file() # Get a fresh copy of the data
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    # We need to add date_created to all tasks for this to work because the fixture lacks it.
    for i, task in enumerate(mock_data['tasks']):
        task['date_created'] = str(1704067200000 + i * 1000)  # Staggered timestamps
    mock_response.json.return_value = mock_data
    mock_requests_get.return_value = mock_response

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 200
    assert result['headers']['Content-Type'] == 'text/html'
    assert "<h1>Recent Kiln Drop-Offs</h1>" in result['body']
    assert "KO-FAKE-001" in result['body'] # Check for task data
    assert "Customer A" in result['body']
    
    # Check that sorting happened (the fixture is not sorted by date)
    # The last task in the fixture ('Customer J') has the latest timestamp, so it should appear first in the HTML.
    assert result['body'].find('Customer J') < result['body'].find('Customer A')


@patch('common.aws.get_secret')
@patch('kiln_dropoff_recent_entries_viewer.lambda_function.requests.get')
def test_lambda_handler_clickup_api_error(mock_requests_get, mock_get_secret, reload_lambda_function):
    """Test the handler's response to a ClickUp API error."""
    # Arrange
    mock_get_secret.return_value = 'fake-token'
    mock_requests_get.side_effect = HTTPError("401 Client Error: Unauthorized for url")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "401 Client Error: Unauthorized for url" in result['body']

def test_lambda_handler_missing_env_var(reload_lambda_function, monkeypatch):
    """Test the handler's response when a required environment variable is missing."""
    # Arrange
    monkeypatch.delenv('CLICKUP_LIST_KILNDROP_ID')
    importlib.reload(lambda_function) # Reload to pick up the deleted env var

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Server configuration error: Missing List ID" in result['body']


@patch('common.aws.get_secret')
def test_lambda_handler_secret_manager_error(mock_get_secret, reload_lambda_function):
    """Test the handler's response to a Secrets Manager error."""
    # Arrange
    mock_get_secret.side_effect = Exception("Could not connect to Secrets Manager")

    # Act
    result = lambda_function.lambda_handler({}, None)

    # Assert
    assert result['statusCode'] == 500
    assert "<h2>An Error Occurred</h2>" in result['body']
    assert "Could not connect to Secrets Manager" in result['body']
