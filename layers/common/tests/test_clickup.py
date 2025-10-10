import json
import os
import importlib
import sys
import pathlib
from unittest.mock import patch

import pytest

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


def test_fetch_clickup_tasks_page_success(requests_mock):
    """Test successfully fetching a page of tasks from ClickUp."""
    list_id = '123'
    api_token = 'token'
    page_num = 0
    mock_response = {'tasks': [{'id': 'task1'}], 'last_page': True}
    requests_mock.get(f"https://api.clickup.com/api/v2/list/{list_id}/task", json=mock_response)

    tasks, last_page = clickup.fetch_clickup_tasks_page(list_id, api_token, page_num)

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
        clickup.fetch_clickup_tasks_page(list_id, api_token, page_num)


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
def test_get_all_clickup_tasks_max_pages(mock_fetch_page):
    """Test that pagination stops at the max_pages limit."""
    mock_fetch_page.return_value = ([{'id': 'task_on_page'}], False)

    tasks = clickup.get_all_clickup_tasks('list-id', 'api-token', max_pages=3)

    assert len(tasks) == 3
    assert mock_fetch_page.call_count == 3
