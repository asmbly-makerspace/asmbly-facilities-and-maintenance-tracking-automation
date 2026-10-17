import json
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock, call

from functions.problem_report.slack_reaction_webhook import lambda_function

LAMBDA_FUNCTION_PATH = "functions.problem_report.slack_reaction_webhook.lambda_function"


class TestProblemReportReactionWebhook(TestCase):

    def setUp(self):
        """Set up common test data."""
        self.fake_reaction_map = {
            "white_check_mark": {
                "clickup_status": "Closed",
                "discourse_post_message": "This has been resolved!",
                "discourse_mark_solution": True
            },
            "loading": {
                "clickup_status": "In Progress",
                "discourse_post_message": "Work has started."
            }
        }
        self.base_event = {
            "body": json.dumps({
                "event": {
                    "type": "reaction_added", "reaction": "white_check_mark",
                    "item": {"channel": "C123", "ts": "12345.678"}
                }
            })
        }

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.discourse")
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_success_full_flow(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup, mock_discourse):
        # --- Mocks Setup ---
        # SSM
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }

        # Secrets
        mock_aws.get_secret.side_effect = [
            'fake-clickup-token', 'fake-discourse-key', 'fake-discourse-user'
        ]

        # Base reaction processing
        discourse_link = "https://yo.asmbly.org/t/slug/123/1"
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "white_check_mark",
            "message_text": f"A problem occurred!\nClickUp: https://app.clickup.com/t/abcde123\nDiscourse: {discourse_link}"
        }

        # Discourse parsing and actions
        mock_discourse.parse_discourse_url.return_value = {
            "base_url": "https://yo.asmbly.org", "topic_id": "123", "post_number": "1"
        }
        mock_discourse.post_reply.return_value = {"id": 987} # New post ID

        # --- Execute ---
        event_body = json.loads(self.base_event['body'])
        response = lambda_function.lambda_handler(event_body, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        mock_reaction_processing.process_base_reaction.assert_called_once()

        # ClickUp update - The body is now the raw event, not json.loads(event['body'])
        mock_clickup.update_task.assert_called_once_with(
            'fake-clickup-token', 'abcde123', {"status": "Closed"}
        )

        # Discourse update
        mock_discourse.parse_discourse_url.assert_called_once()
        mock_discourse.post_reply.assert_called_once_with(
            base_url="https://yo.asmbly.org",
            topic_id="123",
            post_number="1",
            message="This has been resolved!",
            api_key='fake-discourse-key',
            api_username='fake-discourse-user'
        )
        mock_discourse.mark_solution.assert_called_once_with(
            base_url="https://yo.asmbly.org",
            post_id=987,
            api_key='fake-discourse-key',
            api_username='fake-discourse-user'
        )

        # Secrets were fetched
        mock_aws.get_secret.assert_has_calls([
            call('fake-clickup-secret', 'CLICKUP_API_TOKEN'),
            call('fake-discourse-secret', 'DISCOURSE_FACILITIES_BOT_API_KEY'),
            call('fake-discourse-secret', 'DISCOURSE_FACILITIES_BOT_API_USERNAME')
        ])

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.discourse")
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_success_no_discourse_link(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup, mock_discourse):
        # --- Mocks Setup ---
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }
        mock_aws.get_secret.return_value = 'fake-clickup-token'
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "white_check_mark",
            "message_text": "A problem occurred!\nClickUp: https://app.clickup.com/t/abcde123"
        }
        mock_discourse.parse_discourse_url.return_value = None

        # --- Execute ---
        event_body = json.loads(self.base_event['body'])
        response = lambda_function.lambda_handler(event_body, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        mock_clickup.update_task.assert_called_once()
        mock_discourse.parse_discourse_url.assert_called_once()
        # Ensure no Discourse actions were taken
        mock_discourse.post_reply.assert_not_called()
        mock_discourse.mark_solution.assert_not_called()

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_ignored_reaction(self, mock_boto3_client, mock_reaction_processing):
        # --- Mocks Setup ---
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "ignored", "reason": "Irrelevant reaction"
        }

        # --- Execute ---
        event_body = json.loads(self.base_event['body'])
        response = lambda_function.lambda_handler(event_body, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        # Ensure no further processing happened
        # (The mocks for clickup, aws, discourse are not patched, so a call would raise an error)

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.discourse")
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_result_log_omits_message_text(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup, mock_discourse):
        """The result log line carries the task ID, not the Slack message's contact details."""
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }
        mock_aws.get_secret.side_effect = [
            'fake-clickup-token', 'fake-discourse-key', 'fake-discourse-user'
        ]
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "white_check_mark",
            "message_text": (
                "A problem occurred!\nContact Details: Jane Doe 512-555-0142\n"
                "ClickUp: https://app.clickup.com/t/abcde123\n"
                "Discourse: https://yo.asmbly.org/t/slug/123/1"
            ),
        }
        mock_discourse.parse_discourse_url.return_value = {
            "base_url": "https://yo.asmbly.org", "topic_id": "123", "post_number": "1"
        }
        mock_discourse.post_reply.return_value = {"id": 987}

        event_body = json.loads(self.base_event['body'])
        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        self.assertEqual(response["statusCode"], 200)
        output = "\n".join(logs.output)
        self.assertNotIn("Jane Doe", output)
        self.assertNotIn("512-555-0142", output)
        results = [r.getMessage() for r in logs.records if "processing result" in r.getMessage()]
        self.assertEqual(len(results), 1, results)
        self.assertIn("abcde123", results[0])
        self.assertIn("white_check_mark", results[0])

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_ignored_result_log_has_status_and_reason(self, mock_boto3_client, mock_reaction_processing):
        """An ignored reaction logs its status and reason."""
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "ignored", "reason": "No ClickUp task URL found in the message."
        }

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(json.loads(self.base_event['body']), None)

        self.assertEqual(response["statusCode"], 200)
        results = [r.getMessage() for r in logs.records if "processing result" in r.getMessage()]
        self.assertEqual(len(results), 1, results)
        self.assertIn("ignored", results[0])
        self.assertIn("No ClickUp task URL found in the message.", results[0])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_slack_challenge(self, mock_boto3_client):
        # The router passes the body directly
        event_body = {"challenge": "test_challenge_string"}
        response = lambda_function.lambda_handler(event_body, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge_string", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_missing_env_var(self, mock_boto3_client):
        # Use an empty patch.dict to ensure the env var is not set
        with patch.dict(os.environ, {}, clear=True):
            # The lambda now receives the raw body, not the full API Gateway event
            event = json.loads(self.base_event['body'])
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("REACTION_MAP_PARAMETER_NAME environment variable not set", response["body"])

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_general_exception(self, mock_boto3_client, mock_reaction_processing):
        # --- Mocks Setup ---
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': json.dumps(self.fake_reaction_map)}
        }
        # Make a downstream function raise an error
        mock_reaction_processing.process_base_reaction.side_effect = Exception("Something broke!")

        # --- Execute ---
        event = json.loads(self.base_event['body'])
        response = lambda_function.lambda_handler(event, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Internal server error: Something broke!", response["body"])

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_received_event_log_omits_token_and_body(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup):
        """The 'Received event' line carries the event's IDs, never Slack's token or the whole event."""
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {'Parameter': {'Value': json.dumps(self.fake_reaction_map)}}
        mock_aws.get_secret.return_value = 'fake-clickup-token'
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "ignored", "reason": "No ClickUp task URL found in the message.",
        }
        event_body = {
            "token": "pk_VERIFY_MARKER",
            "team_id": "T999",
            "event_id": "Ev123ABC",
            "type": "event_callback",
            "event": {
                "type": "reaction_added", "reaction": "white_check_mark", "user": "U555",
                "item": {"type": "message", "channel": "C123", "ts": "123.456"},
            },
        }

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(event_body, None)

        self.assertEqual(response["statusCode"], 200)
        output = "\n".join(logs.output)
        self.assertNotIn("pk_VERIFY_MARKER", output)
        self.assertNotIn("T999", output)
        received = [r.getMessage() for r in logs.records if r.getMessage().startswith("Received event")]
        self.assertEqual(received, [
            "Received event: type=reaction_added reaction=white_check_mark channel=C123 ts=123.456 event_id=Ev123ABC"
        ])

    def test_received_event_log_handles_non_dict_shapes(self):
        """The log line never raises before the handler's try, whatever shape the event has."""
        with self.assertLogs(level="INFO") as logs:
            lambda_function._log_received_event("pk_STRING_MARKER")
            lambda_function._log_received_event({"event": "not-a-dict", "token": "pk_VERIFY_MARKER"})
            lambda_function._log_received_event({"event": {"type": "reaction_added", "item": ["x"]}})

        self.assertEqual([r.getMessage() for r in logs.records], [
            "Received event: not a dict",
            "Received event: type=None reaction=None channel=None ts=None event_id=None",
            "Received event: type=reaction_added reaction=None channel=None ts=None event_id=None",
        ])
        self.assertNotIn("pk_", "\n".join(logs.output))

    @patch.dict(os.environ, {
        "REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param",
        "SLACK_MAINTENANCE_BOT_SECRET_NAME": "fake-slack-secret",
        "CLICKUP_SECRET_NAME": "fake-clickup-secret",
        "DISCOURSE_SECRET_NAME": "fake-discourse-secret"
    })
    @patch(f"{LAMBDA_FUNCTION_PATH}.discourse")
    @patch(f"{LAMBDA_FUNCTION_PATH}.clickup")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    @patch(f"{LAMBDA_FUNCTION_PATH}.reaction_processing")
    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_discourse_reply_log_has_post_id_only(self, mock_boto3_client, mock_reaction_processing, mock_aws, mock_clickup, mock_discourse):
        """The Discourse reply is logged by its post ID, not its text or the bot's user record."""
        mock_ssm = MagicMock()
        mock_boto3_client.return_value = mock_ssm
        mock_ssm.get_parameter.return_value = {'Parameter': {'Value': json.dumps(self.fake_reaction_map)}}
        mock_aws.get_secret.side_effect = ['fake-clickup-token', 'fake-discourse-key', 'fake-discourse-user']
        mock_reaction_processing.process_base_reaction.return_value = {
            "status": "success",
            "task_id": "abcde123",
            "reaction": "white_check_mark",
            "message_text": "ClickUp: https://app.clickup.com/t/abcde123\nDiscourse: https://yo.asmbly.org/t/slug/123/1",
        }
        mock_discourse.parse_discourse_url.return_value = {
            "base_url": "https://yo.asmbly.org", "topic_id": "123", "post_number": "1"
        }
        mock_discourse.post_reply.return_value = {"id": 987, "raw": "pk_REPLY_MARKER", "username": "facilities-bot"}

        with self.assertLogs(level="INFO") as logs:
            response = lambda_function.lambda_handler(json.loads(self.base_event['body']), None)

        self.assertEqual(response["statusCode"], 200)
        output = "\n".join(logs.output)
        self.assertNotIn("pk_REPLY_MARKER", output)
        self.assertNotIn("facilities-bot", output)
        posted = [r.getMessage() for r in logs.records if r.getMessage().startswith("Discourse reply posted")]
        self.assertEqual(posted, ["Discourse reply posted: post_id=987"])
        mock_discourse.mark_solution.assert_called_once_with(
            base_url="https://yo.asmbly.org",
            post_id=987,
            api_key='fake-discourse-key',
            api_username='fake-discourse-user'
        )
