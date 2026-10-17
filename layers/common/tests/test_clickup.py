import logging
import os
import sys
import traceback
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

    assert str(excinfo.value) == "ClickUp API HTTP Error: 401 Unauthorized - GET task/t1 (ECODE=OAUTH_025)"
    assert "pk_BODY_MARKER" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
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
    """A non-JSON error body reaches neither the exception text nor the log."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    error_response = _http_error_response(401, "Unauthorized", text="<html>pk_BODY_MARKER</html>")
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized", response=error_response
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("pk_TOKEN_MARKER", "t1")

    assert str(excinfo.value) == "ClickUp API HTTP Error: 401 Unauthorized - GET task/t1 (ECODE=None)"
    assert "<html>" not in str(excinfo.value)
    assert "pk_BODY_MARKER" not in str(excinfo.value)
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

    assert str(excinfo.value) == "Network error during ClickUp API request: GET task/t1 (ConnectionError)"
    assert str(err) not in str(excinfo.value)
    assert "pk_URL_MARKER" not in str(excinfo.value)
    assert "api.clickup.com" not in str(excinfo.value)
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

    assert str(excinfo.value) == "ClickUp task update for t1 returned 200 OK but task ID other (ECODE=None)"
    assert "Jane Member" not in str(excinfo.value)
    assert "bad" not in str(excinfo.value)
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

    assert str(excinfo.value) == "ClickUp task update for t1 returned 200 OK but no task ID (ECODE=None)"
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

    assert str(excinfo.value) == "ClickUp task update for t1 returned 200 OK but no task ID (ECODE=OAUTH_027)"
    assert "Team not authorized" not in str(excinfo.value)
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

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    assert str(excinfo.value) == "ClickUp task update for t1 returned 200 OK but task ID <invalid> (ECODE=None)"
    assert "jane@example.com" not in str(excinfo.value)

    assert capsys.readouterr().out == ""
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()
    assert "jane@example.com" not in caplog.text


def test_ecode_for_log_rejects_trailing_newline():
    """An ECODE with a trailing newline is not a valid code and is replaced."""
    assert clickup._ecode_for_log({"ECODE": "OAUTH_025\n"}) == "<invalid>"
    assert clickup._ecode_for_log({"ECODE": "OAUTH_025"}) == "OAUTH_025"


def test_task_id_for_log_rejects_trailing_newline():
    """A task ID with a trailing newline is not a valid ID and is replaced."""
    assert clickup._task_id_for_log("abc123\n") == "<invalid>"
    assert clickup._task_id_for_log("abc123") == "abc123"


def _formatted_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


@patch('common.clickup.requests.request')
def test_make_clickup_request_http_error_traceback_has_no_body_or_url(mock_requests_request, caplog):
    """Neither the message nor the formatted traceback carries the body or the requests URL."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    body = {
        "err": "Assignee Jane Member jane.member@example.com 512-555-0142",
        "ECODE": "ITEM_015",
    }
    error_response = _http_error_response(404, "Not Found", json_body=body)
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404 Client Error: Not Found for url: https://api.clickup.com/api/v2/task/t1?token=pk_URL_MARKER",
        response=error_response,
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("token", "t1")

    assert str(excinfo.value) == "ClickUp API HTTP Error: 404 Not Found - GET task/t1 (ECODE=ITEM_015)"
    formatted = _formatted_traceback(excinfo.value)
    for forbidden in ("pk_URL_MARKER", "token=", "jane.member@example.com", "512-555-0142",
                      "Jane Member", "HTTPError", "api.clickup.com"):
        assert forbidden not in formatted
        assert forbidden not in caplog.text


