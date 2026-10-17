import base64
import copy
import datetime
import importlib
import json
import re
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from moto import mock_aws

import boto3
import pytest
from common.github_app import GitHubConflict, GitHubError
from common.neoncrm import NeonCRMError

from functions.classes.class_photo_upload_api import lambda_function, photo_checks, submission
from functions.classes.class_photo_upload_api.class_list_cache import ClassListRecord, ListSource
from functions.classes.class_photo_upload_api.dynamodb_class_list_cache import DynamoDBClassListCache
from functions.classes.class_photo_upload_api.submission import (
    ACTION_OPENED,
    ACTION_UPDATED,
    RepoConfig,
    SubmissionConflict,
    SubmissionPlan,
    SubmissionResult,
)
from functions.classes.class_photo_upload_api.tests.fake_class_list_cache import InMemoryClassListCache
from functions.classes.class_photo_upload_api.tests.jpeg_builder import make_jpeg

MODULE = "functions.classes.class_photo_upload_api.lambda_function"
FIXTURES = Path(__file__).parent / "fixtures"

CLIENT_ID = "fake-app-client-id"
USERNAME = "staff-user-USERMARKER"
SUB = "11111111-2222-3333-4444-555555555555"
TOKEN = "ghs_FAKETOKENMARKER"
KEY_MARKER = "KEYMARKER"
PRIVATE_KEY = f"-----BEGIN RSA PRIVATE KEY-----\n{KEY_MARKER}\n-----END RSA PRIVATE KEY-----\n"
APP_SECRET = {"app_id": "1234567", "installation_id": "87654321", "private_key": PRIVATE_KEY}
CONFIG = {
    "repo_owner": "asmbly-makerspace",
    "repo_name": "asmbly-classes",
    "base_branch": "main",
    "images_dir": "app/src/lib/images",
    "branch_prefix": "class-photo/",
    "image_extensions": ["avif", "gif", "heif", "jpeg", "jpg", "png", "tiff", "webp"],
}
ENV = {
    "NEON_SECRET_NAME": "prod/neon_token",
    "GITHUB_APP_SECRET_NAME": "github/class-photo-upload-app",
    "CLASS_PHOTO_CONFIG_PARAM_NAME": "/stage/config/class-photo-upload",
    "CLASS_PHOTO_APP_CLIENT_ID": CLIENT_ID,
    "CLASS_PHOTO_DRY_RUN": "true",
    "CLASS_CACHE_TABLE_NAME": "ClassPhotoClassListCache-test",
}
CLASS_NAME = "Ceramics: Glazing Workshop"
NEON_EVENTS = [
    {"Event ID": "1", "Event Name": "Ceramics: Glazing Workshop w/ Pat"},
    {"Event ID": "2", "Event Name": "Woodshop Safety"},
    {"Event ID": "3", "Event Name": "AC/DC Basics w/ X"},
    {"Event ID": "4", "Event Name": "A-B Basics"},
    {"Event ID": "5", "Event Name": "A B Basics"},
]
FILE_PATH = "app/src/lib/images/Ceramics__Glazing_Workshop.jpg"
PR_URL = "https://github.com/asmbly-makerspace/asmbly-classes/pull/12"


class FakeContext:
    def __init__(self, remaining_ms: int = 20_000) -> None:
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self) -> int:
        return self.remaining_ms


