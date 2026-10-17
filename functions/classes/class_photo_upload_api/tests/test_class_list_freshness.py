import datetime

import pytest

from functions.classes.class_photo_upload_api.class_list_cache import ClassListRecord, ListSource
from functions.classes.class_photo_upload_api.class_list_freshness import (
    MAX_AGE,
    MIN_REFRESH_INTERVAL,
    Action,
    FreshnessPolicy,
)

NOW = datetime.datetime(2026, 10, 17, 14, 5, tzinfo=datetime.timezone.utc)
POLICY = FreshnessPolicy()


def record_aged(age: datetime.timedelta) -> ClassListRecord:
    return ClassListRecord(("Woodshop Safety",), NOW - age, ListSource.SCHEDULE)


def test_defaults_are_26_hours_and_60_seconds() -> None:
    assert MAX_AGE == datetime.timedelta(hours=26)
    assert MIN_REFRESH_INTERVAL == datetime.timedelta(seconds=60)
    assert POLICY.max_age == MAX_AGE
    assert POLICY.min_refresh_interval == MIN_REFRESH_INTERVAL


def test_no_record_reads_neon() -> None:
    assert POLICY.for_request(None, NOW) is Action.READ_NEON
    assert POLICY.for_manual_refresh(None, NOW) is Action.READ_NEON


def test_fresh_record_is_used() -> None:
    assert POLICY.for_request(record_aged(datetime.timedelta(minutes=5)), NOW) is Action.USE_CACHE


def test_record_at_max_age_is_used() -> None:
    assert POLICY.for_request(record_aged(MAX_AGE), NOW) is Action.USE_CACHE


def test_record_past_max_age_reads_neon() -> None:
    assert POLICY.for_request(record_aged(MAX_AGE + datetime.timedelta(seconds=1)), NOW) is Action.READ_NEON


def test_future_record_counts_as_age_zero() -> None:
    future = record_aged(-datetime.timedelta(hours=2))
    assert POLICY.age(future, NOW) == datetime.timedelta(0)
    assert POLICY.for_request(future, NOW) is Action.USE_CACHE
    assert POLICY.for_manual_refresh(future, NOW) is Action.TOO_SOON


@pytest.mark.parametrize(
    "age, expected",
    [
        (datetime.timedelta(0), Action.TOO_SOON),
        (datetime.timedelta(seconds=59), Action.TOO_SOON),
        (datetime.timedelta(seconds=60), Action.READ_NEON),
        (datetime.timedelta(hours=1), Action.READ_NEON),
        (MAX_AGE * 2, Action.READ_NEON),
    ],
)
def test_manual_refresh_too_soon_under_a_minute(age: datetime.timedelta, expected: Action) -> None:
    assert POLICY.for_manual_refresh(record_aged(age), NOW) is expected


def test_fallback_serves_any_copy() -> None:
    week_old = record_aged(datetime.timedelta(days=7))
    assert POLICY.fallback(week_old) is week_old
    assert POLICY.fallback(None) is None


def test_policy_limits_can_be_set() -> None:
    policy = FreshnessPolicy(max_age=datetime.timedelta(minutes=10), min_refresh_interval=datetime.timedelta(0))
    assert policy.for_request(record_aged(datetime.timedelta(minutes=11)), NOW) is Action.READ_NEON
    assert policy.for_manual_refresh(record_aged(datetime.timedelta(0)), NOW) is Action.READ_NEON
