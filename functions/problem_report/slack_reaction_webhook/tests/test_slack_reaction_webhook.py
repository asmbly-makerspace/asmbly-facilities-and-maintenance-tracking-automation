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

    @patch.dict(os.environ, {"REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param"})
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
        response = lambda_function.lambda_handler(self.base_event, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        mock_reaction_processing.process_base_reaction.assert_called_once()

        # ClickUp update
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
            call('clickup/api/token', 'CLICKUP_API_TOKEN'),
            call('prod/discourse-facilities-bot', 'DISCOURSE_FACILITIES_BOT_API_KEY'),
            call('prod/discourse-facilities-bot', 'DISCOURSE_FACILITIES_BOT_API_USERNAME')
        ])

    @patch.dict(os.environ, {"REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param"})
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
        response = lambda_function.lambda_handler(self.base_event, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        mock_clickup.update_task.assert_called_once()
        mock_discourse.parse_discourse_url.assert_called_once()
        # Ensure no Discourse actions were taken
        mock_discourse.post_reply.assert_not_called()
        mock_discourse.mark_solution.assert_not_called()

    @patch.dict(os.environ, {"REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param"})
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
        response = lambda_function.lambda_handler(self.base_event, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 200)
        # Ensure no further processing happened
        # (The mocks for clickup, aws, discourse are not patched, so a call would raise an error)

    def test_handler_slack_challenge(self):
        event = {"body": json.dumps({"challenge": "test_challenge_string"})}
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("test_challenge_string", response["body"])

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    def test_handler_missing_env_var(self, mock_boto3_client):
        # Use an empty patch.dict to ensure the env var is not set
        with patch.dict(os.environ, {}, clear=True):
            response = lambda_function.lambda_handler(self.base_event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("REACTION_MAP_PARAMETER_NAME environment variable not set", response["body"])

    @patch.dict(os.environ, {"REACTION_MAP_PARAMETER_NAME": "/fake/ssm/param"})
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
        response = lambda_function.lambda_handler(self.base_event, None)

        # --- Assertions ---
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("Internal server error: Something broke!", response["body"])