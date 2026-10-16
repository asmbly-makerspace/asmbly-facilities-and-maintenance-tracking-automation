"""The class photo upload API: the class list from Neon, and a checked photo as a pull request.

Routes (both behind the staff pool's Cognito authorizer in template.yaml):

- ``GET /class-photo-upload/classes``: the class list, with each class's file name, any
  problem with that name, and any warning that another class shares its photo.
- ``POST /class-photo-upload/submit``: ``{"class_name": ..., "photo_base64": ...}``. Checks
  the photo and the class, then opens or updates the class's pull request on
  asmbly-classes, or, when ``CLASS_PHOTO_DRY_RUN`` isn't ``false`` (every stage but
  prod), reports what it would do with a read-only token.

The authorizer accepts an ID token from any app client of the pool, so the handler also
requires this page's client ID in ``aud`` and ``token_use`` ``id``. Logs carry the route,
the caller's ``sub``, the class name and the outcome; never the username, a token, the
request body or the photo.
"""

import base64
import binascii
import datetime
import hmac
import json
import logging
import math
import os
import traceback
from pathlib import Path
from typing import Any

from common import aws, github_app
from common.github_app import GitHubError
from common.neoncrm import NeonCRM

try:
    from . import class_names, photo_checks, submission
except ImportError:  # Under Lambda this module is top-level, beside its helpers.
    import class_names  # type: ignore[no-redef]
    import photo_checks  # type: ignore[no-redef]
    import submission  # type: ignore[no-redef]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GENERIC_ERROR = "Something went wrong on our side. Try again later."
NEON_ERROR = "Couldn't load the class list. Try again in a minute."
GITHUB_ERROR = "Couldn't open the pull request. Try again in a minute."
CONFLICT_ERROR = "Someone else just submitted a photo for this class. Try again."
FORBIDDEN_ERROR = "You're not allowed to use this page."
NOT_IN_LIST_ERROR = "Pick a class from the list."
BAD_REQUEST_ERROR = "The photo didn't arrive whole. Choose it again and submit."
NOT_FOUND_ERROR = "Not found."

REQUIRED_ENV = (
    "NEON_SECRET_NAME",
    "GITHUB_APP_SECRET_NAME",
    "CLASS_PHOTO_CONFIG_PARAM_NAME",
    "CLASS_PHOTO_APP_CLIENT_ID",
)
GITHUB_SECRET_KEYS = ("app_id", "installation_id", "private_key")

CLASSES_ROUTE = ("GET", "/class-photo-upload/classes")
SUBMIT_ROUTE = ("POST", "/class-photo-upload/submit")

MAX_CLASS_NAME_LENGTH = 200
# The longest base64 a photo within the size limit can take, plus slack for padding.
MAX_PHOTO_BASE64_LENGTH = 4 * math.ceil(photo_checks.MAX_PHOTO_BYTES / 3) + 16

READ_PERMISSIONS = {"contents": "read", "pull_requests": "read"}
WRITE_PERMISSIONS = {"contents": "write", "pull_requests": "write"}
# A GitHub call gives up when it can't connect or gets no data for this long, so the
# request usually ends well inside the function's 25 s timeout (and API Gateway's 29 s).
GITHUB_TIMEOUT_SECONDS = 5.0
# Don't start writing to GitHub with less time than this left: a commit and a pull
# request take a few seconds, and a write cut off half way needs another submission.
WRITE_MIN_REMAINING_MS = 8000

RESPONSE_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

# The kind of photo problem, for the log line: the fixed messages, and a fixed part
# of each formatted one (they all start "This photo is ").
_PHOTO_PROBLEM_EXACT = {
    photo_checks.NOT_JPEG_MESSAGE: "not_jpeg",
    photo_checks.UNREADABLE_JPEG_MESSAGE: "unreadable",
    photo_checks.LOCATION_MESSAGE: "location",
}
_PHOTO_PROBLEM_FRAGMENTS = (
    (photo_checks.TOO_BIG_MESSAGE.split("}", 1)[1], "size"),
    (photo_checks.NOT_LANDSCAPE_MESSAGE.split("{ratio}", 1)[1].split("{", 1)[0], "not_landscape"),
    (photo_checks.WRONG_RATIO_MESSAGE.split("{ratio}", 1)[1].split("{", 1)[0], "ratio"),
)


