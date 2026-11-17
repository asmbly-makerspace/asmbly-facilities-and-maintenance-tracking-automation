import logging
import os
import sys
from typing import Any, Callable
from unittest.mock import patch, MagicMock

import pytest
import requests

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

from common import slack


@patch('common.slack.requests.post')
def test_send_slack_message_success(mock_requests_post):
    """Test successfully sending a message to Slack."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True, "ts": "123.456"}
    mock_requests_post.return_value = mock_response

    # Explicitly test the non-dry-run case
    response = slack.send_slack_message('slack-token', '#general', 'Hello', 'Bot', ':emoji:', dry_run=False)

    assert response['ok'] is True
    assert response['ts'] == "123.456"
    mock_requests_post.assert_called_once()
    assert mock_requests_post.call_args.kwargs['json']['channel'] == 'general'
    assert mock_requests_post.call_args.kwargs['json']['text'] == 'Hello'
    assert 'thread_ts' not in mock_requests_post.call_args.kwargs['json']


@patch('common.slack.requests.post')
def test_send_slack_message_dry_run(mock_requests_post, capsys):
    """Test that dry_run=True prints to console and does not send a request."""
    response = slack.send_slack_message(
        'slack-token',
        '#general',
        'Dry run message',
        'Bot',
        ':emoji:',
        dry_run=True
    )

    assert response['ok'] is True
    assert response['ts'] == "DRY_RUN_TIMESTAMP"

    # Assert that no HTTP request was made
    mock_requests_post.assert_not_called()

    # Assert that the message was printed to stdout
    captured = capsys.readouterr()
    assert "--- DRY RUN MODE ---" in captured.out
    assert "Would send to channel: #general" in captured.out
    assert "Message: Dry run message" in captured.out

def test_slack_state_get_value():
    """Test SlackState.get_value for various scenarios."""
    state = slack.SlackState({
        "block1": {"action1": {"value": "hello"}}
    })
    assert state.get_value("block1", "action1") == "hello"
    assert state.get_value("block1", "action2") is None
    assert state.get_value("block2", "action1") is None

def test_slack_state_get_selected_option_value():
    """Test SlackState.get_selected_option_value for various scenarios."""
    state = slack.SlackState({
        "block1": {"action1": {"selected_option": {"value": "option1"}}}
    })
    assert state.get_selected_option_value("block1", "action1") == "option1"
    assert state.get_selected_option_value("block1", "action2") is None
    assert state.get_selected_option_value("block2", "action1") is None

def test_get_slack_post_url_success():
    """Test successful generation of a Slack permalink."""
    url = slack.get_slack_post_url("https://my.slack.com", "C123", "12345.67890")
    assert url == "https://my.slack.com/archives/C123/p1234567890"

def test_get_slack_post_url_no_workspace_url(caplog, capsys):
    """Test that the function returns None and logs a warning if the workspace URL is missing."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    url = slack.get_slack_post_url(None, "C123", "12345.67890")
    assert url is None
    assert capsys.readouterr().out == ""
    assert any(r.name == "common.slack" and r.levelno == logging.WARNING for r in caplog.records)

def test_get_slack_user_info():
    """Test retrieving user information from Slack."""
    user_id = "U12345"
    api_token = "xoxb-fake-token"

    # 1. Set up the expected JSON that the Slack API would return
    mock_api_response = {
        "ok": True,
        "user": {
            "id": user_id,
            "name": "test.user",
            "real_name": "Test User"
        }
    }

    # 2. Create a mock for the HTTP response object
    mock_response_obj = MagicMock()
    mock_response_obj.json.return_value = mock_api_response
    mock_response_obj.raise_for_status.return_value = None

    # 3. Create a mock for the session object and configure its `get` method
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response_obj

    # 4. Call the function, injecting the mock session
    user_info = slack.get_slack_user_info(api_token, user_id, http_session=mock_session)

    # 5. Assert that the function returned the correct data
    assert user_info["ok"] is True
    assert user_info["user"]["real_name"] == "Test User"

    # 6. Assert that the session's get method was called with the correct arguments
    # CORRECTED: Pass the 'url' as a positional argument to match the actual function call
    mock_session.get.assert_called_once_with(
        "https://slack.com/api/users.info",
        headers={"Authorization": f"Bearer {api_token}"},
        params={"user": user_id},
        timeout=8.0,
    )


def _slack_errors(caplog):
    return [r for r in caplog.records if r.name == "common.slack" and r.levelno == logging.ERROR]


