import boto3
import json
import logging
import os
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _error_summary(e: BaseException) -> str:
    """Describe an error by its class and, for an AWS ClientError, its error code.

    Never includes the exception's text, which can carry secret or parameter values.
    """
    summary = type(e).__name__
    if isinstance(e, ClientError):
        response = e.response if isinstance(e.response, dict) else {}
        error = response.get("Error", {})
        code = error.get("Code", "Unknown") if isinstance(error, dict) else "Unknown"
        summary = f"{summary} ({code})"
    return summary


def get_secret_json(secret_name: str) -> Any:
    """Retrieve and parse a JSON secret with a single Secrets Manager call."""
    region_name = os.environ.get("AWS_REGION", "us-east-2")
    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=region_name,
    )
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.error("Unable to retrieve or parse secret %s: %s", secret_name, _error_summary(e))
        raise


def get_secret(secret_name: str, secret_key: str) -> Any:
    """
    Retrieves a specific key from a secret stored in AWS Secrets Manager.
    If the retrieved value is a string, it will be stripped of leading/trailing whitespace.
    """
    # Use AWS_REGION if available, otherwise default to us-east-2 for local dev/testing
    region_name = os.environ.get("AWS_REGION", "us-east-2")
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        secret_dict = json.loads(secret_string)

        if secret_key in secret_dict:
            value = secret_dict[secret_key]
            if isinstance(value, str):
                return value.strip()
            return value
        else:
            raise KeyError(f"Key '{secret_key}' not found in secret '{secret_name}'")

    except Exception as e:
        logger.error(
            "Unable to retrieve secret %s with key %s: %s", secret_name, secret_key, _error_summary(e)
        )
        raise e

def get_json_parameter(parameter_name: str, expected_key: str | None = None) -> Any:
    """
    Retrieves a parameter from AWS Systems Manager (SSM) Parameter Store
    and parses it as JSON. If expected_key is provided, it extracts and
    returns the value for that key.
    """
    region_name = os.environ.get("AWS_REGION", "us-east-2")
    session = boto3.session.Session()
    client = session.client(
        service_name='ssm',
        region_name=region_name
    )
    try:
        parameter_response = client.get_parameter(Name=parameter_name, WithDecryption=True)
        parameter_value = parameter_response['Parameter']['Value']
        config_data = json.loads(parameter_value)

        if expected_key:
            if expected_key not in config_data:
                raise KeyError(f"Key '{expected_key}' not found in SSM parameter '{parameter_name}'.")
            return config_data[expected_key]

        return config_data

    except Exception as e:
        logger.error("Unable to retrieve or parse SSM parameter %s: %s", parameter_name, _error_summary(e))
        raise e
