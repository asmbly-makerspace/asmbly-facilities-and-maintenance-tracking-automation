import unittest
from unittest.mock import patch, Mock
import base64
import json
import logging
from typing import Any

import pytest
import requests_mock as requests_mock_lib
import requests
from common.neoncrm import MAX_SEARCH_PAGES, NeonCRM, NeonCRMError

class TestNeonCRM(unittest.TestCase):

    def setUp(self):
        self.org_id = "test_org"
        self.api_key = "test_key"
        self.client = NeonCRM(self.org_id, self.api_key)

    def test_init(self):
        """Test that the NeonCRM client is initialized correctly."""
        self.assertEqual(self.client.org_id, self.org_id)
        self.assertEqual(self.client.api_key, self.api_key)
        self.assertEqual(self.client.base_url, "https://api.neoncrm.com/v2")

        auth_string = f"{self.org_id}:{self.api_key}"
        expected_auth_header = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

        self.assertIn("Authorization", self.client.headers)
        self.assertEqual(self.client.headers["Authorization"], f"Basic {expected_auth_header}")
        self.assertEqual(self.client.headers["Content-Type"], "application/json")

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_found(self, mock_post):
        """Test retrieving an account by email when the account exists."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "searchResults": [{"Account ID": "12345"}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        account_id = self.client.get_account_by_email("test@example.com")

        self.assertEqual(account_id, "12345")
        expected_url = f"{self.client.base_url}/accounts/search"
        expected_payload = {
            "searchFields": [{"field": "Email 1", "operator": "EQUAL", "value": "test@example.com"}],
            "outputFields": ["Account ID"],
            "pagination": {"currentPage": 0, "pageSize": 1},
        }
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_not_found(self, mock_post):
        """Test retrieving an account by email when the account does not exist."""
        mock_response = Mock()
        mock_response.json.return_value = {"searchResults": []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        account_id = self.client.get_account_by_email("notfound@example.com")

        self.assertIsNone(account_id)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_found_logs_account_id_not_email(self, mock_post):
        """A found account is logged by its ID; the searched email never reaches the log."""
        mock_response = Mock()
        mock_response.json.return_value = {"searchResults": [{"Account ID": "12345"}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with self.assertLogs(level="DEBUG") as logs:
            account_id = self.client.get_account_by_email("test@example.com")

        self.assertEqual(account_id, "12345")
        output = "\n".join(logs.output)
        self.assertIn("12345", output)
        self.assertNotIn("test@example.com", output)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_not_found_does_not_log_email(self, mock_post):
        """When no account matches, the log line does not contain the searched email."""
        mock_response = Mock()
        mock_response.json.return_value = {"searchResults": []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with self.assertLogs(level="DEBUG") as logs:
            account_id = self.client.get_account_by_email("notfound@example.com")

        self.assertIsNone(account_id)
        output = "\n".join(logs.output)
        self.assertNotIn("notfound@example.com", output)
        self.assertNotIn("notfound", output)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_api_error(self, mock_post):
        """Test handling of API errors when searching for an account."""
        mock_post.side_effect = requests.exceptions.RequestException("API Error")

        account_id = self.client.get_account_by_email("test@example.com")

        self.assertIsNone(account_id)

    @patch('common.neoncrm.requests.post')
    def test_get_account_by_email_api_error_logs_type_not_email(self, mock_post):
        """An API error logs the exception type only; the searched email never reaches the log."""
        mock_post.side_effect = requests.exceptions.RequestException(
            "400 Client Error for search value test@example.com"
        )

        with self.assertLogs(level="DEBUG") as logs:
            account_id = self.client.get_account_by_email("test@example.com")

        self.assertIsNone(account_id)
        output = "\n".join(logs.output)
        self.assertIn("RequestException", output)
        self.assertNotIn("test@example.com", output)

    @patch('common.neoncrm.requests.patch')
    def test_update_account_custom_field_success(self, mock_patch):
        """Test successfully updating a custom field for an account."""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_patch.return_value = mock_response

        account_id = "12345"
        field_id = "10"
        field_value = "New Value"

        # This method doesn't return anything, so we just check for no exceptions
        self.client.update_account_custom_field(account_id, field_id, field_value)

        expected_url = f"{self.client.base_url}/accounts/{account_id}"
        expected_payload = {
            "individualAccount": {
                "accountCustomFields": [{"id": field_id, "value": field_value}]
            }
        }
        mock_patch.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch('common.neoncrm.requests.patch')
    def test_update_account_custom_field_api_error(self, mock_patch):
        """Test handling of API errors when updating a custom field."""
        mock_patch.side_effect = requests.exceptions.RequestException("API Error")

        account_id = "12345"
        field_id = "10"
        field_value = "New Value"

        # We expect this to fail silently and log an error, not raise an exception
        try:
            self.client.update_account_custom_field(account_id, field_id, field_value)
        except Exception as e:
            self.fail(f"update_account_custom_field raised an unexpected exception: {e}")


# --- NeonCRM.search_events (pytest style, requests-mock: no network) ---

SEARCH_URL = "https://api.neoncrm.com/v2/events/search"
SEARCH_FIELDS = [{"field": "Event End Date", "operator": "GREATER_AND_EQUAL", "value": "2026-06-16"}]
OUTPUT_FIELDS = ["Event ID", "Event Name"]
BODY_MARKER = "SECRET-BODY-MARKER-7f3a"


@pytest.fixture
def neon() -> NeonCRM:
    return NeonCRM("test_org", "test_key")


def _page(results: list[dict], current: int, total: int) -> dict:
    return {"searchResults": results, "pagination": {"currentPage": current, "totalPages": total}}


def test_search_events_posts_fields_and_pagination(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(SEARCH_URL, json=_page([{"Event ID": "1", "Event Name": "A"}], 0, 1))

    results = neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert results == [{"Event ID": "1", "Event Name": "A"}]
    assert requests_mock.call_count == 1
    request = requests_mock.request_history[0]
    assert request.json() == {
        "searchFields": SEARCH_FIELDS,
        "outputFields": OUTPUT_FIELDS,
        "pagination": {"currentPage": 0, "pageSize": 200},
    }
    expected = base64.b64encode(b"test_org:test_key").decode("utf-8")
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert request.timeout == 10.0


def test_search_events_reads_every_page(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(
        SEARCH_URL,
        [
            {"json": _page([{"Event ID": "1"}, {"Event ID": "2"}], 0, 2)},
            {"json": _page([{"Event ID": "3"}], 1, 2)},
        ],
    )

    results = neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert [r["Event ID"] for r in results] == ["1", "2", "3"]
    assert [r.json()["pagination"]["currentPage"] for r in requests_mock.request_history] == [0, 1]


def test_search_events_stops_at_page_guard(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture) -> None:
    requests_mock.post(SEARCH_URL, json=_page([{"Event ID": "x"}], 0, 10_000))

    with caplog.at_level(logging.WARNING):
        results = neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert requests_mock.call_count == MAX_SEARCH_PAGES
    assert len(results) == MAX_SEARCH_PAGES
    assert "stopped at" in caplog.text


def test_search_events_without_pagination_reads_one_page(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(SEARCH_URL, json={"searchResults": [{"Event ID": "1"}]})

    assert neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS) == [{"Event ID": "1"}]
    assert requests_mock.call_count == 1


def test_search_events_raises_on_http_error(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture) -> None:
    requests_mock.post(SEARCH_URL, status_code=500, text=f"internal error {BODY_MARKER}")

    with caplog.at_level(logging.DEBUG), pytest.raises(NeonCRMError) as excinfo:
        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert str(excinfo.value) == "events/search failed (status 500)"
    assert BODY_MARKER not in str(excinfo.value)
    assert BODY_MARKER not in caplog.text
    assert "Basic " not in caplog.text
    assert "test_key" not in caplog.text


def test_search_events_raises_on_timeout(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(SEARCH_URL, exc=requests.exceptions.ConnectTimeout)

    with pytest.raises(NeonCRMError) as excinfo:
        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert str(excinfo.value) == "events/search failed (no response)"


def test_search_events_raises_on_non_json(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture) -> None:
    requests_mock.post(SEARCH_URL, status_code=200, text=f"<html>{BODY_MARKER}</html>")

    with caplog.at_level(logging.DEBUG), pytest.raises(NeonCRMError) as excinfo:
        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert str(excinfo.value) == "events/search failed (status 200)"
    assert BODY_MARKER not in caplog.text


@pytest.mark.parametrize(
    "body",
    [{"error": BODY_MARKER}, {"searchResults": None}, [BODY_MARKER]],
)
def test_search_events_raises_without_search_results(
    neon: NeonCRM,
    requests_mock: requests_mock_lib.Mocker,
    caplog: pytest.LogCaptureFixture,
    body: Any,
) -> None:
    requests_mock.post(SEARCH_URL, status_code=200, text=json.dumps(body))

    with caplog.at_level(logging.DEBUG), pytest.raises(NeonCRMError):
        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert BODY_MARKER not in caplog.text


def test_search_events_raises_when_a_later_page_fails(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(
        SEARCH_URL,
        [{"json": _page([{"Event ID": "1"}], 0, 2)}, {"status_code": 503, "text": "busy"}],
    )

    with pytest.raises(NeonCRMError, match="status 503"):
        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)
