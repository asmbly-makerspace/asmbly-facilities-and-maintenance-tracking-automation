import base64
import hmac
import logging
import os
from typing import Optional

import boto3
from common import aws

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DDNS_SECRET_NAME = os.environ.get("DDNS_SECRET_NAME")
HOSTED_ZONE_ID = os.environ.get("HOSTED_ZONE_ID")

RECORD_TTL_SECONDS = 60


def _parse_basic_auth(headers: Optional[dict]) -> Optional[tuple]:
    """Extracts (username, password) from a Basic Authorization header, or None if missing/malformed."""
    auth_header = None
    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            auth_header = value
            break

    if not auth_header or not auth_header.startswith("Basic "):
        return None

    try:
        decoded = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8")
        username, _, password = decoded.partition(":")
        return username, password
    except Exception as e:
        logger.warning("Failed to decode Basic Auth header: %s", e)
        return None


def _text_response(status_code: int, body: str) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/plain"},
        "body": body,
    }


def lambda_handler(event, context):
    """Handles a DynDNS2-style update request from the UDM and upserts Route53 A records."""
    if not DDNS_SECRET_NAME or not HOSTED_ZONE_ID:
        logger.error("DDNS_SECRET_NAME or HOSTED_ZONE_ID environment variable not set.")
        return _text_response(500, "911")

    credentials = _parse_basic_auth(event.get("headers"))
    if not credentials:
        return _text_response(401, "badauth")
    supplied_username, supplied_password = credentials

    try:
        username = aws.get_secret(DDNS_SECRET_NAME, "username")
        password = aws.get_secret(DDNS_SECRET_NAME, "password")
        allowed_hostnames = aws.get_secret(DDNS_SECRET_NAME, "allowed_hostnames")
    except Exception as e:
        logger.error("Failed to retrieve DDNS credential secret: %s", e)
        return _text_response(500, "911")

    # Constant-time comparison to avoid leaking credential validity via timing.
    username_ok = hmac.compare_digest(supplied_username, username)
    password_ok = hmac.compare_digest(supplied_password, password)
    if not (username_ok and password_ok):
        return _text_response(401, "badauth")

    query_params = event.get("queryStringParameters") or {}
    hostname_param = query_params.get("hostname")
    myip = query_params.get("myip")
    if not hostname_param or not myip:
        return _text_response(400, "notfqdn")

    hostnames = [h.strip() for h in hostname_param.split(",") if h.strip()]
    if not hostnames:
        return _text_response(400, "notfqdn")

    # Reject the whole request if any hostname isn't allowed, so a partial
    # or ambiguous update never happens.
    if any(hostname not in allowed_hostnames for hostname in hostnames):
        logger.warning("Rejected update for disallowed hostname(s): %s", hostname_param)
        return _text_response(200, "nohost")

    route53_client = boto3.client("route53")
    results = []
    for hostname in hostnames:
        try:
            route53_client.change_resource_record_sets(
                HostedZoneId=HOSTED_ZONE_ID,
                ChangeBatch={
                    "Changes": [
                        {
                            "Action": "UPSERT",
                            "ResourceRecordSet": {
                                "Name": hostname,
                                "Type": "A",
                                "TTL": RECORD_TTL_SECONDS,
                                "ResourceRecords": [{"Value": myip}],
                            },
                        }
                    ]
                },
            )
            results.append(f"good {myip}")
        except Exception as e:
            logger.error("Failed to update Route53 record for %s: %s", hostname, e)
            results.append("dnserr")

    return _text_response(200, "\n".join(results))
