import logging
import os
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock

import pytest
import requests
from common import discourse

class TestDiscourse(unittest.TestCase):

    @patch('common.discourse.requests.request')
    def test_make_discourse_request_success(self, mock_request):
        """Test successful Discourse API request."""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"success": "ok"}
        mock_request.return_value = mock_response

        result = discourse._make_discourse_request("GET", "http://test.com/test", "test_key", "test_user")

        self.assertEqual(result, {"success": "ok"})
        mock_request.assert_called_once_with(
            "GET", "http://test.com/test",
            headers={
                "Api-Key": "test_key",
                "Api-Username": "test_user",
                "Content-Type": "application/json"
            }
        )

    @patch('common.discourse.requests.request')
    def test_make_discourse_request_http_error(self, mock_request):
        """Test Discourse API request raising an HTTPError."""
        mock_response = Mock()
        mock_response.text = '{"error": "bad request"}'
        http_error = requests.exceptions.HTTPError("HTTP Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_request.return_value = mock_response

        with self.assertRaises(requests.exceptions.HTTPError):
            discourse._make_discourse_request("GET", "http://test.com/test", "test_key", "test_user")

    @patch('common.discourse.requests.request')
    def test_make_discourse_request_network_error(self, mock_request):
        """Test Discourse API request raising a RequestException."""
        mock_request.side_effect = requests.exceptions.RequestException("Network Error")

        with self.assertRaises(requests.exceptions.RequestException):
            discourse._make_discourse_request("GET", "http://test.com/test", "test_key", "test_user")

    @patch('common.discourse._make_discourse_request')
    def test_post_reply(self, mock_make_request):
        """Test posting a reply."""
        mock_make_request.return_value = {"id": 123}
        result = discourse.post_reply("http://test.com", "topic1", "post1", "Hello", "key", "user")

        self.assertEqual(result, {"id": 123})
        expected_payload = {
            "topic_id": "topic1",
            "raw": "Hello",
            "reply_to_post_number": "post1"
        }
        mock_make_request.assert_called_once_with(
            "POST", "http://test.com/posts.json", "key", "user", json=expected_payload
        )

    @patch('common.discourse._make_discourse_request')
    def test_mark_solution(self, mock_make_request):
        """Test marking a post as a solution."""
        mock_make_request.return_value = {"success": "ok"}
        result = discourse.mark_solution("http://test.com", "post123", "key", "user")

        self.assertEqual(result, {"success": "ok"})
        expected_payload = {"id": "post123"}
        mock_make_request.assert_called_once_with(
            "POST", "http://test.com/solution/accept", "key", "user", json=expected_payload
        )

    def test_parse_discourse_url_valid(self):
        """Test parsing a valid Discourse URL."""
        url = "https://yo.asmbly.org/t/some-topic-slug/14509/1"
        expected = {
            "base_url": "https://yo.asmbly.org",
            "topic_id": "14509",
            "post_number": "1"
        }
        self.assertEqual(discourse.parse_discourse_url(url), expected)

    def test_parse_discourse_url_http(self):
        """Test parsing a valid HTTP Discourse URL."""
        url = "http://yo.asmbly.org/t/some-topic-slug/14509/1"
        expected = {
            "base_url": "http://yo.asmbly.org",
            "topic_id": "14509",
            "post_number": "1"
        }
        self.assertEqual(discourse.parse_discourse_url(url), expected)

    def test_parse_discourse_url_no_post_number(self):
        """Test parsing a Discourse URL that points to a topic, not a post."""
        url = "https://yo.asmbly.org/t/some-topic-slug/14509"
        self.assertIsNone(discourse.parse_discourse_url(url))

    def test_parse_discourse_url_invalid(self):
        """Test parsing an invalid string."""
        url = "this is not a url"
        self.assertIsNone(discourse.parse_discourse_url(url))

    def test_parse_discourse_url_in_text(self):
        """Test parsing a URL embedded in other text."""
        text = "Check out this post: https://yo.asmbly.org/t/topic/123/4"
        expected = {
            "base_url": "https://yo.asmbly.org",
            "topic_id": "123",
            "post_number": "4"
        }
        self.assertEqual(discourse.parse_discourse_url(text), expected)

    @patch('common.discourse._make_discourse_request')
    def test_create_post_success(self, mock_make_request):
        """Tests successful creation of a Discourse post."""
        mock_make_request.return_value = {
            "topic_slug": "test-topic-slug",
            "topic_id": 12345
        }
        
        base_url = "https://test.discourse.url"
        title = "Test Title"
        content = "Test content"
        api_key = "test_key"
        api_username = "test_user"
        category_id = "12"

        result_url = discourse.create_post(base_url, title, content, api_key, api_username, category_id)
        
        self.assertEqual(result_url, "https://test.discourse.url/t/test-topic-slug/12345")
        mock_make_request.assert_called_once_with(
            "POST",
            f"{base_url}/posts.json",
            api_key,
            api_username,
            json={"title": title, "raw": content, "category": category_id}
        )

    @patch('common.discourse._make_discourse_request')
    def test_create_post_api_failure(self, mock_make_request):
        """Tests handling of an API failure during post creation."""
        mock_make_request.side_effect = Exception("API Error")
        
        with self.assertRaises(Exception) as context:
            discourse.create_post("url", "title", "content", "key", "user", "12")
        
        self.assertTrue("API Error" in str(context.exception))

    @patch('common.discourse._make_discourse_request')
    def test_create_post_missing_slug_in_response(self, mock_make_request):
        """Tests that None is returned if the slug is missing from the response."""
        mock_make_request.return_value = {"topic_id": 12345} # Missing 'topic_slug'
        
        result_url = discourse.create_post("url", "title", "content", "key", "user", "12")
        
        self.assertIsNone(result_url)



# --- Failure logging ---

DISCOURSE_URL = "https://yo.asmbly.org/posts.json?api_key=pk_QUERY"
LAYER_PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]


