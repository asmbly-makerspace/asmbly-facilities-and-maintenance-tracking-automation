import json
import requests # type: ignore
from dataclasses import dataclass


BASE_URL = "https://api.clickup.com/api/v2"


@dataclass
class ClickUpTask:
    """A simple data class to hold processed task information."""
    channel: str
    asset_name: str | None
    frequency: str | None
    task_id: str
    task_name: str
    task_url: str
    time_status: str
    task_description: str | None


def _make_clickup_request(api_token, method, endpoint, **kwargs):
    """Makes a request to the ClickUp API and handles errors."""
    headers = {"Authorization": api_token, "Content-Type": "application/json"}
    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_message = f"ClickUp API HTTP Error: {e.response.status_code} {e.response.reason}"
        try:
            error_details = e.response.json()
            error_message += f" - Details: {json.dumps(error_details)}"
        except ValueError:
            error_message += f" - Response body: {e.response.text}"
        print(error_message)
        raise ValueError(error_message)
    except requests.exceptions.RequestException as e:
        error_message = f"Network error during ClickUp API request: {str(e)}"
        print(error_message)
        raise ValueError(error_message)


def get_task(api_token, task_id):
    """Retrieves task details from a ClickUp task."""
    return _make_clickup_request(api_token, "GET", f"task/{task_id}")


def create_task(api_token, list_id, payload):
    """Creates a ClickUp task in a specific list."""
    return _make_clickup_request(api_token, "POST", f"list/{list_id}/task", json=payload)

def update_task(api_token, task_id, payload):
    """Updates a ClickUp task."""
    return _make_clickup_request(api_token, "PUT", f"task/{task_id}", json=payload)


def get_custom_field_value(task, field_id):
    """
    Extracts the value of a custom field from a ClickUp task object using its ID.
    """
    if not field_id:
        return None

    custom_fields = task.get('custom_fields', [])
    if not isinstance(custom_fields, list):
        return None

    for field in custom_fields:
        if not isinstance(field, dict) or 'id' not in field:
            continue

        if field.get('id') == field_id:
            field_value = field.get('value')

            if field_value is None:
                return None

            if field.get('type') == 'drop_down' and isinstance(field_value, (str, int)):
                type_config = field.get('type_config', {})
                options = type_config.get('options', [])
                try:
                    if isinstance(field_value, str):
                        for option in options:
                            if option.get('id') == field_value:
                                return option.get('name')
                    val_as_int = int(field_value)
                    for option in options:
                        if option.get('orderindex') == val_as_int:
                            return option.get('name')
                except (ValueError, TypeError):
                    pass
                return None

            if isinstance(field_value, str):
                return field_value.strip()

            # Handle 'relation' fields which can be a list of objects with a 'name' key
            if isinstance(field_value, list) and len(field_value) > 0:
                # Check if items are strings or objects with a 'name'
                if all(isinstance(item, dict) and 'name' in item for item in field_value):
                    return ", ".join(item['name'] for item in field_value if item.get('name'))
                # Fallback for a list of simple strings
                elif all(isinstance(item, str) for item in field_value):
                    return ", ".join(item.strip() for item in field_value)

            if isinstance(field_value, (int, float)):
                 return str(field_value)

            if isinstance(field_value, bool):
                 return str(field_value)

            return None

    return None

def fetch_clickup_tasks_page(list_id, api_token, page_num, due_date_lt_ms=None, due_date_gt_ms=None, include_subtasks=False, include_closed=False):
    """
    Fetches a single page of tasks from the ClickUp API with optional date ranges.
    """
    endpoint = f"list/{list_id}/task"
    query_params = {
        "archived": "false",
        "page": page_num,
        "subtasks": str(include_subtasks).lower(),
        "include_closed": str(include_closed).lower(),
    }
    if due_date_lt_ms is not None:
        query_params["due_date_lt"] = due_date_lt_ms
    if due_date_gt_ms is not None:
        query_params["due_date_gt"] = due_date_gt_ms

    data = _make_clickup_request(api_token, "GET", endpoint, params=query_params)
    tasks_on_page = data.get('tasks', [])
    is_last_page = data.get('last_page', True) if not tasks_on_page else data.get('last_page', False)
    return tasks_on_page, is_last_page

def get_all_clickup_tasks(list_id, api_token, due_date_lt_ms=None, due_date_gt_ms=None, max_pages=20, **kwargs):
    """
    Fetches all tasks from a ClickUp list, paginating as necessary.
    """
    all_tasks = []
    current_page = 0
    include_subtasks = False
    include_closed = False

    while True:
        if current_page >= max_pages:
            print(f"Reached maximum page limit ({max_pages}). Stopping task fetch.")
            break

        tasks_on_page, is_last_page = fetch_clickup_tasks_page(
            list_id, api_token, current_page,
            due_date_lt_ms=due_date_lt_ms, due_date_gt_ms=due_date_gt_ms,
            include_subtasks=include_subtasks, include_closed=include_closed
        )

        if tasks_on_page is None:
            break

        all_tasks.extend(tasks_on_page)

        if is_last_page or not tasks_on_page:
            break

        current_page += 1

    return all_tasks
