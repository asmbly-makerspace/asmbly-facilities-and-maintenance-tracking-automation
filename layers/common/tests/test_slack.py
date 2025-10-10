import os
import sys
from unittest.mock import patch

import pytest

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

from common import slack


def test_send_slack_message_success(requests_mock):
    """Test successfully sending a message to Slack."""
    requests_mock.post("https://slack.com/api/chat.postMessage", json={"ok": True, "ts": "123.456"})

    response = slack.send_slack_message('slack-token', '#general', 'Hello', 'Bot', ':emoji:')

    assert response['ok'] is True
    assert response['ts'] == "123.456"
    sent_payload = requests_mock.last_request.json()
    assert sent_payload['channel'] == 'general'
    assert sent_payload['text'] == 'Hello'


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

def test_get_slack_user_info(requests_mock):
    """Test retrieving user information from Slack."""
    user_id = "U12345"
    api_token = "xoxb-fake-token"
    mock_response = {
        "ok": True,
        "user": {
            "id": user_id,
            "name": "test.user",
            "real_name": "Test User"
        }
    }
    requests_mock.get(f"https://slack.com/api/users.info?user={user_id}", json=mock_response)

    user_info = slack.get_slack_user_info(api_token, user_id)

    assert user_info["ok"] is True
    assert user_info["user"]["real_name"] == "Test User"
