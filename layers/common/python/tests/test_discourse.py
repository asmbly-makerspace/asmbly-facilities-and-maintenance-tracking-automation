import unittest
from unittest.mock import patch, Mock
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
        
        result_url = discourse.create_post(base_url, title, content, api_key, api_username)
        
        self.assertEqual(result_url, "https://test.discourse.url/t/test-topic-slug/12345")
        mock_make_request.assert_called_once_with(
            "POST",
            f"{base_url}/posts.json",
            api_key,
            api_username,
            json={"title": title, "raw": content}
        )

    @patch('common.discourse._make_discourse_request')
    def test_create_post_api_failure(self, mock_make_request):
        """Tests handling of an API failure during post creation."""
        mock_make_request.side_effect = Exception("API Error")
        
        with self.assertRaises(Exception) as context:
            discourse.create_post("url", "title", "content", "key", "user")
        
        self.assertTrue("API Error" in str(context.exception))

    @patch('common.discourse._make_discourse_request')
    def test_create_post_missing_slug_in_response(self, mock_make_request):
        """Tests that None is returned if the slug is missing from the response."""
        mock_make_request.return_value = {"topic_id": 12345} # Missing 'topic_slug'
        
        result_url = discourse.create_post("url", "title", "content", "key", "user")
        
        self.assertIsNone(result_url)
