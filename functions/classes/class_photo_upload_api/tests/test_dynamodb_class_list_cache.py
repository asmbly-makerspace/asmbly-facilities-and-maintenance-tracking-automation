"""The DynamoDB implementation of the class-list cache, against moto (no network)."""

import datetime
import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import NoRegionError
from moto import mock_aws

from functions.classes.class_photo_upload_api.class_list_cache import (
    CacheUnavailable,
    ClassListRecord,
    ListSource,
)
from functions.classes.class_photo_upload_api.dynamodb_class_list_cache import (
    CACHE_KEY,
    DynamoDBClassListCache,
    default_client,
)

TABLE_NAME = "ClassPhotoClassListCache-test"
NOW = datetime.datetime(2026, 10, 17, 14, 5, tzinfo=datetime.timezone.utc)
RECORD = ClassListRecord(("Ceramics: Glazing Workshop", "Woodshop Safety"), NOW, ListSource.SCHEDULE)
GOOD_ITEM = {
    "cache_key": {"S": CACHE_KEY},
    "version": {"N": "1"},
    "classes": {"S": json.dumps(["Secret Class Name"])},
    "class_count": {"N": "1"},
    "refreshed_at": {"S": "2026-10-17T14:05:00Z"},
    "source": {"S": "live_read"},
}


@pytest.fixture
def dynamodb(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    # Another test module sets AWS_REGION at import; the cache's client reads it.
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-2")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


def test_get_empty_table_is_none(dynamodb: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        assert DynamoDBClassListCache(TABLE_NAME).get() is None
    assert "Class list cache: empty" in caplog.text


def test_put_then_get_round_trips(dynamodb: Any) -> None:
    cache = DynamoDBClassListCache(TABLE_NAME)

    cache.put(RECORD)

    assert DynamoDBClassListCache(TABLE_NAME).get() == RECORD


def test_item_has_exactly_six_attributes(dynamodb: Any) -> None:
    DynamoDBClassListCache(TABLE_NAME).put(RECORD)

    item = dynamodb.get_item(TableName=TABLE_NAME, Key={"cache_key": {"S": CACHE_KEY}})["Item"]

    assert item == {
        "cache_key": {"S": "class-list"},
        "version": {"N": "1"},
        "classes": {"S": json.dumps(["Ceramics: Glazing Workshop", "Woodshop Safety"])},
        "class_count": {"N": "2"},
        "refreshed_at": {"S": "2026-10-17T14:05:00Z"},
        "source": {"S": "schedule"},
    }


def test_put_replaces_the_item(dynamodb: Any) -> None:
    cache = DynamoDBClassListCache(TABLE_NAME)
    cache.put(RECORD)
    newer = ClassListRecord(("Intro to Forging",), NOW + datetime.timedelta(hours=1), ListSource.MANUAL_REFRESH)

    cache.put(newer)

    assert cache.get() == newer
    assert dynamodb.scan(TableName=TABLE_NAME)["Count"] == 1


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"version": {"N": "2"}}, "version"),
        ({"version": {"S": "1"}}, "version"),
        ({"classes": {"S": "not json"}}, "classes"),
        ({"classes": {"S": json.dumps({"a": "Secret Class Name"})}}, "classes"),
        ({"classes": {"S": json.dumps(["Secret Class Name", 3])}}, "classes"),
        ({"classes": {"S": json.dumps(["Secret Class Name", ""])}}, "classes"),
        ({"refreshed_at": {"S": "yesterday-SECRETTIME"}}, "refreshed_at"),
        ({"source": {"S": "someone-SECRETSOURCE"}}, "source"),
    ],
)
def test_unreadable_items_are_none(
    dynamodb: Any, change: dict[str, Any], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    dynamodb.put_item(TableName=TABLE_NAME, Item={**GOOD_ITEM, **change})

    with caplog.at_level("INFO"):
        assert DynamoDBClassListCache(TABLE_NAME).get() is None

    assert f"Class list cache: unreadable item ({reason})" in caplog.text
    for value in ("Secret Class Name", "SECRETTIME", "SECRETSOURCE", "not json"):
        assert value not in caplog.text


def test_good_item_written_elsewhere_is_read(dynamodb: Any) -> None:
    dynamodb.put_item(TableName=TABLE_NAME, Item=GOOD_ITEM)

    assert DynamoDBClassListCache(TABLE_NAME).get() == ClassListRecord(
        ("Secret Class Name",), NOW, ListSource.LIVE_READ
    )


def test_missing_table_raises_cache_unavailable(dynamodb: Any) -> None:
    cache = DynamoDBClassListCache("ClassPhotoClassListCache-missing")

    with pytest.raises(CacheUnavailable, match="^ResourceNotFoundException$"):
        cache.get()
    with pytest.raises(CacheUnavailable, match="^ResourceNotFoundException$"):
        cache.put(RECORD)


def test_client_created_lazily(dynamodb: Any) -> None:
    created: list[Any] = []

    def factory() -> Any:
        created.append(boto3.client("dynamodb", region_name="us-east-2"))
        return created[-1]

    cache = DynamoDBClassListCache(TABLE_NAME, client_factory=factory)
    assert created == []

    cache.get()
    cache.put(RECORD)
    cache.get()

    assert len(created) == 1


def test_client_creation_failure_is_cache_unavailable() -> None:
    def factory() -> Any:
        raise NoRegionError()

    cache = DynamoDBClassListCache(TABLE_NAME, client_factory=factory)

    with pytest.raises(CacheUnavailable, match="^NoRegionError$"):
        cache.get()


def test_default_client_makes_one_attempt_with_short_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-2")

    client = default_client()

    assert client.meta.config.retries["total_max_attempts"] == 1
    assert client.meta.config.connect_timeout == 2
    assert client.meta.config.read_timeout == 2
    assert client.meta.region_name == "us-east-2"


def test_from_environment_reads_the_table_name(dynamodb: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASS_CACHE_TABLE_NAME", TABLE_NAME)

    cache = DynamoDBClassListCache.from_environment()
    cache.put(RECORD)

    assert dynamodb.scan(TableName=TABLE_NAME)["Count"] == 1
