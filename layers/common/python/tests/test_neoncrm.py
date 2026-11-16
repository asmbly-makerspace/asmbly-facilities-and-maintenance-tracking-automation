import unittest
from unittest.mock import patch, Mock
import base64
import json
import logging
import os
import pathlib
import subprocess
import sys
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
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload, timeout=8.0)

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
        mock_patch.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload, timeout=8.0)

    @patch('common.neoncrm.requests.patch')
    def test_update_account_custom_field_api_error(self, mock_patch):
        """A failed update raises NeonCRMError instead of passing for a success."""
        mock_patch.side_effect = requests.exceptions.RequestException("API Error")

        with self.assertRaises(NeonCRMError):
            self.client.update_account_custom_field("12345", "10", "New Value")


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


def test_search_events_stops_at_the_callers_page_cap(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture) -> None:
    requests_mock.post(SEARCH_URL, json=_page([{"Event ID": "x"}], 0, 10_000))

    with caplog.at_level(logging.WARNING):
        results = neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS, max_pages=3)

    assert requests_mock.call_count == 3
    assert len(results) == 3
    assert "stopped at 3 of 10000 pages" in caplog.text


def test_search_events_passes_the_timeout_to_each_request(neon: NeonCRM, requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(SEARCH_URL, [{"json": _page([{"Event ID": "1"}], 0, 2)}, {"json": _page([{"Event ID": "2"}], 1, 2)}])

    neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS, timeout=4.0)

    assert [r.timeout for r in requests_mock.request_history] == [4.0, 4.0]


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


# --- Logging setup, account-call logging and timeouts ---

LAYER_PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
MEMBER_EMAIL = "pk_member@example.com"


def _import_in_fresh_interpreter(module: str) -> list[str]:
    """Imports a layer module in a new Python with the root logger at WARNING, and
    returns the root level and the module logger's level after the import."""
    code = (
        "import logging, sys\n"
        "logging.getLogger().setLevel(logging.WARNING)\n"
        f"import {module}\n"
        f"print(logging.getLogger().level, logging.getLogger({module!r}).level)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(LAYER_PYTHON_DIR)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    return result.stdout.split()


def test_import_sets_no_log_level() -> None:
    """Importing the Neon helper leaves the root logger alone and sets no level of its own."""
    root_level, module_level = _import_in_fresh_interpreter("common.neoncrm")

    assert int(root_level) == logging.WARNING
    assert int(module_level) == logging.NOTSET


def _neon_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "common.neoncrm"]


@pytest.mark.parametrize(
    "outcome",
    ["found", "not_found", "connection_error"],
)
def test_get_account_by_email_logs_no_email(neon: NeonCRM, caplog: pytest.LogCaptureFixture, outcome: str) -> None:
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    with patch("common.neoncrm.requests.post") as mock_post:
        if outcome == "connection_error":
            mock_post.side_effect = requests.exceptions.ConnectionError(f"search for {MEMBER_EMAIL} failed")
        else:
            results = [{"Account ID": "12345"}] if outcome == "found" else []
            mock_post.return_value = Mock(**{"json.return_value": {"searchResults": results}})

        neon.get_account_by_email(MEMBER_EMAIL)

    assert _neon_records(caplog)
    assert MEMBER_EMAIL not in caplog.text
    assert "pk_member" not in caplog.text


def test_get_account_by_email_http_error_logs_status(neon: NeonCRM, caplog: pytest.LogCaptureFixture) -> None:
    """A failed search logs the operation, the error class and the status, not Neon's body."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    response = Mock(status_code=401, text=f"pk_NEON_BODY {MEMBER_EMAIL}")
    error = requests.exceptions.HTTPError(f"401 Client Error for {MEMBER_EMAIL}", response=response)
    with patch("common.neoncrm.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.side_effect = error

        assert neon.get_account_by_email(MEMBER_EMAIL) is None

    errors = [r.getMessage() for r in _neon_records(caplog) if r.levelno == logging.ERROR]
    assert errors == ["Error searching for NeonCRM account: HTTPError (status 401)"]
    assert "pk_NEON_BODY" not in caplog.text
    assert MEMBER_EMAIL not in caplog.text


def test_update_account_custom_field_success_logs_ids(neon: NeonCRM, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    with patch("common.neoncrm.requests.patch") as mock_patch:
        mock_patch.return_value.raise_for_status.return_value = None

        neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert [r.getMessage() for r in _neon_records(caplog)] == ["Updated custom field 77 for NeonCRM account 12345"]
    assert "2026-10-17" not in caplog.text


ACCOUNT_URL = "https://api.neoncrm.com/v2/accounts/12345"


def _update_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in _neon_records(caplog) if r.levelno == logging.ERROR]


def test_update_account_custom_field_rejected_logs_neon_errors_and_raises(
    neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture
) -> None:
    """A 400 logs Neon's error codes and messages, and raises with the status only."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    requests_mock.patch(ACCOUNT_URL, status_code=400, json=[
        {"code": "400", "message": "Date of birth is invalid."},
        {"code": "INVALID_FIELD", "message": "Custom field 77 is read only."},
    ])

    with pytest.raises(NeonCRMError) as excinfo:
        neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert str(excinfo.value) == "accounts/12345 update failed (status 400)"
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
    assert _update_errors(caplog) == [
        "Error updating NeonCRM account 12345: HTTPError (status 400): "
        "400: Date of birth is invalid.; INVALID_FIELD: Custom field 77 is read only."
    ]