def _event(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def classes_event() -> dict[str, Any]:
    return _event("api_event_classes.json")


def submit_event(class_name: str = CLASS_NAME, photo: bytes | None = None, **fields: Any) -> dict[str, Any]:
    event = _event("api_event_submit.json")
    data = photo if photo is not None else make_jpeg(1500, 1000)
    body = {"class_name": class_name, "photo_base64": base64.b64encode(data).decode("ascii"), **fields}
    event["body"] = json.dumps(body)
    return event


def body_of(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["body"])


def make_plan(open_pull_request: dict[str, Any] | None = None) -> SubmissionPlan:
    return SubmissionPlan(
        class_name=CLASS_NAME,
        file_path=FILE_PATH,
        replaces_existing=True,
        removed_paths=["app/src/lib/images/Ceramics_Glazing_Workshop.jpg"],
        branch="class-photo/ceramics-glazing-workshop-0123abcd",
        branch_sha="b" * 40 if open_pull_request else None,
        base_sha="a" * 40,
        open_pull_request=open_pull_request,
        title="Class photo: Ceramics: Glazing Workshop",
        body="Class: `Ceramics: Glazing Workshop`",
        warnings=["a warning"],
    )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> InMemoryClassListCache:
    """The handler's cache for this test: in memory, empty (so a request reads Neon, as before)."""
    cache = InMemoryClassListCache()
    monkeypatch.setattr(lambda_function, "_class_list_cache", cache)
    return cache


@pytest.fixture
def mocks(env: None, fake_cache: InMemoryClassListCache) -> Any:
    """aws, NeonCRM, github_app and the submission calls, patched where the handler uses them."""
    with (
        patch(f"{MODULE}.aws") as aws,
        patch(f"{MODULE}.NeonCRM") as neon_class,
        patch(f"{MODULE}.github_app") as github_app,
        patch.object(submission, "plan_submission") as plan_submission,
        patch.object(submission, "apply_submission") as apply_submission,
    ):
        aws.get_secret.side_effect = lambda name, key: {"NEON_ORG_ID": "org", "NEON_API_KEY": "neonkey"}[key]
        aws.get_json_parameter.return_value = copy.deepcopy(CONFIG)
        aws.get_secret_json.return_value = dict(APP_SECRET)
        neon_class.return_value.search_events.return_value = list(NEON_EVENTS)
        github_app.installation_token.return_value = TOKEN
        plan_submission.return_value = make_plan()
        apply_submission.return_value = SubmissionResult(
            action=ACTION_OPENED, pull_request={"number": 12, "html_url": PR_URL}, plan=make_plan()
        )
        yield MagicMock(
            aws=aws,
            neon=neon_class,
            github_app=github_app,
            plan_submission=plan_submission,
            apply_submission=apply_submission,
            cache=fake_cache,
        )


def assert_nothing_outside_called(mocks: Any) -> None:
    mocks.neon.assert_not_called()
    mocks.github_app.installation_token.assert_not_called()
    mocks.plan_submission.assert_not_called()
    mocks.apply_submission.assert_not_called()


def assert_json_headers(response: dict[str, Any]) -> None:
    assert response["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert response["headers"]["Cache-Control"] == "no-store"


# --- Environment and caller ---


@pytest.mark.parametrize("missing", lambda_function.REQUIRED_ENV)
def test_missing_env_returns_500(mocks: Any, monkeypatch: pytest.MonkeyPatch, missing: str, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv(missing)

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    for value in ENV.values():
        assert value not in response["body"]
    assert f"Missing environment variable {missing}" in caplog.text
    assert_nothing_outside_called(mocks)


def _with_claims(event: dict[str, Any], **changes: Any) -> dict[str, Any]:
    claims = event["requestContext"]["authorizer"]["claims"]
    for key, value in changes.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    return event


def assert_forbidden(response: dict[str, Any], mocks: Any) -> None:
    assert response["statusCode"] == 403
    assert body_of(response) == {"error": lambda_function.FORBIDDEN_ERROR}
    mocks.aws.get_secret.assert_not_called()
    mocks.aws.get_secret_json.assert_not_called()
    mocks.aws.get_json_parameter.assert_not_called()
    assert_nothing_outside_called(mocks)


@pytest.mark.parametrize("make_event", [classes_event, submit_event])
def test_wrong_audience_returns_403_and_calls_nothing(mocks: Any, make_event: Any, caplog: pytest.LogCaptureFixture) -> None:
    event = _with_claims(make_event(), aud="another-client-SECRETAUD")

    with caplog.at_level(logging.INFO):
        response = lambda_function.lambda_handler(event, FakeContext())

    assert_forbidden(response, mocks)
    assert "Rejected caller: audience" in caplog.text
    assert "SECRETAUD" not in caplog.text


def test_access_token_returns_403(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    event = _with_claims(submit_event(), token_use="access")

    with caplog.at_level(logging.INFO):
        response = lambda_function.lambda_handler(event, FakeContext())

    assert_forbidden(response, mocks)
    assert "Rejected caller: token_use" in caplog.text


@pytest.mark.parametrize(
    "change",
    [{"sub": None}, {"sub": ""}, {"cognito:username": None}, {"cognito:username": "  "}, {"aud": None}, {"aud": 5}],
)
def test_missing_claims_returns_403(mocks: Any, change: dict[str, Any]) -> None:
    response = lambda_function.lambda_handler(_with_claims(submit_event(), **change), FakeContext())

    assert_forbidden(response, mocks)


@pytest.mark.parametrize("request_context", [None, {}, {"authorizer": None}, {"authorizer": {"claims": "x"}}])
def test_no_authorizer_claims_returns_403(mocks: Any, request_context: Any) -> None:
    event = submit_event()
    event["requestContext"] = request_context

    response = lambda_function.lambda_handler(event, FakeContext())

    assert_forbidden(response, mocks)


def test_non_ascii_audience_is_refused_not_an_error(mocks: Any) -> None:
    response = lambda_function.lambda_handler(_with_claims(classes_event(), aud="clïent"), FakeContext())

    assert_forbidden(response, mocks)


@pytest.mark.parametrize(
    "method, resource",
    [("POST", "/class-photo-upload/classes"), ("GET", "/class-photo-upload/submit"), ("GET", "/other"), (None, None)],
)
def test_unknown_route_returns_404(mocks: Any, method: Any, resource: Any) -> None:
    event = classes_event()
    event["httpMethod"] = method
    event["resource"] = resource

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 404
    assert body_of(response) == {"error": "Not found."}
    assert_nothing_outside_called(mocks)


# --- Class list ---


def test_classes_returns_names_problems_and_warnings(mocks: Any) -> None:
    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 200
    assert_json_headers(response)
    payload = body_of(response)
    assert payload["dry_run"] is True
    by_name = {entry["name"]: entry for entry in payload["classes"]}
    assert [entry["name"] for entry in payload["classes"]] == [
        "A B Basics",
        "A-B Basics",
        "AC/DC Basics",
        "Ceramics: Glazing Workshop",
        "Woodshop Safety",
    ]
    assert by_name["Ceramics: Glazing Workshop"] == {
        "name": "Ceramics: Glazing Workshop",
        "file_name": "Ceramics__Glazing_Workshop.jpg",
        "problem": None,
        "warning": None,
    }
    assert by_name["AC/DC Basics"]["file_name"] is None
    assert '"/"' in by_name["AC/DC Basics"]["problem"]
    assert by_name["AC/DC Basics"]["warning"] is None
    assert by_name["A-B Basics"]["file_name"] == "A-B_Basics.jpg"
    assert by_name["A-B Basics"]["warning"] == (
        'Another class, "A B Basics", matches the same photo on the class list. '
        "Both classes will show this photo there."
    )
    assert '"A-B Basics"' in by_name["A B Basics"]["warning"]
    mocks.neon.assert_called_once_with("org", "neonkey")
    search = mocks.neon.return_value.search_events
    assert search.call_args.kwargs == {"timeout": 4.0, "max_pages": 8}
    mocks.github_app.installation_token.assert_not_called()
    assert payload["stale"] is False
    assert payload["refresh"] is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", payload["refreshed_at"])


def test_classes_reports_prod_as_not_a_dry_run(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")

    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert body_of(response)["dry_run"] is False


def test_classes_neon_failure_returns_502_without_details(mocks: Any) -> None:
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": "Couldn't load the class list. Try again in a minute."}
    assert "500" not in response["body"]


def test_classes_secret_failure_returns_502(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    mocks.aws.get_secret.side_effect = KeyError("Key 'NEON_API_KEY' not found in secret 'prod/neon_token'")

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": lambda_function.NEON_ERROR}
    assert "Couldn't read the Neon secret: KeyError" in caplog.text
    mocks.neon.assert_not_called()


# --- The class list cache (class-photo-loading phase 1) ---

CACHED_NAMES = ("Ceramics: Glazing Workshop", "Woodshop Safety")


def cached_copy(age: datetime.timedelta, source: ListSource = ListSource.SCHEDULE) -> ClassListRecord:
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return ClassListRecord(CACHED_NAMES, now - age, source)


def refresh_event(value: Any = "1") -> dict[str, Any]:
    event = classes_event()
    event["queryStringParameters"] = {"refresh": value}
    return event


def scheduled_event() -> dict[str, Any]:
    return json.loads((FIXTURES / "scheduled_event.json").read_text())


def test_classes_second_call_is_served_from_cache(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        first = body_of(lambda_function.lambda_handler(classes_event(), FakeContext()))
        second = body_of(lambda_function.lambda_handler(classes_event(), FakeContext()))

    assert mocks.neon.return_value.search_events.call_count == 1
    assert second["classes"] == first["classes"]
    assert second["refreshed_at"] == first["refreshed_at"]
    assert re.search(r"Class list from neon \(age [01] s\): 5 classes", caplog.text)
    assert "Class list from cache (age " in caplog.text
    assert mocks.cache.puts[0].source is ListSource.LIVE_READ


def test_classes_fresh_cache_reads_no_neon_secret(mocks: Any) -> None:
    mocks.cache.record = cached_copy(datetime.timedelta(hours=25))

    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 200
    assert [entry["name"] for entry in body_of(response)["classes"]] == list(CACHED_NAMES)
    assert body_of(response)["stale"] is False
    mocks.aws.get_secret.assert_not_called()
    mocks.neon.assert_not_called()


def test_classes_cached_list_survives_neon_failure(mocks: Any) -> None:
    mocks.cache.record = cached_copy(datetime.timedelta(hours=27))
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 200
    payload = body_of(response)
    assert [entry["name"] for entry in payload["classes"]] == list(CACHED_NAMES)
    assert payload["stale"] is True
    assert payload["refresh"] is None
    assert payload["refreshed_at"] == lambda_function.format_time(mocks.cache.record.refreshed_at)


def test_classes_neon_failure_without_cache_returns_502(mocks: Any) -> None:
    assert mocks.cache.record is None
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    response = lambda_function.lambda_handler(classes_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": lambda_function.NEON_ERROR}
    assert mocks.cache.puts == []


def test_classes_logs_neon_time(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        lambda_function.lambda_handler(classes_event(), FakeContext())

    assert "Neon read 5 events (1 pages) in " in caplog.text
    assert " ms: 5 classes" in caplog.text


def test_classes_neon_failure_logs_elapsed_time(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    with caplog.at_level(logging.ERROR):
        lambda_function.lambda_handler(classes_event(), FakeContext())

    assert re.search(r"Couldn't read the class list from Neon after \d+ ms: NeonCRMError", caplog.text)


def test_classes_refresh_reads_neon_and_logs_sub(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    mocks.cache.record = cached_copy(datetime.timedelta(minutes=10))

    with caplog.at_level(logging.INFO):
        response = lambda_function.lambda_handler(refresh_event(), FakeContext())

    payload = body_of(response)
    assert response["statusCode"] == 200
    assert payload["refresh"] == "refreshed"
    assert payload["stale"] is False
    assert len(payload["classes"]) == 5
    mocks.neon.return_value.search_events.assert_called_once()
    assert mocks.cache.record.source is ListSource.MANUAL_REFRESH
    assert f"Class list refresh by sub {SUB}: refreshed" in caplog.text
    assert "USERMARKER" not in caplog.text


def test_classes_refresh_twice_in_a_minute_is_too_soon(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        first = body_of(lambda_function.lambda_handler(refresh_event(), FakeContext()))
        second = body_of(lambda_function.lambda_handler(refresh_event(), FakeContext()))

    assert first["refresh"] == "refreshed"
    assert second["refresh"] == "too_soon"
    assert second["stale"] is False
    assert second["classes"] == first["classes"]
    assert mocks.neon.return_value.search_events.call_count == 1
    assert f"Class list refresh by sub {SUB}: too_soon" in caplog.text


def test_classes_refresh_neon_failure_serves_copy_stale(mocks: Any) -> None:
    mocks.cache.record = cached_copy(datetime.timedelta(minutes=10))
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    response = lambda_function.lambda_handler(refresh_event(), FakeContext())

    payload = body_of(response)
    assert response["statusCode"] == 200
    assert payload["refresh"] == "failed"
    assert payload["stale"] is True
    assert [entry["name"] for entry in payload["classes"]] == list(CACHED_NAMES)


def test_classes_refresh_without_copy_and_neon_failure_returns_502(mocks: Any) -> None:
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    response = lambda_function.lambda_handler(refresh_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": lambda_function.NEON_ERROR}


@pytest.mark.parametrize("parameters", [{"refresh": "0"}, {"refresh": "true"}, {"refresh": ""}, {}, None])
def test_classes_refresh_param_other_values_are_a_normal_load(mocks: Any, parameters: Any) -> None:
    mocks.cache.record = cached_copy(datetime.timedelta(minutes=10))
    event = classes_event()
    event["queryStringParameters"] = parameters

    payload = body_of(lambda_function.lambda_handler(event, FakeContext()))

    assert payload["refresh"] is None
    mocks.neon.assert_not_called()


def test_classes_refresh_needs_claims(mocks: Any) -> None:
    event = _with_claims(refresh_event(), aud=None)

    response = lambda_function.lambda_handler(event, FakeContext())

    assert_forbidden(response, mocks)
    assert mocks.cache.gets == 0
    assert mocks.cache.puts == []


def test_scheduled_event_refreshes_cache_without_github(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler(scheduled_event(), FakeContext())

    assert result == {"refreshed": True}
    assert mocks.cache.record is not None
    assert mocks.cache.record.source is ListSource.SCHEDULE
    assert len(mocks.cache.record.names) == 5
    mocks.github_app.installation_token.assert_not_called()
    mocks.aws.get_secret_json.assert_not_called()
    mocks.aws.get_json_parameter.assert_not_called()
    mocks.plan_submission.assert_not_called()
    assert "Scheduled class list refresh: done" in caplog.text


def test_scheduled_refresh_neon_failure_keeps_cache(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    old = cached_copy(datetime.timedelta(hours=3))
    mocks.cache.record = old
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler(scheduled_event(), FakeContext())

    assert result == {"refreshed": False}
    assert mocks.cache.record is old
    assert "Scheduled class list refresh failed (Refusal); kept the cached list, 180 minutes old" in caplog.text
    assert "Scheduled class list refresh: kept the cached list" in caplog.text


def test_scheduled_refresh_unexpected_error_returns_normally(
    mocks: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenService:
        def refresh_on_schedule(self) -> bool:
            raise RuntimeError("secret detail")

    monkeypatch.setattr(lambda_function, "class_list_service", BrokenService)

    with caplog.at_level(logging.INFO):
        result = lambda_function.lambda_handler(scheduled_event(), FakeContext())

    assert result == {"refreshed": False}
    assert "Scheduled class list refresh failed: RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text


def test_http_event_with_scheduled_keys_still_needs_claims(mocks: Any) -> None:
    event = _with_claims(classes_event(), aud=None)
    event["source"] = "aws.events"
    event["detail-type"] = "Scheduled Event"

    response = lambda_function.lambda_handler(event, FakeContext())

    assert_forbidden(response, mocks)
    assert mocks.cache.gets == 0
    assert mocks.cache.puts == []


def test_scheduled_refresh_logs_no_names(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        lambda_function.lambda_handler(scheduled_event(), FakeContext())

    for event in NEON_EVENTS:
        assert event["Event Name"] not in caplog.text
    for name in ("Glazing", "Woodshop", "Pat", "USERMARKER", "neonkey", TOKEN):
        assert name not in caplog.text


def test_default_cache_is_the_dynamodb_table_from_env(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lambda_function, "_class_list_cache", None)
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-2").create_table(
            TableName=ENV["CLASS_CACHE_TABLE_NAME"],
            AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )

        first = lambda_function.lambda_handler(classes_event(), FakeContext())
        cache = lambda_function.class_list_cache()
        second = lambda_function.lambda_handler(classes_event(), FakeContext())

        assert isinstance(cache, DynamoDBClassListCache)
        assert lambda_function.class_list_cache() is cache
        assert first["statusCode"] == second["statusCode"] == 200
        assert mocks.neon.return_value.search_events.call_count == 1
        stored = cache.get()
        assert stored is not None and stored.source is ListSource.LIVE_READ


# --- Submit: the request ---


def test_submit_invalid_json_400(mocks: Any) -> None:
    event = submit_event()
    event["body"] = "{not json"

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": lambda_function.BAD_REQUEST_ERROR}
    assert_nothing_outside_called(mocks)


@pytest.mark.parametrize(
    "body",
    [
        None,
        "[]",
        "null",
        json.dumps({"photo_base64": "aGk="}),
        json.dumps({"class_name": CLASS_NAME}),
        json.dumps({"class_name": 5, "photo_base64": "aGk="}),
        json.dumps({"class_name": CLASS_NAME, "photo_base64": ["aGk="]}),
    ],
)
def test_submit_missing_fields_400(mocks: Any, body: Any) -> None:
    event = submit_event()
    event["body"] = body

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": lambda_function.BAD_REQUEST_ERROR}
    assert_nothing_outside_called(mocks)


@pytest.mark.parametrize("class_name", ["", "x" * 201])
def test_submit_class_name_out_of_range_400(mocks: Any, class_name: str) -> None:
    response = lambda_function.lambda_handler(submit_event(class_name=class_name), FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": "Pick a class from the list."}
    assert_nothing_outside_called(mocks)


@pytest.mark.parametrize("photo_base64", ["not base64!", "aGk", "aG k="])
def test_submit_bad_base64_400(mocks: Any, photo_base64: str) -> None:
    event = submit_event()
    event["body"] = json.dumps({"class_name": CLASS_NAME, "photo_base64": photo_base64})

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": lambda_function.BAD_REQUEST_ERROR}
    assert_nothing_outside_called(mocks)


def test_submit_base64_encoded_event_body(mocks: Any) -> None:
    event = submit_event()
    event["body"] = base64.b64encode(event["body"].encode("utf-8")).decode("ascii")
    event["isBase64Encoded"] = True

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 200
    assert mocks.plan_submission.call_args.args[2] == CLASS_NAME


def test_submit_base64_encoded_event_body_that_is_not_base64_400(mocks: Any) -> None:
    event = submit_event()
    event["isBase64Encoded"] = True

    response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": lambda_function.BAD_REQUEST_ERROR}


def test_submit_oversized_refused_before_decode(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    event = submit_event()
    event["body"] = json.dumps({"class_name": CLASS_NAME, "photo_base64": "A" * (6 * 1024 * 1024)})

    with patch(f"{MODULE}.base64.b64decode") as b64decode, caplog.at_level(logging.INFO):
        response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": photo_checks.too_big_message(6 * 1024 * 1024 * 3 // 4)}
    assert "4.5 MB" in body_of(response)["error"]
    b64decode.assert_not_called()
    assert "photo:size" in caplog.text
    assert_nothing_outside_called(mocks)


def test_largest_allowed_photo_is_decoded(mocks: Any) -> None:
    photo = make_jpeg(1500, 1000, pad_to=photo_checks.MAX_PHOTO_BYTES)

    response = lambda_function.lambda_handler(submit_event(photo=photo), FakeContext())

    assert response["statusCode"] == 200


def test_photo_one_byte_too_big_gets_the_size_message(mocks: Any) -> None:
    photo = make_jpeg(1500, 1000, pad_to=photo_checks.MAX_PHOTO_BYTES + 1)

    response = lambda_function.lambda_handler(submit_event(photo=photo), FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": photo_checks.too_big_message(photo_checks.MAX_PHOTO_BYTES + 1)}
    assert_nothing_outside_called(mocks)


@pytest.mark.parametrize(
    "photo, kind",
    [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "not_jpeg"),
        (make_jpeg(1600, 1200), "ratio"),
        (make_jpeg(1000, 1500), "not_landscape"),
        (make_jpeg(1500, 1000, orientation=6), "not_landscape"),
        (make_jpeg(1500, 1000, exif_gps=True), "location"),
        (make_jpeg(1500, 1000, xmp_gps=True), "location"),
    ],
    ids=["png", "4:3", "portrait", "orientation-6", "exif-gps", "xmp-gps"],
)
def test_submit_bad_photo_400_and_nothing_called(
    mocks: Any, photo: bytes, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        response = lambda_function.lambda_handler(submit_event(photo=photo), FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": photo_checks.check_photo(photo)}
    assert f"photo:{kind}" in caplog.text
    mocks.aws.get_secret.assert_not_called()
    assert_nothing_outside_called(mocks)


def test_photo_problem_kind_names_every_message() -> None:
    kinds = {
        photo_checks.too_big_message(5_000_000): "size",
        photo_checks.NOT_JPEG_MESSAGE: "not_jpeg",
        photo_checks.UNREADABLE_JPEG_MESSAGE: "unreadable",
        photo_checks.LOCATION_MESSAGE: "location",
        photo_checks.WRONG_RATIO_MESSAGE.format(width=4, height=3, ratio="4:3", example="x"): "ratio",
        photo_checks.NOT_LANDSCAPE_MESSAGE.format(width=3, height=4, ratio="3:4", example="x"): "not_landscape",
        "something new": "other",
    }

    assert {message: lambda_function.photo_problem_kind(message) for message in kinds} == kinds


# --- Submit: the class ---


def test_submit_class_not_in_list_400(mocks: Any) -> None:
    response = lambda_function.lambda_handler(submit_event(class_name="Not A Class"), FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {"error": "Pick a class from the list."}
    mocks.github_app.installation_token.assert_not_called()
    mocks.aws.get_secret_json.assert_not_called()


def test_submit_forbidden_character_400(mocks: Any) -> None:
    response = lambda_function.lambda_handler(submit_event(class_name="AC/DC Basics"), FakeContext())

    assert response["statusCode"] == 400
    assert body_of(response) == {
        "error": 'The class name "AC/DC Basics" contains "/", which can\'t be in a file name. '
        "Rename the class in Neon first."
    }
    mocks.github_app.installation_token.assert_not_called()


def test_submit_neon_failure_returns_502(mocks: Any) -> None:
    mocks.neon.return_value.search_events.side_effect = NeonCRMError("events/search failed (no response)")

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": lambda_function.NEON_ERROR}
    mocks.github_app.installation_token.assert_not_called()


# --- Submit: GitHub ---


def test_submit_prod_opens_pull_request(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")
    photo = make_jpeg(1500, 1000)

    response = lambda_function.lambda_handler(submit_event(photo=photo), FakeContext())

    assert response["statusCode"] == 200
    assert_json_headers(response)
    mocks.github_app.installation_token.assert_called_once_with(
        "1234567",
        "87654321",
        PRIVATE_KEY.strip(),
        "asmbly-classes",
        {"contents": "write", "pull_requests": "write"},
        timeout=5.0,
    )
    mocks.github_app.GitHubRepo.assert_called_once_with(
        TOKEN, "asmbly-makerspace", "asmbly-classes", "class-photo/", timeout=5.0
    )
    repo = mocks.github_app.GitHubRepo.return_value
    config = RepoConfig.from_dict(CONFIG)
    classes = ["A B Basics", "A-B Basics", "AC/DC Basics", CLASS_NAME, "Woodshop Safety"]
    mocks.plan_submission.assert_called_once_with(repo, config, CLASS_NAME, classes, USERNAME)
    mocks.apply_submission.assert_called_once_with(
        repo, config, make_plan(), base64.b64encode(photo).decode("ascii"), USERNAME
    )
    assert body_of(response) == {
        "dry_run": False,
        "action": "opened",
        "pull_request": {"number": 12, "url": PR_URL},
        "file_path": FILE_PATH,
        "replaces_existing": True,
        "removed_paths": ["app/src/lib/images/Ceramics_Glazing_Workshop.jpg"],
        "title": "Class photo: Ceramics: Glazing Workshop",
        "body": "Class: `Ceramics: Glazing Workshop`",
        "warnings": ["a warning"],
    }


def test_submit_prod_repeat_returns_updated(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")
    open_pull_request = {"number": 12, "html_url": PR_URL}
    mocks.plan_submission.return_value = make_plan(open_pull_request)
    mocks.apply_submission.return_value = SubmissionResult(
        action=ACTION_UPDATED, pull_request=open_pull_request, plan=make_plan(open_pull_request)
    )

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 200
    assert body_of(response)["action"] == "updated"
    assert body_of(response)["pull_request"] == {"number": 12, "url": PR_URL}


def test_submit_dry_run_uses_read_only_token_and_never_applies(mocks: Any) -> None:
    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 200
    assert mocks.github_app.installation_token.call_args.args[4] == {
        "contents": "read",
        "pull_requests": "read",
    }
    mocks.apply_submission.assert_not_called()
    payload = body_of(response)
    assert payload["dry_run"] is True
    assert payload["action"] == "would_open"
    assert payload["pull_request"] is None
    assert payload["file_path"] == FILE_PATH
    assert payload["removed_paths"] == ["app/src/lib/images/Ceramics_Glazing_Workshop.jpg"]
    assert payload["title"] == "Class photo: Ceramics: Glazing Workshop"
    assert payload["body"] == "Class: `Ceramics: Glazing Workshop`"


def test_submit_dry_run_with_open_pull_request_would_update(mocks: Any) -> None:
    mocks.plan_submission.return_value = make_plan({"number": 7, "html_url": PR_URL})

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    payload = body_of(response)
    assert payload["action"] == "would_update"
    assert payload["pull_request"] == {"number": 7, "url": PR_URL}
    mocks.apply_submission.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "TRUE", "no", "False ", " false"])
def test_dry_run_is_default(mocks: Any, monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("CLASS_PHOTO_DRY_RUN")
    else:
        monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", value)

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    # Only "false" (any case, trimmed) turns the dry run off.
    expected_dry_run = value is None or value.strip().lower() != "false"
    assert body_of(response)["dry_run"] is expected_dry_run
    assert (mocks.apply_submission.call_count == 0) is expected_dry_run


@pytest.mark.parametrize("value", ["", "TRUE", "no", "yes", "0"])
def test_values_other_than_false_are_dry_runs(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", value)

    assert lambda_function.is_dry_run() is True


@pytest.mark.parametrize(
    "failing, error",
    [
        ("installation_token", GitHubError("installation_token", 500)),
        ("plan_submission", GitHubError("list_directory", None)),
        ("apply_submission", GitHubConflict("create_pull_request", 422)),
        ("apply_submission", GitHubError("create_blob", 502)),
    ],
)
def test_submit_github_error_502_without_details(
    mocks: Any, monkeypatch: pytest.MonkeyPatch, failing: str, error: GitHubError
) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")
    target = mocks.github_app.installation_token if failing == "installation_token" else getattr(mocks, failing)
    target.side_effect = error

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": "Couldn't open the pull request. Try again in a minute."}
    assert error.operation not in response["body"]


def test_submit_conflict_409(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")
    mocks.apply_submission.side_effect = SubmissionConflict()

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 409
    assert body_of(response) == {"error": "Someone else just submitted a photo for this class. Try again."}


def test_submit_with_too_little_time_left_writes_nothing(mocks: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(submit_event(), FakeContext(remaining_ms=7_999))

    assert response["statusCode"] == 502
    assert body_of(response) == {"error": lambda_function.GITHUB_ERROR}
    mocks.plan_submission.assert_called_once()
    mocks.apply_submission.assert_not_called()
    assert "Not enough time left to write: 7999 ms" in caplog.text


def test_submit_without_a_context_clock_still_writes(mocks: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")

    response = lambda_function.lambda_handler(submit_event(), None)

    assert response["statusCode"] == 200
    mocks.apply_submission.assert_called_once()


@pytest.mark.parametrize("missing", ["app_id", "installation_id", "private_key"])
def test_github_secret_missing_key_500(mocks: Any, missing: str, caplog: pytest.LogCaptureFixture) -> None:
    secret = dict(APP_SECRET)
    del secret[missing]
    mocks.aws.get_secret_json.return_value = secret

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    assert f"The GitHub App secret has no string {missing}" in caplog.text
    assert KEY_MARKER not in caplog.text
    mocks.github_app.installation_token.assert_not_called()


@pytest.mark.parametrize("secret", [["not", "an", "object"], {"app_id": 1234567, "installation_id": "1", "private_key": "k"}])
def test_github_secret_malformed_500(mocks: Any, secret: Any) -> None:
    mocks.aws.get_secret_json.return_value = secret

    response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    mocks.github_app.installation_token.assert_not_called()


def test_github_secret_unreadable_500(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    mocks.aws.get_secret_json.side_effect = RuntimeError(f"boom {KEY_MARKER}")

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    assert "Couldn't read the GitHub App secret: RuntimeError" in caplog.text
    assert KEY_MARKER not in caplog.text


@pytest.mark.parametrize(
    "config, logged",
    [
        ({**CONFIG, "branch_prefix": "class-photo"}, "branch_prefix"),
        ({key: value for key, value in CONFIG.items() if key != "repo_name"}, "repo_name"),
    ],
)
def test_invalid_config_500(mocks: Any, config: dict[str, Any], logged: str, caplog: pytest.LogCaptureFixture) -> None:
    mocks.aws.get_json_parameter.return_value = config

    with caplog.at_level(logging.ERROR):
        response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    assert logged in caplog.text
    mocks.aws.get_json_parameter.assert_called_once_with("/stage/config/class-photo-upload")
    mocks.github_app.installation_token.assert_not_called()


def test_unexpected_error_500_without_its_text(mocks: Any, caplog: pytest.LogCaptureFixture) -> None:
    mocks.plan_submission.side_effect = ValueError(f"unexpected {KEY_MARKER}")

    with caplog.at_level(logging.DEBUG):
        response = lambda_function.lambda_handler(submit_event(), FakeContext())

    assert response["statusCode"] == 500
    assert body_of(response) == {"error": lambda_function.GENERIC_ERROR}
    assert "Unexpected ValueError at " in caplog.text
    assert "while handling POST /class-photo-upload/submit" in caplog.text
    assert KEY_MARKER not in caplog.text
    assert KEY_MARKER not in response["body"]


def test_logs_hold_no_username_token_or_photo(mocks: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("CLASS_PHOTO_DRY_RUN", "false")
    event = submit_event(photo=make_jpeg(1500, 1000, pad_to=4096))
    photo_base64 = json.loads(event["body"])["photo_base64"]

    with caplog.at_level(logging.DEBUG):
        response = lambda_function.lambda_handler(event, FakeContext())

    assert response["statusCode"] == 200
    assert SUB in caplog.text
    assert CLASS_NAME in caplog.text
    assert "USERMARKER" not in caplog.text
    assert KEY_MARKER not in caplog.text
    assert TOKEN not in caplog.text
    assert "AUTHMARKER" not in caplog.text
    assert photo_base64[100:160] not in caplog.text


def test_handler_imports_as_top_level_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under Lambda the function's folder is on the path and there is no parent package."""
    folder = Path(lambda_function.__file__).parent
    monkeypatch.syspath_prepend(str(folder))
    names = (
        "lambda_function",
        "class_names",
        "photo_checks",
        "submission",
        "class_list_cache",
        "class_list_freshness",
        "class_list_service",
        "dynamodb_class_list_cache",
    )
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        module = importlib.import_module("lambda_function")

        assert module.__name__ == "lambda_function"
        assert module.class_names.__name__ == "class_names"
        assert module.photo_checks.__name__ == "photo_checks"
        assert module.submission.__name__ == "submission"
        assert module.submission.class_names is module.class_names
        assert module.ClassListService.__module__ == "class_list_service"
        assert module.DynamoDBClassListCache.__module__ == "dynamodb_class_list_cache"
        service_module = sys.modules["class_list_service"]
        assert service_module.ClassListRecord is sys.modules["class_list_cache"].ClassListRecord
        assert service_module.FreshnessPolicy is sys.modules["class_list_freshness"].FreshnessPolicy
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
