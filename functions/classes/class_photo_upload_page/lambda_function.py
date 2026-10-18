"""Serves the class photo upload page: a fixed HTML sign-in shell.

``GET /class-photo-upload`` has no authorizer, because a browser opening the page can't
send a token (README Decision 7). The page reads nothing, calls nothing and changes
nothing: it embeds only public values (the staff pool's sign-in host, this page's app
client ID, its own URL and whether submissions are a dry run), signs the person in with
the staff pool, and then calls the data routes, which sit behind the Cognito authorizer.

The page's shared brand tokens and Asmbly logo (``common/brand.py``) and its
Content-Security-Policy (``common/csp.py``) come from the common layer. The tokens and
logo are filled into ``page.html`` once per container. Both modules import only the
standard library, so this function needs no other layer and loads no boto3.
"""

import html
import json
import logging
import os
import pathlib
import re
from typing import Any

from common import brand, csp

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PAGE_PATH = pathlib.Path(__file__).with_name("page.html")
# Both are checked with fullmatch: `$` with match would also accept a trailing newline.
HOST_PATTERN = re.compile(r"[A-Za-z0-9.-]+")
# "/class-photo-upload" on the custom domain, "/<stage>/class-photo-upload" on the API's own host.
PATH_PATTERN = re.compile(r"(?:/[A-Za-z0-9_-]+)?/class-photo-upload")
REQUIRED_ENV = ("STAFF_AUTH_DOMAIN", "CLASS_PHOTO_APP_CLIENT_ID")

NONCE_MARKER = "__CSP_NONCE__"
CONFIG_MARKER = "__PAGE_CONFIG__"
# JSON inside <script type="application/json"> must not be able to close the element.
JSON_HTML_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}

SERVER_ERROR_TEXT = "Something went wrong on our side. Try again later."
BAD_REQUEST_TEXT = "This page can't be opened from this address."

ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Class photo upload</title></head>
<body><p>{message}</p></body>
</html>
"""
ERROR_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": csp.strict_policy(),
}

_page_template: str | None = None


def _template() -> str:
    """page.html with the shared brand tokens and logo filled in, read once per container."""
    global _page_template
    if _page_template is None:
        _page_template = brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))
    return _page_template


def is_dry_run() -> bool:
    """Anything but ``false`` in CLASS_PHOTO_DRY_RUN (or no value) is a dry run."""
    return os.environ.get("CLASS_PHOTO_DRY_RUN", "true").strip().lower() != "false"


def page_url(event: dict[str, Any]) -> str | None:
    """The page's own address, from the host and path API Gateway saw; None if unexpected.

    It is the sign-in return address and the base of the API routes, so it must equal a
    callback URL on the app client.
    """
    request_context = event.get("requestContext")
    if not isinstance(request_context, dict):
        return None
    domain = request_context.get("domainName")
    path = request_context.get("path")
    if not isinstance(domain, str) or not HOST_PATTERN.fullmatch(domain):
        return None
    if not isinstance(path, str) or not PATH_PATTERN.fullmatch(path):
        return None
    return f"https://{domain}{path}"


def render_page(config: dict[str, Any], nonce: str) -> str:
    """page.html with its config JSON and CSP nonce filled in."""
    config_json = json.dumps(config)
    for character, escape in JSON_HTML_ESCAPES.items():
        config_json = config_json.replace(character, escape)
    return _template().replace(NONCE_MARKER, nonce).replace(CONFIG_MARKER, config_json)


def response_headers(auth_domain: str, nonce: str) -> dict[str, str]:
    """The page's headers: one nonce for its inline script and style, images only from
    blob: URLs, and fetches only to its own origin and the sign-in host."""
    return {
        "Content-Type": "text/html; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": csp.nonce_policy(
            nonce, [("img-src", "blob:"), ("connect-src", f"'self' https://{auth_domain}")]
        ),
    }


def _error_page(status: int, message: str) -> dict[str, Any]:
    body = ERROR_PAGE.format(message=html.escape(message))
    return {"statusCode": status, "headers": dict(ERROR_HEADERS), "body": body}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    for name in REQUIRED_ENV:
        if not os.environ.get(name):
            logger.error("Missing environment variable %s", name)
            return _error_page(500, SERVER_ERROR_TEXT)
    auth_domain = os.environ["STAFF_AUTH_DOMAIN"]
    if not HOST_PATTERN.fullmatch(auth_domain):
        logger.error("STAFF_AUTH_DOMAIN is not a host name")
        return _error_page(500, SERVER_ERROR_TEXT)
    dry_run = is_dry_run()

    url = page_url(event if isinstance(event, dict) else {})
    if url is None:
        logger.warning("Refused the class photo page for an unexpected host or path")
        return _error_page(400, BAD_REQUEST_TEXT)

    nonce = csp.new_nonce()
    config = {
        "authDomain": auth_domain,
        "clientId": os.environ["CLASS_PHOTO_APP_CLIENT_ID"],
        "pageUrl": url,
        "dryRun": dry_run,
    }
    # No query string here: after sign-in it carries the one-time code.
    logger.info("Served class photo page (dry_run=%s)", dry_run)
    return {"statusCode": 200, "headers": response_headers(auth_domain, nonce), "body": render_page(config, nonce)}