def test_update_account_custom_field_masks_personal_data_in_neon_messages(
    neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture
) -> None:
    """Emails, phone numbers and dates that Neon quotes back are masked in the log."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    requests_mock.patch(ACCOUNT_URL, status_code=400, json=[
        {"code": "400", "message": f"Email {MEMBER_EMAIL} is already used"},
        {"code": "400", "message": "Phone 512-555-0142 is invalid"},
        {"code": "400", "message": "Date of birth 0100-01-02 is out of range"},
    ])

    with pytest.raises(NeonCRMError):
        neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert _update_errors(caplog) == [
        "Error updating NeonCRM account 12345: HTTPError (status 400): "
        "400: Email <email> is already used; 400: Phone <number> is invalid; "
        "400: Date of birth <number> is out of range"
    ]
    for leaked in (MEMBER_EMAIL, "512-555-0142", "0100-01-02", "2026-10-17"):
        assert leaked not in caplog.text


def test_update_account_custom_field_truncates_and_caps_neon_errors(
    neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture
) -> None:
    """A long message is cut to 200 characters, on one line; only the first five errors are logged."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    long_message = "x" * 150 + "\nFORGED LOG LINE " + "y" * 100 + BODY_MARKER
    requests_mock.patch(ACCOUNT_URL, status_code=400, json=[{"code": "E1", "message": long_message}] + [
        {"code": f"E{n}", "message": "m"} for n in range(2, 9)
    ])

    with pytest.raises(NeonCRMError):
        neon.update_account_custom_field("12345", "77", "2026-10-17")

    [error] = _update_errors(caplog)
    assert BODY_MARKER not in error
    assert "\n" not in error
    assert "E1: " + ("x" * 150 + " FORGED LOG LINE " + "y" * 100)[:200] + "..." in error
    assert error.endswith("E5: m; and 3 more")
    assert "E6" not in error


@pytest.mark.parametrize(
    ("body", "summary"),
    [
        ({"text": f"<html>{BODY_MARKER}</html>"}, "body is not JSON"),
        ({"json": {"code": f"{BODY_MARKER} {MEMBER_EMAIL}", "message": 7}}, "<invalid>"),
        ({"json": [BODY_MARKER, {"message": None}]}, "<invalid>; <invalid>"),
        ({"json": []}, "no errors listed"),
    ],
)
def test_update_account_custom_field_unexpected_error_body_is_not_logged_raw(
    neon: NeonCRM, requests_mock: requests_mock_lib.Mocker, caplog: pytest.LogCaptureFixture,
    body: dict[str, Any], summary: str,
) -> None:
    """A body that isn't Neon's error list is summarized, never logged as it came."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    requests_mock.patch(ACCOUNT_URL, status_code=500, **body)

    with pytest.raises(NeonCRMError, match=r"^accounts/12345 update failed \(status 500\)$"):
        neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert _update_errors(caplog) == [f"Error updating NeonCRM account 12345: HTTPError (status 500): {summary}"]
    assert BODY_MARKER not in caplog.text
    assert MEMBER_EMAIL not in caplog.text


def test_update_account_custom_field_failure_logs_no_exception_text(neon: NeonCRM, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    response = Mock(status_code=400, text="pk_NEON_BODY jane@example.com")
    response.json.return_value = [{"code": "400", "message": "Invalid"}]
    error = requests.exceptions.HTTPError("400 Client Error: pk_HTTP_TEXT", response=response)
    with patch("common.neoncrm.requests.patch") as mock_patch:
        mock_patch.return_value.raise_for_status.side_effect = error

        with pytest.raises(NeonCRMError):
            neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert _update_errors(caplog) == ["Error updating NeonCRM account 12345: HTTPError (status 400): 400: Invalid"]
    assert "pk_NEON_BODY" not in caplog.text
    assert "jane@example.com" not in caplog.text
    assert "pk_HTTP_TEXT" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [requests.exceptions.ConnectionError("pk_URL"), requests.exceptions.ReadTimeout("pk_URL")],
)
def test_update_account_custom_field_no_response_logs_type_and_raises(
    neon: NeonCRM, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """A dropped connection or a timeout is a failed update too: logged by class, raised."""
    caplog.set_level(logging.DEBUG, logger="common.neoncrm")
    with patch("common.neoncrm.requests.patch") as mock_patch:
        mock_patch.side_effect = error

        with pytest.raises(NeonCRMError, match=r"^accounts/12345 update failed \(status no response\)$"):
            neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert _update_errors(caplog) == [
        f"Error updating NeonCRM account 12345: {type(error).__name__} (status no response): no body"
    ]
    assert "pk_URL" not in caplog.text


def test_account_calls_pass_timeout(neon: NeonCRM) -> None:
    with patch("common.neoncrm.requests.post") as mock_post, patch("common.neoncrm.requests.patch") as mock_patch:
        mock_post.return_value = Mock(**{"json.return_value": {"searchResults": []}})

        neon.get_account_by_email(MEMBER_EMAIL)
        neon.update_account_custom_field("12345", "77", "2026-10-17")

    assert mock_post.call_args.kwargs["timeout"] == 8.0
    assert mock_patch.call_args.kwargs["timeout"] == 8.0


def test_search_events_keeps_ten_second_timeout(neon: NeonCRM) -> None:
    with patch("common.neoncrm.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, **{"json.return_value": {"searchResults": []}})

        neon.search_events(SEARCH_FIELDS, OUTPUT_FIELDS)

    assert mock_post.call_args.kwargs["timeout"] == 10.0
