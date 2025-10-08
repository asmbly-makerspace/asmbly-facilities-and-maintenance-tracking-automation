import json
import os
import sys
from unittest.mock import MagicMock

import pytest

# Add the parent directory to the path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aws import get_secret

def test_get_secret_success(mocker):
    """Test successful retrieval of a secret from AWS Secrets Manager."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'MY_KEY': 'supersecret'})
    }
    mocker.patch('boto3.session.Session.client', return_value=mock_secrets_client)

    secret = get_secret('some-secret', 'MY_KEY')
    assert secret == 'supersecret'
    mock_secrets_client.get_secret_value.assert_called_once_with(SecretId='some-secret')

def test_get_secret_key_not_found(mocker):
    """Test that a KeyError is raised if the key is not in the secret."""
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        'SecretString': json.dumps({'OTHER_KEY': 'supersecret'})
    }
    mocker.patch('boto3.session.Session.client', return_value=mock_secrets_client)

    with pytest.raises(KeyError, match="Key 'MISSING_KEY' not found in secret 'some-secret'"):
        get_secret('some-secret', 'MISSING_KEY')