@patch('common.slack.requests.post')
def test_send_slack_message_api_error_logs_error_code_only(mock_requests_post, caplog, capsys):
    """A Slack API error logs the channel and error code, not the whole response or the token."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": False,
        "error": "channel_not_found",
        "response_metadata": {"messages": ["pk_META_MARKER"]},
    }
    mock_requests_post.return_value = mock_response

    response = slack.send_slack_message('xoxb-TOKEN-MARKER', '#general', 'Hello', 'Bot', ':emoji:')

    assert response == {
        "ok": False,
        "error": "channel_not_found",
        "response_metadata": {"messages": ["pk_META_MARKER"]},
    }
    assert capsys.readouterr().out == ""
    errors = _slack_errors(caplog)
    assert len(errors) == 1
    assert "channel_not_found" in errors[0].getMessage()
    assert "general" in errors[0].getMessage()
    assert "pk_META_MARKER" not in caplog.text
    assert "xoxb-TOKEN-MARKER" not in caplog.text


@patch('common.slack.requests.post')
def test_send_slack_message_exception_logs_type_only(mock_requests_post, caplog, capsys):
    """A request failure logs the exception type and returns no exception text."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_requests_post.side_effect = requests.exceptions.ConnectionError("pk_EXC_MARKER")

    response = slack.send_slack_message('xoxb-TOKEN-MARKER', '#general', 'Hello', 'Bot', ':emoji:')

    assert response == {"ok": False, "error": "script_error"}
    assert "pk_EXC_MARKER" not in str(response)
    assert capsys.readouterr().out == ""
    errors = _slack_errors(caplog)
    assert len(errors) == 1
    assert "ConnectionError" in errors[0].getMessage()
    assert "general" in errors[0].getMessage()
    assert "pk_EXC_MARKER" not in caplog.text
    assert "xoxb-TOKEN-MARKER" not in caplog.text


@patch('common.slack.requests.post')
def test_send_slack_message_api_error_invalid_code_not_logged(mock_requests_post, caplog, capsys):
    """A Slack 'error' that doesn't look like an error code is replaced in the log."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": False, "error": "pk_ERR_MARKER Jane jane@example.com"}
    mock_requests_post.return_value = mock_response

    response = slack.send_slack_message('xoxb-TOKEN-MARKER', '#general', 'Hello', 'Bot', ':emoji:')

    assert response == {"ok": False, "error": "pk_ERR_MARKER Jane jane@example.com"}
    assert capsys.readouterr().out == ""
    errors = _slack_errors(caplog)
    assert len(errors) == 1
    assert "<invalid>" in errors[0].getMessage()
    assert "pk_ERR_MARKER" not in caplog.text
    assert "jane@example.com" not in caplog.text


def test_slack_error_for_log_rejects_trailing_newline():
    """A Slack error code with a trailing newline is not a valid code and is replaced."""
    assert slack._slack_error_for_log({"error": "channel_not_found\n"}) == "<invalid>"
    assert slack._slack_error_for_log({"error": "channel_not_found"}) == "channel_not_found"
    assert slack._slack_error_for_log({"ok": False}) is None


@patch('common.slack.requests.post')
def test_send_slack_message_passes_timeout(mock_requests_post):
    """chat.postMessage is sent with the 8-second timeout."""
    mock_requests_post.return_value.json.return_value = {"ok": True, "ts": "1.2"}

    slack.send_slack_message('xoxb-TOKEN-MARKER', '#general', 'Hello', 'Bot', ':emoji:')

    assert slack.DEFAULT_TIMEOUT_SECONDS == 8.0
    assert mock_requests_post.call_args.kwargs['timeout'] == 8.0


@patch('common.slack.requests.post')
def test_send_slack_message_timeout_returns_script_error(mock_requests_post, caplog, capsys):
    """A timeout is handled like any other failure: logged by class, script_error returned."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_requests_post.side_effect = requests.exceptions.ReadTimeout("pk_URL_MARKER read timed out")

    response = slack.send_slack_message('xoxb-TOKEN-MARKER', '#general', 'Hello', 'Bot', ':emoji:')

    assert response == {"ok": False, "error": "script_error"}
    assert capsys.readouterr().out == ""
    errors = _slack_errors(caplog)
    assert len(errors) == 1
    assert "ReadTimeout" in errors[0].getMessage()
    assert "chat.postMessage" in errors[0].getMessage()
    assert "pk_URL_MARKER" not in caplog.text
    assert "xoxb-TOKEN-MARKER" not in caplog.text


