import boto3
import json

def get_secret(secret_name, secret_key=None):
    """
    Retrieves a secret from AWS Secrets Manager.

    Args:
        secret_name (str): The name of the secret to retrieve.
        secret_key (str, optional): The key of the value to retrieve from a JSON secret. 
                                    If None, the function attempts to return a sensible
                                    default based on the secret's structure.

    Returns:
        str: The secret value.

    Raises:
        KeyError: If the secret_key is not found in the secret.
        Exception: For other errors during secret retrieval.
    """
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager')

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']

        try:
            # Try to parse as JSON
            secret_dict = json.loads(secret_string)

            if secret_key:
                if secret_key in secret_dict:
                    value = secret_dict[secret_key]
                    return value.strip() if isinstance(value, str) else value
                else:
                    raise KeyError(f"Key '{secret_key}' not found in secret '{secret_name}'")
            
            # If no key is specified and it's a dict with one entry, return that entry's value
            if isinstance(secret_dict, dict) and len(secret_dict) == 1:
                value = list(secret_dict.values())[0]
                return value.strip() if isinstance(value, str) else value

            # If it's a dict but we don't know which key to use, return the whole dict
            if isinstance(secret_dict, dict):
                return secret_dict

        except json.JSONDecodeError:
            # Not a JSON string, return the raw string
            return secret_string.strip()

    except Exception as e:
        print(f"ERROR: Unable to retrieve secret '{secret_name}': {e}")
        raise e
