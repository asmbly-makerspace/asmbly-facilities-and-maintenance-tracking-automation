import requests
import logging
import re
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)


def _make_discourse_request(method: str, url: str, api_key: str, api_username: str, **kwargs: Any) -> Any:
    """Helper function to make requests to the Discourse API. A failure is logged and re-raised."""
    headers = {
        "Api-Key": api_key,
        "Api-Username": api_username,
        "Content-Type": "application/json"
    }
    try:
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # The path only: no query string, no response body, no requests text.
        path = urllib.parse.urlsplit(url).path
        if e.response is not None:
            logger.error("Discourse %s %s failed with HTTP %s", method, path, e.response.status_code)
        else:
            logger.error("Discourse %s %s failed: %s", method, path, type(e).__name__)
        raise

def create_post(base_url, title, content, api_key, api_username, category_id):
    """Creates a new topic in Discourse and returns its URL."""
    url = f"{base_url}/posts.json"
    payload = {
        "title": title,
        "raw": content,
        "category": category_id
    }
        
    response_data = _make_discourse_request("POST", url, api_key, api_username, json=payload)
    
    # Construct the URL from the response
    topic_slug = response_data.get('topic_slug')
    topic_id = response_data.get('topic_id')
    if topic_slug and topic_id:
        return f"{base_url}/t/{topic_slug}/{topic_id}"
    else:
        logger.error("Could not construct Discourse URL from response.")
        return None

def post_reply(base_url, topic_id, post_number, message, api_key, api_username):
    """Posts a reply to a specific topic in Discourse."""
    url = f"{base_url}/posts.json"
    payload = {
        "topic_id": topic_id,
        "raw": message,
        "reply_to_post_number": post_number
    }
    return _make_discourse_request("POST", url, api_key, api_username, json=payload)


def mark_solution(base_url, post_id, api_key, api_username):
    """Marks a post as the solution in a Discourse topic."""
    url = f"{base_url}/solution/accept"
    payload = {"id": post_id}
    return _make_discourse_request("POST", url, api_key, api_username, json=payload)


def parse_discourse_url(text):
    """
    Parses a Discourse URL from a string to extract base_url, topic_id, and post_number.
    Example: https://yo.asmbly.org/t/some-topic-slug/14509/1
    """
    match = re.search(r"(https?://[^/]+)/t/[^/]+/(\d+)/(\d+)", text)
    if match:
        return {
            "base_url": match.group(1),
            "topic_id": match.group(2),
            "post_number": match.group(3)
        }
    return None
