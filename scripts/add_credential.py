"""CLI tool to create or update the Dynamic DNS credential secret.

Provisions the Secrets Manager secret consumed by the
`dynamic_dns_update` Lambda (see PLAN.md, "Secrets Manager credential").
This secret is created out-of-band -- it is intentionally NOT a
CloudFormation resource -- so it must be run manually before deploying
the `NetworkingStack` for a given stage.

Example:
    python scripts/add_credential.py --stage dev --username udm \\
        --hostname shop.asmbly.org --hostname vpn.asmbly.org
"""

import argparse
import getpass
import json
import sys
from typing import List

import boto3
from botocore.exceptions import ClientError

DEFAULT_REGION = "us-east-2"


def build_secret_name(stage: str) -> str:
    """Builds the stage-scoped secret name, matching the project's
    ${Stage} isolation convention."""
    return f"ddns/router-credential-{stage}"


def normalize_hostnames(hostnames: List[str]) -> List[str]:
    """Lowercases and strips trailing whitespace from each hostname.

    Does not append a trailing dot: this list is stored in the secret
    for application-level comparison against the DynDNS2 `hostname`
    parameter, which routers submit without a trailing dot.
    """
    return [hostname.strip().lower() for hostname in hostnames]


def format_cloudformation_hostnames(hostnames: List[str]) -> str:
    """Format application hostnames for the Route 53 IAM condition."""
    return ",".join(f"{hostname.rstrip('.')}." for hostname in hostnames)


def put_credential_secret(
    secret_name: str,
    username: str,
    password: str,
    allowed_hostnames: List[str],
    region: str,
) -> None:
    """Creates the secret if it doesn't exist, otherwise updates its value."""
    client = boto3.session.Session().client(
        service_name="secretsmanager", region_name=region
    )
    secret_value = json.dumps(
        {
            "username": username,
            "password": password,
            "allowed_hostnames": allowed_hostnames,
        }
    )

    try:
        client.create_secret(Name=secret_name, SecretString=secret_value)
        print(f"Created secret '{secret_name}'.")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceExistsException":
            print(f"::error::Unable to create secret '{secret_name}': {error}")
            sys.exit(1)
        try:
            client.put_secret_value(SecretId=secret_name, SecretString=secret_value)
            print(f"Updated existing secret '{secret_name}'.")
        except ClientError as update_error:
            print(
                f"::error::Unable to update secret '{secret_name}': {update_error}"
            )
            sys.exit(1)

    print(f"allowed_hostnames: {allowed_hostnames}")
    print(
        "DdnsHostnames parameter value: "
        f"{format_cloudformation_hostnames(allowed_hostnames)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update the Dynamic DNS router credential secret."
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=["dev", "stage", "prod"],
        help="Deployment stage the secret belongs to.",
    )
    parser.add_argument("--username", required=True, help="DynDNS2 client username.")
    parser.add_argument(
        "--password",
        required=False,
        help="DynDNS2 client password. Omit to be prompted securely.",
    )
    parser.add_argument(
        "--hostname",
        required=True,
        action="append",
        help="Hostname this credential may update. Repeat for multiple hostnames.",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region of the secret. Defaults to {DEFAULT_REGION}.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    secret_password = args.password or getpass.getpass("Password: ")

    if not secret_password:
        print("::error::Password must not be empty.")
        sys.exit(1)

    put_credential_secret(
        secret_name=build_secret_name(args.stage),
        username=args.username,
        password=secret_password,
        allowed_hostnames=normalize_hostnames(args.hostname),
        region=args.region,
    )

