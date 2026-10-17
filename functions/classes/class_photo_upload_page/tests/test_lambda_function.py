import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from functions.classes.class_photo_upload_api import lambda_function as api
from functions.classes.class_photo_upload_api import photo_checks
from functions.classes.class_photo_upload_page import lambda_function

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_HTML = (Path(lambda_function.__file__).parent / "page.html").read_text(encoding="utf-8")

AUTH_DOMAIN = "asmbly-staff.auth.us-east-2.amazoncognito.com"
CLIENT_ID = "fakeappclientid123"
ENV = {
    "STAFF_AUTH_DOMAIN": AUTH_DOMAIN,
    "CLASS_PHOTO_APP_CLIENT_ID": CLIENT_ID,
    "CLASS_PHOTO_DRY_RUN": "false",
}
CONFIG_BLOCK = re.compile(r'<script type="application/json" id="page-config">(.*?)</script>', re.S)


def _event(domain: str | None = None, path: str | None = None) -> dict[str, Any]:
    event = json.loads((FIXTURES / "api_event_page.json").read_text())
    if domain is not None:
        event["requestContext"]["domainName"] = domain
    if path is not None:
        event["requestContext"]["path"] = path
    return event


def _call(event: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    with patch.dict("os.environ", env if env is not None else ENV, clear=True):
        return lambda_function.lambda_handler(event, None)


def _config(body: str) -> dict[str, Any]:
    match = CONFIG_BLOCK.search(body)
    assert match is not None
    return json.loads(match.group(1))


def _csp(response: dict[str, Any]) -> dict[str, str]:
    directives = [part.strip() for part in response["headers"]["Content-Security-Policy"].split(";")]
    return {directive.split(" ", 1)[0]: directive.split(" ", 1)[1] if " " in directive else "" for directive in directives}


def test_serves_page_with_config_and_nonce() -> None:
    response = _call(_event())

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "text/html; charset=utf-8"
    body = response["body"]
    assert _config(body) == {
        "authDomain": AUTH_DOMAIN,
        "clientId": CLIENT_ID,
        "pageUrl": "https://facilities.asmbly.org/class-photo-upload",
        "dryRun": False,
    }
    nonce = _csp(response)["script-src"].removeprefix("'nonce-").removesuffix("'")
    assert nonce and _csp(response)["style-src"] == f"'nonce-{nonce}'"
    assert f'<script nonce="{nonce}">' in body
    assert f'<style nonce="{nonce}">' in body
    assert "__CSP_NONCE__" not in body and "__PAGE_CONFIG__" not in body


def test_stage_page_url_includes_stage() -> None:
    domain = "abc123.execute-api.us-east-2.amazonaws.com"
    env = {**ENV, "CLASS_PHOTO_DRY_RUN": "true"}

    response = _call(_event(domain=domain, path="/stage/class-photo-upload"), env)

    config = _config(response["body"])
    assert config["pageUrl"] == f"https://{domain}/stage/class-photo-upload"
    assert config["dryRun"] is True


@pytest.mark.parametrize("value", [None, "", "TRUE", "no"])
def test_dry_run_is_default(value: str | None) -> None:
    env = {key: item for key, item in ENV.items() if key != "CLASS_PHOTO_DRY_RUN"}
    if value is not None:
        env["CLASS_PHOTO_DRY_RUN"] = value

    assert _config(_call(_event(), env)["body"])["dryRun"] is True


def test_config_json_cannot_close_the_script() -> None:
    client_id = "x</script><script>alert(1)</script>&"

    body = _call(_event(), {**ENV, "CLASS_PHOTO_APP_CLIENT_ID": client_id})["body"]

    assert "alert(1)</script>" not in body
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e\\u0026" in body
    assert body.count("</script>") == 2  # the JSON block and the program
    assert _config(body)["clientId"] == client_id


def test_csp_header() -> None:
    response = _call(_event())

    directives = _csp(response)
    nonce = directives["script-src"]
    assert re.fullmatch(r"'nonce-[A-Za-z0-9_-]{20,}'", nonce)
    assert directives == {
        "default-src": "'none'",
        "script-src": nonce,
        "style-src": nonce,
        "img-src": "blob:",
        "connect-src": f"'self' https://{AUTH_DOMAIN}",
        "base-uri": "'none'",
        "form-action": "'none'",
        "frame-ancestors": "'none'",
    }
    assert "unsafe-inline" not in response["headers"]["Content-Security-Policy"]
    assert response["headers"]["X-Content-Type-Options"] == "nosniff"
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["Referrer-Policy"] == "no-referrer"


def test_nonce_changes_per_request() -> None:
    first = _csp(_call(_event()))["script-src"]
    second = _csp(_call(_event()))["script-src"]

    assert first != second


@pytest.mark.parametrize("missing", lambda_function.REQUIRED_ENV)
def test_missing_env_returns_500_without_details(missing: str, caplog: pytest.LogCaptureFixture) -> None:
    env = {key: value for key, value in ENV.items() if key != missing}

    with caplog.at_level(logging.ERROR):
        response = _call(_event(), env)

    assert response["statusCode"] == 500
    assert "Something went wrong on our side. Try again later." in response["body"]
    assert missing not in response["body"]
    for value in env.values():
        assert value not in response["body"]
    assert missing in caplog.text


def test_invalid_auth_domain_returns_500() -> None:
    response = _call(_event(), {**ENV, "STAFF_AUTH_DOMAIN": "https://evil.example/x"})

    assert response["statusCode"] == 500
    assert "evil" not in response["body"]
    assert "Content-Security-Policy" in response["headers"]


@pytest.mark.parametrize(
    "path",
    ["/class-photo-upload/classes", "/other", "/a/b/class-photo-upload", "/x\"y/class-photo-upload", "", None],
)
def test_unexpected_path_returns_400(path: str | None) -> None:
    event = _event()
    event["requestContext"]["path"] = path

    response = _call(event)

    assert response["statusCode"] == 400
    assert "page-config" not in response["body"]


@pytest.mark.parametrize("domain", ["evil.example/x", "a b", "", None, "facilities.asmbly.org:443"])
def test_bad_domain_returns_400(domain: str | None) -> None:
    event = _event()
    event["requestContext"]["domainName"] = domain

    assert _call(event)["statusCode"] == 400


def test_event_without_request_context_returns_400() -> None:
    event = _event()
    del event["requestContext"]

    assert _call(event)["statusCode"] == 400
    assert _call([])["statusCode"] == 400  # type: ignore[arg-type]


def test_page_has_public_warning_above_submit() -> None:
    warning = (
        "When you submit, this photo becomes public on GitHub right away, before anyone reviews it. "
        "It stays visible in the pull request even if the pull request is never merged."
    )
    body = _call(_event())["body"]

    warning_at = body.index(warning)
    submit_at = body.index('<button type="button" id="submit"')
    assert warning_at < submit_at
    # Nothing but the warning's closing tag between it and the button.
    assert body[warning_at + len(warning) : submit_at].strip() == "</p>"


def test_page_shows_stage_banner_text() -> None:
    assert (
        "Stage: dry run. Submitting checks the photo and shows what would happen; nothing is opened on GitHub."
        in PAGE_HTML
    )


@pytest.mark.parametrize(
    "message",
    [
        photo_checks.TOO_BIG_MESSAGE.replace("{size:.1f}", "{size}"),
        photo_checks.NOT_JPEG_MESSAGE,
        photo_checks.UNREADABLE_JPEG_MESSAGE,
        photo_checks.WRONG_RATIO_MESSAGE,
        photo_checks.NOT_LANDSCAPE_MESSAGE,
        photo_checks.LOCATION_MESSAGE,
        photo_checks.EXAMPLE_SIZE,
        # The API's messages the page shows itself when an answer carries none.
        api.GENERIC_ERROR,
        api.NEON_ERROR,
        api.FORBIDDEN_ERROR,
    ],
)
def test_page_messages_match_server_messages(message: str) -> None:
    assert f'"{message}"' in PAGE_HTML


def test_page_check_limits_match_the_server() -> None:
    assert f"const MAX_HEADER_SEGMENTS = {photo_checks.MAX_HEADER_SEGMENTS};" in PAGE_HTML
    assert f"const MAX_EMBEDDED_IMAGES = {photo_checks.MAX_EMBEDDED_IMAGES};" in PAGE_HTML
    assert f"const RATIO_TERM_LIMIT = {photo_checks.RATIO_TERM_LIMIT};" in PAGE_HTML
    assert f"const RATIO_TOLERANCE_PERCENT = {photo_checks.RATIO_TOLERANCE_PERCENT};" in PAGE_HTML
    assert photo_checks.MAX_PHOTO_BYTES == 4 * 1024 * 1024
    assert "const MAX_PHOTO_BYTES = 4 * 1024 * 1024;" in PAGE_HTML
    assert f"/{photo_checks.XMP_GPS_PATTERN.pattern.decode('ascii')}/" in PAGE_HTML


def test_page_uses_text_content_not_inner_html() -> None:
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in PAGE_HTML
    # Style attributes would need 'unsafe-inline' under the page's CSP.
    assert "style=" not in PAGE_HTML


def test_page_has_one_inline_script_and_style() -> None:
    assert PAGE_HTML.count("<script nonce=") == 1
    assert PAGE_HTML.count("<style nonce=") == 1
    assert PAGE_HTML.count("<script") == 2  # the program and the JSON config


def test_logs_hold_no_query_string(caplog: pytest.LogCaptureFixture) -> None:
    event = _event()
    event["queryStringParameters"] = {"code": "SECRETCODE", "state": "SECRETSTATE"}
    event["multiValueQueryStringParameters"] = {"code": ["SECRETCODE"], "state": ["SECRETSTATE"]}

    with caplog.at_level(logging.DEBUG):
        response = _call(event)

    assert response["statusCode"] == 200
    assert "SECRETCODE" not in caplog.text and "SECRETSTATE" not in caplog.text
    assert "SECRETCODE" not in response["body"]
    assert "Served class photo page (dry_run=False)" in caplog.text
