import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

# Now we can import the clickup module directly
from common import clickup


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
    assert clickup.get_custom_field_value(task, field_id) == expected_value


@patch('common.clickup.requests.request')
def test_fetch_clickup_tasks_page_success(mock_requests_request):
    """Test successfully fetching a page of tasks from ClickUp."""
    list_id = '123'
    api_token = 'token'
    page_num = 0
    mock_response = {'tasks': [{'id': 'task1'}], 'last_page': True}
    mock_requests_request.return_value.json.return_value = mock_response
    mock_requests_request.return_value.raise_for_status.return_value = None

    tasks, last_page = clickup.fetch_clickup_tasks_page(list_id, api_token, page_num)

    assert len(tasks) == 1
    assert tasks[0]['id'] == 'task1'
    assert last_page is True
    mock_requests_request.assert_called_once()


@patch('common.clickup.requests.request')
def test_fetch_clickup_tasks_page_http_error(mock_requests_request):
    """Test that an HTTP error from ClickUp API is handled."""
    from unittest.mock import MagicMock
    import json
    from requests.exceptions import HTTPError
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.reason = "Unauthorized"
    mock_response.text = "Invalid JSON body"
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
    mock_requests_request.return_value.raise_for_status.side_effect = HTTPError("401 Unauthorized", response=mock_response)

    with pytest.raises(ValueError, match="ClickUp API HTTP Error: 401 Unauthorized"):
        clickup.fetch_clickup_tasks_page('123', 'token', 0)


@patch('common.clickup.fetch_clickup_tasks_page')
def test_get_all_clickup_tasks_pagination(mock_fetch_page):
    """Test that get_all_clickup_tasks paginates correctly."""
    mock_fetch_page.side_effect = [
        ([{'id': 'task1'}], False),  # Page 0
        ([{'id': 'task2'}], True),   # Page 1 (last page)
    ]

    tasks = clickup.get_all_clickup_tasks('list-id', 'api-token')

    assert len(tasks) == 2
    assert tasks[0]['id'] == 'task1'
    assert tasks[1]['id'] == 'task2'
    assert mock_fetch_page.call_count == 2


@patch('common.clickup.fetch_clickup_tasks_page')
def test_get_all_clickup_tasks_max_pages(mock_fetch_page, caplog, capsys):
    """Test that pagination stops at the max_pages limit and logs a warning."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_fetch_page.return_value = ([{'id': 'task_on_page'}], False)

    tasks = clickup.get_all_clickup_tasks('list-id', 'api-token', max_pages=3)

    assert len(tasks) == 3
    assert mock_fetch_page.call_count == 3
    assert capsys.readouterr().out == ""
    warnings = [r for r in caplog.records if r.name == "common.clickup" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "3" in warnings[0].getMessage()
    assert "list-id" in warnings[0].getMessage()


@patch('common.clickup._make_clickup_request')
def test_get_list_custom_fields(mock_make_request):
    """Test retrieving custom fields for a list."""
    api_token = 'test_token'
    list_id = 'list_123'
    mock_response = {
        "fields": [
            {"id": "field_abc", "name": "Test Field 1"},
            {"id": "field_def", "name": "Test Field 2"}
        ]
    }
    mock_make_request.return_value = mock_response

    fields = clickup.get_list_custom_fields(api_token, list_id)

    mock_make_request.assert_called_once_with(api_token, "GET", f"list/{list_id}/field")
    assert len(fields) == 2
    assert fields[0]['id'] == 'field_abc'
    assert fields[1]['name'] == 'Test Field 2'


def _http_error_response(status_code, reason, json_body=None, text=""):
    """Build a mock error response; .json() raises ValueError when json_body is None."""
    error_response = MagicMock()
    error_response.status_code = status_code
    error_response.reason = reason
    error_response.text = text
    if json_body is None:
        error_response.json.side_effect = ValueError("not json")
    else:
        error_response.json.return_value = json_body
    return error_response


def _clickup_errors(caplog):
    return [r for r in caplog.records if r.name == "common.clickup" and r.levelno == logging.ERROR]


@patch('common.clickup.requests.request')
def test_make_clickup_request_http_error_logs_status_not_body(mock_requests_request, caplog, capsys):
    """A ClickUp HTTP error logs the method, endpoint, status and ECODE, never the body or token."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    body = {"err": "echo pk_BODY_MARKER", "ECODE": "OAUTH_025"}
    error_response = _http_error_response(401, "Unauthorized", json_body=body)
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized", response=error_response
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("pk_TOKEN_MARKER", "t1")

    assert str(excinfo.value) == (
        'ClickUp API HTTP Error: 401 Unauthorized - Details: {"err": "echo pk_BODY_MARKER", "ECODE": "OAUTH_025"}'
    )
    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    for expected in ("GET", "task/t1", "401", "OAUTH_025"):
        assert expected in message
    for forbidden in ("pk_BODY_MARKER", "pk_TOKEN_MARKER", "Authorization"):
        assert forbidden not in caplog.text


