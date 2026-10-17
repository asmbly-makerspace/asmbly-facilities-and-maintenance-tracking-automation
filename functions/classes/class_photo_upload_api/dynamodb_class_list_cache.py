"""The class-list cache in DynamoDB: one item in ``ClassPhotoClassListCache-${Stage}``.

The only module that imports boto3 or knows the item's attribute names. The client is
created on first use, never at import.
"""

import json
import logging
import os
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

try:
    from .class_list_cache import CacheUnavailable, ClassListRecord, ListSource, format_time, parse_time
except ImportError:  # Under Lambda this module is top-level, beside class_list_cache.py.
    from class_list_cache import (  # type: ignore[no-redef]
        CacheUnavailable,
        ClassListRecord,
        ListSource,
        format_time,
        parse_time,
    )

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME_ENV = "CLASS_CACHE_TABLE_NAME"
CACHE_KEY = "class-list"
SCHEMA_VERSION = 1

# A DynamoDB problem must not eat the request's time (plan README, Decision 7): one
# attempt each for the read and the write (no retry) keeps an outage to about 8 s of the
# 25 s. "total_max_attempts", not "max_attempts": in client config botocore reads
# "max_attempts" as retries and adds one.
CLIENT_CONFIG = Config(
    connect_timeout=2, read_timeout=2, retries={"total_max_attempts": 1, "mode": "standard"}
)


def default_client() -> Any:
    return boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION"), config=CLIENT_CONFIG)


def _reason(error: Exception) -> str:
    """A fixed reason for a backend error: its code, or its type. Never its message."""
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code")
        if isinstance(code, str) and code:
            return code
    return type(error).__name__


class _Unreadable(Exception):
    """An item this code can't read; ``str()`` names the attribute, never its value."""


def _decode(item: dict[str, Any]) -> ClassListRecord:
    if item.get("version", {}).get("N") != str(SCHEMA_VERSION):
        raise _Unreadable("version")
    try:
        names = json.loads(item.get("classes", {}).get("S", ""))
    except ValueError:
        raise _Unreadable("classes") from None
    if not isinstance(names, list) or not all(isinstance(name, str) and name for name in names):
        raise _Unreadable("classes")
    refreshed_at = parse_time(item.get("refreshed_at", {}).get("S", ""))
    if refreshed_at is None:
        raise _Unreadable("refreshed_at")
    try:
        source = ListSource(item.get("source", {}).get("S", ""))
    except ValueError:
        raise _Unreadable("source") from None
    return ClassListRecord(names=tuple(names), refreshed_at=refreshed_at, source=source)


def _encode(record: ClassListRecord) -> dict[str, Any]:
    return {
        "cache_key": {"S": CACHE_KEY},
        "version": {"N": str(SCHEMA_VERSION)},
        "classes": {"S": json.dumps(list(record.names))},
        "class_count": {"N": str(len(record.names))},
        "refreshed_at": {"S": format_time(record.refreshed_at)},
        "source": {"S": record.source.value},
    }


class DynamoDBClassListCache:
    """``ClassListCache`` on one DynamoDB item, key ``cache_key = "class-list"``."""

    def __init__(self, table_name: str, client_factory: Callable[[], Any] = default_client) -> None:
        self._table_name = table_name
        self._client_factory = client_factory
        self._client: Any = None

    @classmethod
    def from_environment(cls) -> "DynamoDBClassListCache":
        return cls(os.environ[TABLE_NAME_ENV])

    def _dynamodb(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def get(self) -> ClassListRecord | None:
        try:
            answer = self._dynamodb().get_item(
                TableName=self._table_name, Key={"cache_key": {"S": CACHE_KEY}}, ConsistentRead=True
            )
        except (BotoCoreError, ClientError) as e:
            raise CacheUnavailable(_reason(e)) from None
        item = answer.get("Item")
        if not item:
            logger.info("Class list cache: empty")
            return None
        try:
            return _decode(item)
        except _Unreadable as e:
            logger.warning("Class list cache: unreadable item (%s)", e)
            return None

    def put(self, record: ClassListRecord) -> None:
        try:
            self._dynamodb().put_item(TableName=self._table_name, Item=_encode(record))
        except (BotoCoreError, ClientError) as e:
            raise CacheUnavailable(_reason(e)) from None