class Refusal(Exception):
    """A request the handler answers with a 4xx or 5xx and a plain message."""

    def __init__(self, status: int, message: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.message = message
        self.reason = reason


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": dict(RESPONSE_HEADERS), "body": json.dumps(payload)}


def _error(status: int, message: str) -> dict[str, Any]:
    return _response(status, {"error": message})


def is_dry_run() -> bool:
    """Anything but ``false`` in CLASS_PHOTO_DRY_RUN (or no value) is a dry run."""
    return os.environ.get("CLASS_PHOTO_DRY_RUN", "true").strip().lower() != "false"


def caller_claims(event: dict[str, Any], client_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """(claims, None) for an ID token of this page's app client, else (None, reason)."""
    request_context = event.get("requestContext")
    authorizer = request_context.get("authorizer") if isinstance(request_context, dict) else None
    claims = authorizer.get("claims") if isinstance(authorizer, dict) else None
    if not isinstance(claims, dict):
        return None, "claims"
    audience = claims.get("aud")
    if not isinstance(audience, str) or not hmac.compare_digest(
        audience.encode("utf-8"), client_id.encode("utf-8")
    ):
        return None, "audience"
    if claims.get("token_use") != "id":
        return None, "token_use"
    for key in ("sub", "cognito:username"):
        value = claims.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, "claims"
    return claims, None


def photo_problem_kind(message: str) -> str:
    """The short name of the check a photo failed, for the log."""
    if message in _PHOTO_PROBLEM_EXACT:
        return _PHOTO_PROBLEM_EXACT[message]
    for fragment, kind in _PHOTO_PROBLEM_FRAGMENTS:
        if fragment in message:
            return kind
    return "other"


def load_classes() -> list[str]:
    """The class list from Neon; Refusal(502) when the secret or Neon fails."""
    secret_name = os.environ["NEON_SECRET_NAME"]
    try:
        org_id = aws.get_secret(secret_name, "NEON_ORG_ID")
        api_key = aws.get_secret(secret_name, "NEON_API_KEY")
    except Exception as e:
        logger.error("Couldn't read the Neon secret: %s", type(e).__name__)
        raise Refusal(502, NEON_ERROR, "neon_secret") from None
    try:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        return class_names.fetch_classes(NeonCRM(org_id, api_key), today)
    except Exception as e:
        logger.error("Couldn't read the class list from Neon: %s", type(e).__name__)
        raise Refusal(502, NEON_ERROR, "neon") from None


def class_list_entries(classes: list[str]) -> list[dict[str, Any]]:
    """Each class with its file name, file-name problem and shared-photo warning."""
    by_key: dict[str, list[str]] = {}
    for name in classes:
        by_key.setdefault(class_names.fuzzy_key(name), []).append(name)
    entries = []
    for name in classes:
        problem = class_names.file_name_problem(name)
        others = sorted({other for other in by_key[class_names.fuzzy_key(name)] if other != name})
        entries.append(
            {
                "name": name,
                "file_name": None if problem else class_names.exact_file_name(name),
                "problem": problem,
                "warning": class_names.collision_warning(name, others),
            }
        )
    return entries


def handle_classes(dry_run: bool) -> dict[str, Any]:
    classes = load_classes()
    logger.info("Answered %d classes", len(classes))
    return _response(200, {"dry_run": dry_run, "classes": class_list_entries(classes)})


def parse_submission(event: dict[str, Any]) -> tuple[str, str]:
    """(class_name, photo_base64) from the request body, or Refusal(400)."""
    body = event.get("body")
    if not isinstance(body, str):
        raise Refusal(400, BAD_REQUEST_ERROR, "no_body")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise Refusal(400, BAD_REQUEST_ERROR, "body_encoding") from None
    try:
        data = json.loads(body)
    except ValueError:
        raise Refusal(400, BAD_REQUEST_ERROR, "json") from None
    if not isinstance(data, dict):
        raise Refusal(400, BAD_REQUEST_ERROR, "json")
    class_name = data.get("class_name")
    photo_base64 = data.get("photo_base64")
    if not isinstance(class_name, str) or not isinstance(photo_base64, str):
        raise Refusal(400, BAD_REQUEST_ERROR, "fields")
    if not 1 <= len(class_name) <= MAX_CLASS_NAME_LENGTH:
        raise Refusal(400, NOT_IN_LIST_ERROR, "class_length")
    return class_name, photo_base64


def decode_photo(photo_base64: str) -> bytes:
    """The photo's bytes, checked; Refusal(400) with the page's message otherwise."""
    if len(photo_base64) > MAX_PHOTO_BASE64_LENGTH:
        message = photo_checks.too_big_message(len(photo_base64) * 3 // 4)
        raise Refusal(400, message, "photo:size")
    try:
        data = base64.b64decode(photo_base64, validate=True)
    except binascii.Error:
        raise Refusal(400, BAD_REQUEST_ERROR, "photo:base64") from None
    message = photo_checks.check_photo(data)
    if message is not None:
        raise Refusal(400, message, f"photo:{photo_problem_kind(message)}")
    return data


def load_github_settings() -> tuple["submission.RepoConfig", dict[str, str]]:
    """The repository config from SSM and the App's credentials; Refusal(500) otherwise."""
    try:
        config = submission.RepoConfig.from_dict(
            aws.get_json_parameter(os.environ["CLASS_PHOTO_CONFIG_PARAM_NAME"])
        )
    except ValueError as e:
        # RepoConfig names the key, never a value.
        logger.error("Class photo configuration is invalid: %s", e)
        raise Refusal(500, GENERIC_ERROR, "config") from None
    except Exception as e:
        logger.error("Couldn't read the class photo configuration: %s", type(e).__name__)
        raise Refusal(500, GENERIC_ERROR, "config") from None
    try:
        secret = aws.get_secret_json(os.environ["GITHUB_APP_SECRET_NAME"])
    except Exception as e:
        logger.error("Couldn't read the GitHub App secret: %s", type(e).__name__)
        raise Refusal(500, GENERIC_ERROR, "github_secret") from None
    if not isinstance(secret, dict):
        logger.error("The GitHub App secret is not a JSON object")
        raise Refusal(500, GENERIC_ERROR, "github_secret")
    for key in GITHUB_SECRET_KEYS:
        value = secret.get(key)
        if not isinstance(value, str) or not value.strip():
            logger.error("The GitHub App secret has no string %s", key)
            raise Refusal(500, GENERIC_ERROR, "github_secret")
    return config, {key: secret[key].strip() for key in GITHUB_SECRET_KEYS}


def remaining_ms(context: Any) -> int | None:
    getter = getattr(context, "get_remaining_time_in_millis", None)
    if not callable(getter):
        return None
    try:
        return int(getter())
    except (TypeError, ValueError):
        return None


def submission_payload(result: "submission.SubmissionResult", dry_run: bool) -> dict[str, Any]:
    plan = result.plan
    pull_request = result.pull_request
    return {
        "dry_run": dry_run,
        "action": result.action,
        "pull_request": (
            {"number": pull_request["number"], "url": pull_request["html_url"]} if pull_request else None
        ),
        "file_path": plan.file_path,
        "replaces_existing": plan.replaces_existing,
        "removed_paths": list(plan.removed_paths),
        "title": plan.title,
        "body": plan.body,
        "warnings": list(plan.warnings),
    }


def handle_submit(event: dict[str, Any], context: Any, username: str, dry_run: bool) -> dict[str, Any]:
    class_name, photo_base64 = parse_submission(event)
    data = decode_photo(photo_base64)

    classes = load_classes()
    if class_name not in classes:
        raise Refusal(400, NOT_IN_LIST_ERROR, "class_not_in_list")
    logger.info("Class photo submitted for class %s", class_name)
    problem = class_names.file_name_problem(class_name)
    if problem is not None:
        raise Refusal(400, problem, "file_name")

    config, app = load_github_settings()
    permissions = READ_PERMISSIONS if dry_run else WRITE_PERMISSIONS
    try:
        token = github_app.installation_token(
            app["app_id"],
            app["installation_id"],
            app["private_key"],
            config.repo,
            permissions,
            timeout=GITHUB_TIMEOUT_SECONDS,
        )
        repo = github_app.GitHubRepo(
            token, config.owner, config.repo, config.branch_prefix, timeout=GITHUB_TIMEOUT_SECONDS
        )
        plan = submission.plan_submission(repo, config, class_name, classes, username)
        if dry_run:
            result = submission.dry_run_result(plan)
            logger.info("Dry run for class %s: %s on branch %s", class_name, result.action, plan.branch)
        else:
            left = remaining_ms(context)
            if left is not None and left < WRITE_MIN_REMAINING_MS:
                logger.error("Not enough time left to write: %d ms", left)
                raise Refusal(502, GITHUB_ERROR, "time")
            result = submission.apply_submission(
                repo, config, plan, base64.b64encode(data).decode("ascii"), username
            )
    except submission.SubmissionConflict:
        logger.warning("Class photo for class %s lost a race for its branch", class_name)
        raise Refusal(409, CONFLICT_ERROR, "conflict") from None
    except GitHubError as e:
        logger.error("GitHub %s failed for class %s: status %s", e.operation, class_name, e.status)
        raise Refusal(502, GITHUB_ERROR, "github") from None
    return _response(200, submission_payload(result, dry_run))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    for name in REQUIRED_ENV:
        if not os.environ.get(name):
            logger.error("Missing environment variable %s", name)
            return _error(500, GENERIC_ERROR)
    dry_run = is_dry_run()

    event = event if isinstance(event, dict) else {}
    claims, reason = caller_claims(event, os.environ["CLASS_PHOTO_APP_CLIENT_ID"])
    if claims is None:
        logger.warning("Rejected caller: %s", reason)
        return _error(403, FORBIDDEN_ERROR)

    route = (event.get("httpMethod"), event.get("resource"))
    logger.info("%s %s from sub %s (dry run: %s)", route[0], route[1], claims["sub"], dry_run)
    try:
        if route == CLASSES_ROUTE:
            return handle_classes(dry_run)
        if route == SUBMIT_ROUTE:
            return handle_submit(event, context, claims["cognito:username"], dry_run)
        return _error(404, NOT_FOUND_ERROR)
    except Refusal as refusal:
        logger.info("Answered %d: %s", refusal.status, refusal.reason)
        return _error(refusal.status, refusal.message)
    except Exception as e:
        # Where it failed, without the exception's text (which can carry values).
        frame = traceback.extract_tb(e.__traceback__)[-1]
        logger.error(
            "Unexpected %s at %s:%s in %s while handling %s %s",
            type(e).__name__,
            Path(frame.filename).name,
            frame.lineno,
            frame.name,
            route[0],
            route[1],
        )
        return _error(500, GENERIC_ERROR)