@patch('common.clickup.requests.request')
def test_make_clickup_request_http_error_invalid_ecode_not_logged(mock_requests_request, caplog, capsys):
    """An ECODE that doesn't look like a ClickUp code is replaced in the log."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    body = {"err": "x", "ECODE": "pk_ECODE_MARKER lowercase"}
    error_response = _http_error_response(400, "Bad Request", json_body=body)
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "400 Bad Request", response=error_response
    )

    with pytest.raises(ValueError):
        clickup.get_task("token", "t1")

    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()
    assert "pk_ECODE_MARKER" not in caplog.text


@patch('common.clickup.requests.request')
def test_make_clickup_request_http_error_non_json_body_not_logged(mock_requests_request, caplog, capsys):
    """A non-JSON error body stays in the exception text but never reaches the log."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    error_response = _http_error_response(401, "Unauthorized", text="<html>pk_BODY_MARKER</html>")
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized", response=error_response
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("pk_TOKEN_MARKER", "t1")

    assert str(excinfo.value) == "ClickUp API HTTP Error: 401 Unauthorized - Response body: <html>pk_BODY_MARKER</html>"
    assert capsys.readouterr().out == ""
    assert len(_clickup_errors(caplog)) == 1
    assert "pk_BODY_MARKER" not in caplog.text
    assert "pk_TOKEN_MARKER" not in caplog.text


@patch('common.clickup.requests.request')
def test_make_clickup_request_network_error_logs_type_only(mock_requests_request, caplog, capsys):
    """A request failure logs the exception type and endpoint, not its text (which holds the URL)."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    err = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.clickup.com'): Max retries exceeded with url: /api/v2/task/t1?x=pk_URL_MARKER"
    )
    mock_requests_request.side_effect = err

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("pk_TOKEN_MARKER", "t1")

    assert str(excinfo.value) == "Network error during ClickUp API request: " + str(err)
    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "ConnectionError" in errors[0].getMessage()
    assert "task/t1" in errors[0].getMessage()
    assert "pk_URL_MARKER" not in caplog.text
    assert "pk_TOKEN_MARKER" not in caplog.text


@patch('common.clickup.requests.request')
def test_create_task_error_does_not_log_payload(mock_requests_request, caplog, capsys):
    """A failed create never logs the request payload."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    error_response = _http_error_response(400, "Bad Request", json_body={"err": "bad", "ECODE": "ITEM_015"})
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "400 Bad Request", response=error_response
    )

    with pytest.raises(ValueError):
        clickup.create_task("token", "list-1", {"name": "pk_PAYLOAD_MARKER"})

    assert capsys.readouterr().out == ""
    assert len(_clickup_errors(caplog)) == 1
    assert "pk_PAYLOAD_MARKER" not in caplog.text


@patch('common.clickup._make_clickup_request')
def test_update_task_mismatch_logs_ids_not_task_body(mock_make_request, caplog, capsys):
    """An update whose response is for another task logs the IDs, not the task object."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    response_data = {"id": "other", "name": "Jane Member", "err": "bad"}
    mock_make_request.return_value = response_data

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    assert str(excinfo.value) == (
        "ClickUp task update for t1 returned 200 OK but the response body indicates a failure. "
        f"Response: {json.dumps(response_data)} | ClickUp Error: bad"
    )
    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "t1" in errors[0].getMessage()
    assert "other" in errors[0].getMessage()
    assert "Jane Member" not in caplog.text


@patch('common.clickup._make_clickup_request')
def test_update_task_list_response_raises_same_value_error(mock_make_request, caplog, capsys):
    """A non-dict response still raises the same ValueError, not an AttributeError."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_make_request.return_value = []

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    assert str(excinfo.value) == (
        "ClickUp task update for t1 returned 200 OK but the response body indicates a failure. Response: []"
    )
    assert capsys.readouterr().out == ""
    assert len(_clickup_errors(caplog)) == 1


@patch('common.clickup._make_clickup_request')
def test_update_task_missing_id_logs_no_task_id(mock_make_request, caplog, capsys):
    """A response without an ID logs that no task ID came back, not 'task ID None'."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    response_data = {"err": "Team not authorized", "ECODE": "OAUTH_027"}
    mock_make_request.return_value = response_data

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    assert str(excinfo.value) == (
        "ClickUp task update for t1 returned 200 OK but the response body indicates a failure. "
        f"Response: {json.dumps(response_data)} | ClickUp Error: Team not authorized"
    )
    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "returned no task ID" in message
    assert "None" not in message
    assert "OAUTH_027" in message
    assert "Team not authorized" not in caplog.text


@patch('common.clickup._make_clickup_request')
def test_update_task_mismatch_with_non_id_value_not_logged(mock_make_request, caplog, capsys):
    """A returned 'id' that doesn't look like a task ID is not copied into the log."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_make_request.return_value = {"id": "Jane Member jane@example.com"}

    with pytest.raises(ValueError):
        clickup.update_task("token", "t1", {"status": "done"})

    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()
    assert "jane@example.com" not in caplog.text
