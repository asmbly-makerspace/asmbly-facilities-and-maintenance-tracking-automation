import requests
import json

# --- ClickUp API Functions ---

BASE_URL = "https://api.clickup.com/api/v2"

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

            if isinstance(field_value, list) and len(field_value) > 0:
                if all(isinstance(item, str) for item in field_value):
                    return ", ".join(item.strip() for item in field_value)
                return None

            if isinstance(field_value, (int, float)):
                 return str(field_value)

            if isinstance(field_value, bool):
                 return str(field_value)

            return None

    return None

def fetch_tasks_page(list_id, api_token, page_num, params=None):
    """
    Fetches a single page of tasks from the ClickUp API.
    """
    endpoint = f"{BASE_URL}/list/{list_id}/task"
    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }
    
    query_params = {
        "archived": "false",
        "page": page_num,
    }
    if params:
        query_params.update(params)

    try:
        response = requests.get(endpoint, headers=headers, params=query_params)
        response.raise_for_status()
        data = response.json()
        tasks_on_page = data.get('tasks', [])
        is_last_page = data.get('last_page', True) if not tasks_on_page else data.get('last_page', False)
        return tasks_on_page, is_last_page
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
        error_message = f"Network error fetching tasks from ClickUp: {str(e)}"
        print(error_message)
        raise ValueError(error_message)

def get_all_tasks(list_id, api_token, max_pages=20, params=None):
    """
    Fetches all tasks from a ClickUp list, paginating as necessary.
    """
    all_tasks = []
    current_page = 0

    while True:
        if current_page >= max_pages:
            print(f"Reached maximum page limit ({max_pages}). Stopping task fetch.")
            break

        tasks_on_page, is_last_page = fetch_tasks_.page(
            list_id, api_token, current_page, params=params
        )

        if tasks_on_page is None:
            break

        all_tasks.extend(tasks_on_page)

        if is_last_page or not tasks_on_page:
            break

        current_page += 1

    return all_tasks

def get_task_details(api_token, task_id):
    """Retrieves task details from a ClickUp task."""
    url = f"{BASE_URL}/task/{task_id}"
    headers = {"Authorization": api_token}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def create_task(api_token, list_id, payload):
    """Creates a ClickUp task."""
    url = f"{BASE_URL}/list/{list_id}/task"
    headers = {"Authorization": api_token, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()
