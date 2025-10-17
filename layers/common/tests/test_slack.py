import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

from common import slack


@patch('common.slack.requests.post')
def test_send_slack_message_success(mock_requests_post):
    """Test successfully sending a message to Slack."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True, "ts": "123.456"}
    mock_requests_post.return_value = mock_response

    response = slack.send_slack_message('slack-token', '#general', 'Hello', 'Bot', ':emoji:')

    assert response['ok'] is True
    assert response['ts'] == "123.456"
    mock_requests_post.assert_called_once()
    assert mock_requests_post.call_args.kwargs['json']['channel'] == 'general'
    assert mock_requests_post.call_args.kwargs['json']['text'] == 'Hello'


def test_send_slack_message_dry_run(capsys):
    """Test that DRY_RUN mode prints to console instead of sending."""
    with patch('common.slack.DRY_RUN', True):
        response = slack.send_slack_message('slack-token', '#general', 'Dry run message', 'Bot', ':emoji:')

    assert response['ok'] is True
    assert response['ts'] == "DRY_RUN_TIMESTAMP"
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
        params={"user": user_id}
    )