def _discourse_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "common.discourse" and r.levelno == logging.ERROR]


def test_http_error_logs_method_path_status_not_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.discourse")
    response = Mock(status_code=422, text="pk_DISCOURSE_BODY reporter@example.com")
    error = requests.exceptions.HTTPError(f"422 Client Error for url: {DISCOURSE_URL}", response=response)
    with patch("common.discourse.requests.request") as mock_request:
        mock_request.return_value.raise_for_status.side_effect = error

        with pytest.raises(requests.exceptions.HTTPError) as excinfo:
            discourse._make_discourse_request("POST", DISCOURSE_URL, "pk_API_KEY", "system", json={"raw": "x"})

    assert excinfo.value is error
    assert [r.getMessage() for r in _discourse_errors(caplog)] == ["Discourse POST /posts.json failed with HTTP 422"]
    for marker in ("pk_DISCOURSE_BODY", "reporter@example.com", "pk_QUERY", "pk_API_KEY", "yo.asmbly.org"):
        assert marker not in caplog.text


def test_network_error_logs_type_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.discourse")
    error = requests.exceptions.ConnectionError("pk_URL")
    with patch("common.discourse.requests.request") as mock_request:
        mock_request.side_effect = error

        with pytest.raises(requests.exceptions.ConnectionError) as excinfo:
            discourse._make_discourse_request("POST", DISCOURSE_URL, "pk_API_KEY", "system")

    assert excinfo.value is error
    assert [r.getMessage() for r in _discourse_errors(caplog)] == ["Discourse POST /posts.json failed: ConnectionError"]
    assert "pk_URL" not in caplog.text
    assert "pk_QUERY" not in caplog.text


def test_logger_is_named() -> None:
    """Records come from common.discourse, and importing the module sets no level."""
    assert discourse.logger.name == "common.discourse"
    code = (
        "import logging\n"
        "logging.getLogger().setLevel(logging.WARNING)\n"
        "import common.discourse\n"
        "print(logging.getLogger().level, logging.getLogger('common.discourse').level)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(LAYER_PYTHON_DIR)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)

    assert [int(level) for level in result.stdout.split()] == [logging.WARNING, logging.NOTSET]
