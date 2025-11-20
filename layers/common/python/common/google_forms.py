import json

def parse_form_response(event_body):
    """
    Parses the JSON string from a Google Forms webhook event body.

    Args:
        event_body (str): The raw string body from the webhook request.

    Returns:
        dict: The dictionary containing the form questions and answers.
              Returns an empty dictionary if parsing fails or 'data' is not found.
    """
    try:
        data = json.loads(event_body)
        return data.get("data", {})
    except (json.JSONDecodeError, TypeError):
        return {}