def test_get_slack_user_info_timeout_logs_and_reraises(caplog):
    """A users.info timeout is logged with the endpoint and class, then raised unchanged."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    err = requests.exceptions.ReadTimeout("HTTPSConnectionPool(host='slack.com'): pk_URL_MARKER")
    mock_session = MagicMock()
    mock_session.get.side_effect = err

    try:
        slack.get_slack_user_info('xoxb-TOKEN-MARKER', 'U123', http_session=mock_session)
    except requests.exceptions.ReadTimeout as raised:
        assert raised is err
    else:
        raise AssertionError("ReadTimeout was not raised")

    errors = _slack_errors(caplog)
    assert [r.getMessage() for r in errors] == ["Slack users.info failed: ReadTimeout"]
    assert "pk_URL_MARKER" not in caplog.text
    assert "xoxb-TOKEN-MARKER" not in caplog.text


def test_get_slack_user_info_http_error_logs_and_reraises(caplog):
    """An HTTP error from users.info is logged by class and re-raised."""
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_session = MagicMock()
    mock_session.get.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError("pk_URL_MARKER")

    try:
        slack.get_slack_user_info('xoxb-TOKEN-MARKER', 'U123', http_session=mock_session)
    except requests.exceptions.HTTPError:
        pass
    else:
        raise AssertionError("HTTPError was not raised")

    assert [r.getMessage() for r in _slack_errors(caplog)] == ["Slack users.info failed: HTTPError"]
    assert "pk_URL_MARKER" not in caplog.text


# --- get_bot_id and get_channel_message ---

TOKEN = 'xoxb-TOKEN-MARKER'


def _slack_answer(body: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


def _raises_slack_request_error(func: Callable[..., Any], *args: str) -> slack.SlackRequestError:
    try:
        func(*args)
    except slack.SlackRequestError as raised:
        return raised
    raise AssertionError("SlackRequestError was not raised")


@patch('common.slack.requests.get')
def test_get_bot_id_returns_bot_id(mock_get: MagicMock) -> None:
    mock_get.return_value = _slack_answer({"ok": True, "bot_id": "B1", "user_id": "U1"})

    assert slack.get_bot_id(TOKEN) == "B1"

    assert mock_get.call_args.args[0] == "https://slack.com/api/auth.test"
    assert mock_get.call_args.kwargs['headers'] == {"Authorization": f"Bearer {TOKEN}"}
    assert mock_get.call_args.kwargs['timeout'] == slack.DEFAULT_TIMEOUT_SECONDS


@patch('common.slack.requests.get')
def test_get_bot_id_without_bot_id_raises(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.return_value = _slack_answer({"ok": True, "user_id": "U1"})

    raised = _raises_slack_request_error(slack.get_bot_id, TOKEN)

    assert str(raised) == "auth.test returned no bot_id"
    assert TOKEN not in caplog.text


@patch('common.slack.requests.get')
def test_get_bot_id_error_logs_code_only(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.return_value = _slack_answer({"ok": False, "error": "invalid_auth"})

    raised = _raises_slack_request_error(slack.get_bot_id, TOKEN)

    assert [r.getMessage() for r in _slack_errors(caplog)] == [
        "Slack auth.test failed: HTTP 200, error invalid_auth"
    ]
    assert str(raised) == "Slack auth.test failed (invalid_auth)"
    assert TOKEN not in caplog.text
    assert TOKEN not in str(raised)


@patch('common.slack.requests.get')
def test_get_channel_message_returns_exact_message(mock_get: MagicMock) -> None:
    message = {"type": "message", "ts": "1700000000.000100", "bot_id": "B1", "text": "hi"}
    mock_get.return_value = _slack_answer({"ok": True, "messages": [message], "has_more": False})

    assert slack.get_channel_message(TOKEN, "C0CJAK1D725", "1700000000.000100") == message

    assert mock_get.call_args.args[0] == "https://slack.com/api/conversations.history"
    assert mock_get.call_args.kwargs['headers'] == {"Authorization": f"Bearer {TOKEN}"}
    assert mock_get.call_args.kwargs['params'] == {
        "channel": "C0CJAK1D725",
        "latest": "1700000000.000100",
        "oldest": "1700000000.000100",
        "inclusive": "true",
        "limit": 1,
    }
    assert mock_get.call_args.kwargs['timeout'] == slack.DEFAULT_TIMEOUT_SECONDS


@patch('common.slack.requests.get')
def test_get_channel_message_thread_parent_is_returned(mock_get: MagicMock) -> None:
    """A reminder that has a description reply is a thread parent: its thread_ts equals its ts."""
    message = {"ts": "1700000000.000100", "thread_ts": "1700000000.000100", "reply_count": 1}
    mock_get.return_value = _slack_answer({"ok": True, "messages": [message]})

    assert slack.get_channel_message(TOKEN, "C1", "1700000000.000100") == message


@patch('common.slack.requests.get')
def test_get_channel_message_other_ts_returns_none(mock_get: MagicMock) -> None:
    """A message at another ts is never returned, whatever Slack answers."""
    mock_get.return_value = _slack_answer({"ok": True, "messages": [{"ts": "1699999999.000001"}]})

    assert slack.get_channel_message(TOKEN, "C1", "1700000000.000100") is None


@patch('common.slack.requests.get')
def test_get_channel_message_thread_broadcast_returns_none(mock_get: MagicMock) -> None:
    """A reply also sent to the channel shows in history but is not a top-level message."""
    mock_get.return_value = _slack_answer({"ok": True, "messages": [
        {"ts": "1700000000.000200", "thread_ts": "1700000000.000100", "subtype": "thread_broadcast"}
    ]})

    assert slack.get_channel_message(TOKEN, "C1", "1700000000.000200") is None


@patch('common.slack.requests.get')
def test_get_channel_message_no_messages_returns_none(mock_get: MagicMock) -> None:
    mock_get.return_value = _slack_answer({"ok": True, "messages": []})

    assert slack.get_channel_message(TOKEN, "C1", "1700000000.000100") is None


@patch('common.slack.requests.get')
def test_get_channel_message_api_error_raises_and_logs_code_only(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.return_value = _slack_answer({"ok": False, "error": "not_in_channel", "pk": "BODY_MARKER"})

    raised = _raises_slack_request_error(slack.get_channel_message, TOKEN, "C1", "1700000000.000100")

    assert [r.getMessage() for r in _slack_errors(caplog)] == [
        "Slack conversations.history failed: HTTP 200, error not_in_channel"
    ]
    assert str(raised) == "Slack conversations.history failed (not_in_channel)"
    for marker in (TOKEN, "BODY_MARKER", "latest="):
        assert marker not in caplog.text
        assert marker not in str(raised)


@patch('common.slack.requests.get')
def test_get_channel_message_rate_limited_keeps_status_and_code(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.return_value = _slack_answer({"ok": False, "error": "ratelimited"}, status_code=429)

    raised = _raises_slack_request_error(slack.get_channel_message, TOKEN, "C1", "1700000000.000100")

    assert [r.getMessage() for r in _slack_errors(caplog)] == [
        "Slack conversations.history failed: HTTP 429, error ratelimited"
    ]
    assert str(raised) == "Slack conversations.history failed (ratelimited)"


@patch('common.slack.requests.get')
def test_get_channel_message_body_not_json_raises(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    response = _slack_answer(None, status_code=502)
    response.json.side_effect = ValueError("BODY_MARKER")
    mock_get.return_value = response

    raised = _raises_slack_request_error(slack.get_channel_message, TOKEN, "C1", "1700000000.000100")

    assert [r.getMessage() for r in _slack_errors(caplog)] == [
        "Slack conversations.history returned a body that is not a JSON object (HTTP 502)"
    ]
    assert "BODY_MARKER" not in caplog.text
    assert "BODY_MARKER" not in str(raised)


@patch('common.slack.requests.get')
def test_get_channel_message_timeout_raises(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.side_effect = requests.exceptions.ReadTimeout("https://slack.com/api?pk_URL_MARKER")

    raised = _raises_slack_request_error(slack.get_channel_message, TOKEN, "C1", "1700000000.000100")

    assert [r.getMessage() for r in _slack_errors(caplog)] == [
        "Slack conversations.history failed: ReadTimeout"
    ]
    assert str(raised) == "Slack conversations.history failed (ReadTimeout)"
    assert raised.__cause__ is None
    assert "pk_URL_MARKER" not in caplog.text
    assert "pk_URL_MARKER" not in str(raised)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("body", [
    {"ok": True},
    {"ok": True, "messages": "not a list"},
    {"ok": True, "messages": ["not a dict"]},
    {"ok": True, "messages": [{"text": "no ts"}]},
])
@patch('common.slack.requests.get')
def test_get_channel_message_odd_messages_return_none(mock_get: MagicMock, body: dict[str, Any]) -> None:
    mock_get.return_value = _slack_answer(body)

    assert slack.get_channel_message(TOKEN, "C1", "1700000000.000100") is None


@patch('common.slack.requests.get')
def test_get_channel_message_json_not_an_object_raises(mock_get: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="common.slack")
    mock_get.return_value = _slack_answer(["BODY_MARKER"])

    raised = _raises_slack_request_error(slack.get_channel_message, TOKEN, "C1", "1700000000.000100")

    assert str(raised) == "Slack conversations.history returned an unreadable answer"
    assert "BODY_MARKER" not in caplog.text
