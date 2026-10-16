import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
import pytest

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

from common.aws import get_json_parameter, get_secret, get_secret_json, boto3

def _aws_errors(caplog):
    return [r for r in caplog.records if r.name == "common.aws" and r.levelno == logging.ERROR]


@patch('common.aws.boto3.session.Session.client')
def test_get_secret_success(mock_boto3_client):
    """Test successful retrieval of a secret from AWS Secrets Manager."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'MY_KEY': 'supersecret'})
    }
    mock_boto3_client.return_value = mock_secrets_client

    secret = get_secret('some-secret', 'MY_KEY')
    assert secret == 'supersecret'
    mock_secrets_client.get_secret_value.assert_called_once_with(SecretId='some-secret')

@patch('common.aws.boto3.session.Session.client')
def test_get_secret_key_not_found(mock_boto3_client):
    """Test that a KeyError is raised if the key is not in the secret."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'OTHER_KEY': 'supersecret'})
    }
    mock_boto3_client.return_value = mock_secrets_client

    with pytest.raises(KeyError, match="Key 'MISSING_KEY' not found in secret 'some-secret'"):
        get_secret('some-secret', 'MISSING_KEY')

@patch('common.aws.boto3.session.Session.client')
def test_get_json_parameter_success(mock_boto3_client):
    """Test successful retrieval and parsing of a JSON parameter from SSM."""
    mock_ssm_client = MagicMock()
    mock_ssm_client.get_parameter.return_value = {
        'Parameter': {'Value': json.dumps({'key': 'value', 'number': 123})}
    }
    mock_boto3_client.return_value = mock_ssm_client

    param_data = get_json_parameter('/my/param')

    assert param_data == {'key': 'value', 'number': 123}
    mock_ssm_client.get_parameter.assert_called_once_with(Name='/my/param', WithDecryption=True)

@patch('common.aws.boto3.session.Session.client')
def test_get_json_parameter_client_error(mock_boto3_client, caplog, capsys):
    """Test that a boto3 ClientError is propagated and logged by parameter name and code."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    mock_ssm_client = MagicMock()
    error_response = {'Error': {'Code': 'ParameterNotFound', 'Message': 'Parameter not found'}}
    mock_ssm_client.get_parameter.side_effect = ClientError(error_response, 'GetParameter')
    mock_boto3_client.return_value = mock_ssm_client

    with pytest.raises(ClientError):
        get_json_parameter('/non/existent/param')

    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert '/non/existent/param' in errors[0].getMessage()
    assert 'ParameterNotFound' in errors[0].getMessage()

@patch('common.aws.boto3.session.Session.client')
def test_get_json_parameter_invalid_json(mock_boto3_client, caplog, capsys):
    """Test that an error is raised if the parameter value is not valid JSON."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    mock_ssm_client = MagicMock()
    mock_ssm_client.get_parameter.return_value = {
        'Parameter': {'Value': 'this is not valid json pk_SSM_MARKER'}
    }
    mock_boto3_client.return_value = mock_ssm_client

    # json.loads raises json.JSONDecodeError, which is caught and re-raised as a generic Exception
    with pytest.raises(Exception) as excinfo:
        get_json_parameter('/invalid/json/param')
    assert 'Expecting value' in str(excinfo.value) # Check for part of the JSONDecodeError message
    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert '/invalid/json/param' in errors[0].getMessage()
    assert 'JSONDecodeError' in errors[0].getMessage()
    assert 'pk_SSM_MARKER' not in caplog.text

@patch('common.aws.boto3.session.Session.client')
def test_get_json_parameter_with_expected_key_success(mock_boto3_client):
    """Test successful retrieval of a single key from a JSON parameter."""
    mock_ssm_client = MagicMock()
    mock_ssm_client.get_parameter.return_value = {
        'Parameter': {'Value': json.dumps({'key1': 'value1', 'key2': 'value2'})}
    }
    mock_boto3_client.return_value = mock_ssm_client

    value = get_json_parameter('/my/param', expected_key='key1')

    assert value == 'value1'
    mock_ssm_client.get_parameter.assert_called_once_with(Name='/my/param', WithDecryption=True)

@patch('common.aws.boto3.session.Session.client')
def test_get_json_parameter_with_missing_key(mock_boto3_client):
    """Test that a KeyError is raised if the expected key is not found."""
    mock_ssm_client = MagicMock()
    mock_ssm_client.get_parameter.return_value = {
        'Parameter': {'Value': json.dumps({'key1': 'value1'})}
    }
    mock_boto3_client.return_value = mock_ssm_client

    with pytest.raises(KeyError, match="Key 'missing_key' not found in SSM parameter '/my/param'."):
        get_json_parameter('/my/param', expected_key='missing_key')


@patch('common.aws.boto3.session.Session.client')
def test_get_secret_key_not_found_logs_without_secret_value(mock_boto3_client, caplog, capsys):
    """A missing key is logged by secret name and key, never with the secret's values."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'OTHER_KEY': 'pk_SECRET_MARKER'})
    }
    mock_boto3_client.return_value = mock_secrets_client

    with pytest.raises(KeyError) as excinfo:
        get_secret('some-secret', 'MISSING_KEY')

    assert excinfo.value.args == ("Key 'MISSING_KEY' not found in secret 'some-secret'",)
    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert 'some-secret' in errors[0].getMessage()
    assert 'MISSING_KEY' in errors[0].getMessage()
    assert 'pk_SECRET_MARKER' not in caplog.text


@patch('common.aws.boto3.session.Session.client')
def test_get_secret_json_invalid_json_logs_without_secret_value(mock_boto3_client, caplog, capsys):
    """Invalid JSON in a secret is logged by secret name and error type, never with the value."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': '{"CLICKUP_API_TOKEN": "pk_SECRET_MARKER" oops}'
    }
    mock_boto3_client.return_value = mock_secrets_client

    with pytest.raises(json.JSONDecodeError):
        get_secret_json('some-secret')

    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert 'some-secret' in errors[0].getMessage()
    assert 'JSONDecodeError' in errors[0].getMessage()
    assert 'pk_SECRET_MARKER' not in caplog.text


@patch('common.aws.boto3.session.Session.client')
def test_get_secret_client_error_reraises_same_exception_and_logs_code(mock_boto3_client, caplog, capsys):
    """A ClientError is re-raised as the same object and logged with its error code."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    err = ClientError({'Error': {'Code': 'AccessDeniedException', 'Message': 'pk_MSG_MARKER'}}, 'GetSecretValue')
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.side_effect = err
    mock_boto3_client.return_value = mock_secrets_client

    with pytest.raises(ClientError) as excinfo:
        get_secret('some-secret', 'MY_KEY')

    assert excinfo.value is err
    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert 'AccessDeniedException' in errors[0].getMessage()
    assert 'some-secret' in errors[0].getMessage()
    assert 'pk_MSG_MARKER' not in caplog.text


@patch('common.aws.boto3.session.Session.client')
def test_get_secret_json_client_error_without_code_reraises_same_exception(mock_boto3_client, caplog, capsys):
    """A ClientError with an empty response is still re-raised as the same object and logged."""
    caplog.set_level(logging.DEBUG, logger="common.aws")
    err = ClientError({}, 'GetSecretValue')
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.side_effect = err
    mock_boto3_client.return_value = mock_secrets_client

    with pytest.raises(ClientError) as excinfo:
        get_secret_json('some-secret')

    assert excinfo.value is err
    assert capsys.readouterr().out == ""
    errors = _aws_errors(caplog)
    assert len(errors) == 1
    assert 'some-secret' in errors[0].getMessage()