@patch('common.clickup.requests.request')
def test_make_clickup_request_network_error_traceback_has_no_url(mock_requests_request, caplog):
    """A network failure's traceback carries the exception class, not the URL or query string."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_requests_request.side_effect = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.clickup.com'): Max retries exceeded with url: /api/v2/task/t1?q=pk_URL_MARKER"
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("token", "t1")

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    formatted = _formatted_traceback(excinfo.value)
    assert "Network error during ClickUp API request: GET task/t1 (ConnectionError)" in formatted
    for forbidden in ("pk_URL_MARKER", "?q=", "HTTPSConnectionPool", "api.clickup.com"):
        assert forbidden not in formatted
        assert forbidden not in caplog.text


@patch('common.clickup._make_clickup_request')
def test_update_task_message_has_no_task_fields(mock_make_request, caplog):
    """A mismatched update names both task IDs and none of the returned task's fields."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_make_request.return_value = {
        "id": "other9",
        "name": "Broken bandsaw",
        "assignees": [{"username": "Jane Member", "email": "jane.member@example.com"}],
        "creator": {"username": "Sam Staff", "email": "sam.staff@example.com"},
        "description": "Reporter: Pat Doe, 512-555-0199",
    }

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    message = str(excinfo.value)
    assert message == "ClickUp task update for t1 returned 200 OK but task ID other9 (ECODE=None)"
    for forbidden in ("Broken bandsaw", "Jane Member", "jane.member@example.com", "Sam Staff",
                      "sam.staff@example.com", "Pat Doe", "512-555-0199"):
        assert forbidden not in message
        assert forbidden not in caplog.text


@patch('common.clickup._make_clickup_request')
def test_update_task_none_response_raises_value_error(mock_make_request):
    """A None response is 'no task ID', not a TypeError."""
    mock_make_request.return_value = None

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1", {"status": "done"})

    assert str(excinfo.value) == "ClickUp task update for t1 returned 200 OK but no task ID (ECODE=None)"


@patch('common.clickup._make_clickup_request')
def test_update_task_matching_id_returns_response(mock_make_request):
    """A response for the requested task is returned unchanged."""
    response_data = {"id": "t1", "name": "Task"}
    mock_make_request.return_value = response_data

    assert clickup.update_task("token", "t1", {"status": "done"}) is response_data


@patch('common.clickup._make_clickup_request')
def test_update_task_invalid_requested_id_not_in_message_or_log(mock_make_request, caplog):
    """A requested task ID that doesn't look like one is replaced in the message and the log."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_make_request.return_value = {"id": "other9"}

    with pytest.raises(ValueError) as excinfo:
        clickup.update_task("token", "t1 jane@example.com\n", {"status": "done"})

    assert str(excinfo.value) == "ClickUp task update for <invalid> returned 200 OK but task ID other9 (ECODE=None)"
    assert "jane@example.com" not in caplog.text
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()


@patch('common.clickup.requests.request')
def test_make_clickup_request_invalid_endpoint_not_in_message_or_log(mock_requests_request, caplog):
    """An endpoint with a query string or newline (from a crafted task ID) is replaced."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    error_response = _http_error_response(400, "Bad Request", json_body={"err": "x", "ECODE": "FIELD_001"})
    mock_requests_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "400 Bad Request", response=error_response
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.set_custom_field_value("token", "t1?x=pk_QUERY_MARKER\n", "f1", "v")

    message = str(excinfo.value)
    assert message == "ClickUp API HTTP Error: 400 Bad Request - POST <invalid> (ECODE=FIELD_001)"
    assert "\n" not in message
    assert "pk_QUERY_MARKER" not in caplog.text
    errors = _clickup_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()


@patch('common.clickup.requests.request')
def test_make_clickup_request_200_non_json_body_not_in_message(mock_requests_request, caplog):
    """A 200 whose body isn't JSON raises without the body in the message or traceback."""
    caplog.set_level(logging.DEBUG, logger="common.clickup")
    mock_requests_request.return_value.raise_for_status.return_value = None
    mock_requests_request.return_value.json.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", "<html>pk_BODY_MARKER jane.member@example.com</html>", 0
    )

    with pytest.raises(ValueError) as excinfo:
        clickup.get_task("token", "t1")

    assert str(excinfo.value) == "Network error during ClickUp API request: GET task/t1 (JSONDecodeError)"
    formatted = _formatted_traceback(excinfo.value)
    assert "pk_BODY_MARKER" not in formatted
    assert "jane.member@example.com" not in formatted
    assert "pk_BODY_MARKER" not in caplog.text


@pytest.mark.parametrize("endpoint, expected", [
    ("task/t1", "task/t1"),
    ("list/901/task", "list/901/task"),
    ("task/abc-1_2/field/0f1e-22", "task/abc-1_2/field/0f1e-22"),
    ("task/t1?x=1", "<invalid>"),
    ("task/t1\n", "<invalid>"),
    ("", "<invalid>"),
    (None, "<invalid>"),
    (123, "<invalid>"),
])
def test_endpoint_for_log_rejects_query_and_newline(endpoint, expected):
    """Only path characters pass; a query string, a newline or a non-string is replaced."""
    assert clickup._endpoint_for_log(endpoint) == expected
