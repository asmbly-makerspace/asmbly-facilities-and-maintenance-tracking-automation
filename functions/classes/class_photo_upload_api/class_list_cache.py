"""The class-list cache's interface: the stored record and what a cache must do.

The service and the handler depend on this module only; the one implementation
(``dynamodb_class_list_cache``) is picked in ``lambda_function`` (plan README, "Design").
No AWS here.
"""

import datetime
import enum
from dataclasses import dataclass
from typing import Protocol

# The one way a record's time is written: in the cache and in the API's answer.
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ListSource(enum.StrEnum):
    """What read a cached copy from Neon."""

    SCHEDULE = "schedule"  # the prod EventBridge rule
    LIVE_READ = "live_read"  # a request found no usable copy
    MANUAL_REFRESH = "manual_refresh"  # staff asked for a refresh


@dataclass(frozen=True)
class ClassListRecord:
    """A class list read from Neon, and when and by what."""

    names: tuple[str, ...]
    refreshed_at: datetime.datetime  # aware, UTC, whole seconds
    source: ListSource


def format_time(moment: datetime.datetime) -> str:
    """``2026-10-17T14:05:00Z``: UTC, whole seconds."""
    return moment.astimezone(datetime.timezone.utc).strftime(TIME_FORMAT)


def parse_time(text: str) -> datetime.datetime | None:
    """The aware UTC time ``format_time`` wrote, or ``None``."""
    try:
        return datetime.datetime.strptime(text, TIME_FORMAT).replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


class CacheUnavailable(Exception):
    """The cache's backend failed. ``str()`` is a fixed reason (an error type or code), never a value."""


class ClassListCache(Protocol):
    """Where the class list is kept between requests."""

    def get(self) -> ClassListRecord | None:
        """The stored copy; ``None`` when nothing usable is stored.

        Raises ``CacheUnavailable`` when the backend fails.
        """
        ...

    def put(self, record: ClassListRecord) -> None:
        """Replaces the stored copy. Raises ``CacheUnavailable`` when the backend fails."""
        ...
