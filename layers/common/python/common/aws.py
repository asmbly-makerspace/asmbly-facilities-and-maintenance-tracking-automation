import boto3
import json
import os

def get_secret(secret_name, secret_key):
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
        print(f"ERROR: Unable to retrieve secret '{secret_name}' with key '{secret_key}': {e}")
        raise e
