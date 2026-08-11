import base64
import os
from unittest import TestCase
from unittest.mock import patch, MagicMock

from functions.networking.dynamic_dns_update import lambda_function

LAMBDA_FUNCTION_PATH = "functions.networking.dynamic_dns_update.lambda_function"


def _basic_auth_header(username, password):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


class TestDynamicDnsUpdate(TestCase):

    def setUp(self):
        self.env_patch = patch.dict(os.environ, {
            "DDNS_SECRET_NAME": "ddns/router-credential",
            "HOSTED_ZONE_ID": "Z123456789",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        # Environment variables are read at import time, so keep the module's
        # module-level constants in sync with the patched environment.
        patch(f"{LAMBDA_FUNCTION_PATH}.DDNS_SECRET_NAME", "ddns/router-credential").start()
        patch(f"{LAMBDA_FUNCTION_PATH}.HOSTED_ZONE_ID", "Z123456789").start()
        self.addCleanup(patch.stopall)

    def _make_event(self, username="router", password="s3cr3t", hostname="shop.asmbly.org", myip="1.2.3.4"):
        query_params = {}
        if hostname is not None:
            query_params["hostname"] = hostname
        if myip is not None:
            query_params["myip"] = myip
        return {
            "headers": {"Authorization": _basic_auth_header(username, password)},
            "queryStringParameters": query_params or None,
        }

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_single_hostname_success(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "s3cr3t",
            "allowed_hostnames": ["shop.asmbly.org", "vpn.asmbly.org"],
        }
        mock_route53 = MagicMock()
        mock_boto3_client.return_value = mock_route53

        event = self._make_event()
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "good 1.2.3.4")
        mock_route53.change_resource_record_sets.assert_called_once_with(
            HostedZoneId="Z123456789",
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": "shop.asmbly.org",
                            "Type": "A",
                            "TTL": 60,
                            "ResourceRecords": [{"Value": "1.2.3.4"}],
                        },
                    }
                ]
            },
        )

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_multiple_hostnames_success(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "s3cr3t",
            "allowed_hostnames": ["shop.asmbly.org", "vpn.asmbly.org"],
        }
        mock_route53 = MagicMock()
        mock_boto3_client.return_value = mock_route53

        event = self._make_event(hostname="shop.asmbly.org,vpn.asmbly.org")
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "good 1.2.3.4\ngood 1.2.3.4")
        self.assertEqual(mock_route53.change_resource_record_sets.call_count, 2)

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_bad_credentials(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "correct-password",
            "allowed_hostnames": ["shop.asmbly.org"],
        }

        event = self._make_event(password="wrong-password")
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"], "badauth")
        mock_boto3_client.assert_not_called()

    def test_missing_auth_header(self):
        event = self._make_event()
        del event["headers"]["Authorization"]

        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"], "badauth")

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_disallowed_hostname_rejects_whole_request(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "s3cr3t",
            "allowed_hostnames": ["shop.asmbly.org"],
        }

        event = self._make_event(hostname="shop.asmbly.org,not-allowed.asmbly.org")
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "nohost")
        mock_boto3_client.assert_not_called()

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_missing_query_params(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "s3cr3t",
            "allowed_hostnames": ["shop.asmbly.org"],
        }

        event = self._make_event(hostname=None, myip=None)
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(response["body"], "notfqdn")
        mock_boto3_client.assert_not_called()

    @patch(f"{LAMBDA_FUNCTION_PATH}.boto3.client")
    @patch(f"{LAMBDA_FUNCTION_PATH}.aws")
    def test_route53_error_returns_dnserr_for_that_hostname(self, mock_aws, mock_boto3_client):
        mock_aws.get_secret_json.return_value = {
            "username": "router",
            "password": "s3cr3t",
            "allowed_hostnames": ["shop.asmbly.org", "vpn.asmbly.org"],
        }
        mock_route53 = MagicMock()
        mock_route53.change_resource_record_sets.side_effect = [None, Exception("boom")]
        mock_boto3_client.return_value = mock_route53

        event = self._make_event(hostname="shop.asmbly.org,vpn.asmbly.org")
        response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "good 1.2.3.4\ndnserr")

    def test_missing_environment_variables(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch(f"{LAMBDA_FUNCTION_PATH}.DDNS_SECRET_NAME", None), \
             patch(f"{LAMBDA_FUNCTION_PATH}.HOSTED_ZONE_ID", None):
            event = self._make_event()
            response = lambda_function.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"], "911")
