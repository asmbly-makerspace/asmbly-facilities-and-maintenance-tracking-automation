"""The class-list service, with the in-memory cache and a fixed clock: no AWS, no Neon."""

import ast
import datetime
from pathlib import Path

import pytest

from functions.classes.class_photo_upload_api.class_list_cache import ClassListRecord, ListSource
from functions.classes.class_photo_upload_api.class_list_freshness import MAX_AGE
from functions.classes.class_photo_upload_api.class_list_service import (
    ClassListService,
    RefreshOutcome,
    ServedFrom,
)
from functions.classes.class_photo_upload_api.tests.fake_class_list_cache import InMemoryClassListCache

NOW = datetime.datetime(2026, 10, 17, 14, 5, tzinfo=datetime.timezone.utc)
OLD_NAMES = ("Ceramics: Glazing Workshop", "Woodshop Safety")
NEW_NAMES = ["Ceramics: Glazing Workshop", "Intro to Forging", "Woodshop Safety"]
MODULE_DIR = Path(__file__).resolve().parent.parent


class NeonDown(Exception):
    pass


class FakeNeon:
    def __init__(self, names: list[str] | None = None, error: Exception | None = None) -> None:
        self.names = list(NEW_NAMES) if names is None else names
        self.error = error
        self.calls = 0

    def __call__(self) -> list[str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.names)


def copy_aged(age: datetime.timedelta, source: ListSource = ListSource.SCHEDULE) -> ClassListRecord:
    return ClassListRecord(OLD_NAMES, NOW - age, source)


def service_for(cache: InMemoryClassListCache, neon: FakeNeon) -> ClassListService:
    return ClassListService(cache, neon, clock=lambda: NOW)


FRESH = datetime.timedelta(minutes=30)
EXPIRED = MAX_AGE + datetime.timedelta(seconds=1)


# --- a request ---------------------------------------------------------------------


def test_hit_serves_cache_without_neon() -> None:
    cache, neon = InMemoryClassListCache(copy_aged(FRESH)), FakeNeon()

    result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.CACHE
    assert result.names == list(OLD_NAMES)
    assert result.stale is False
    assert result.refresh is None
    assert neon.calls == 0
    assert cache.puts == []


def test_miss_reads_neon_and_writes_cache() -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon()

    result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.NEON
    assert result.names == NEW_NAMES
    assert neon.calls == 1
    assert cache.puts == [ClassListRecord(tuple(NEW_NAMES), NOW, ListSource.LIVE_READ)]


def test_expired_copy_reads_neon_and_replaces_it() -> None:
    cache, neon = InMemoryClassListCache(copy_aged(EXPIRED)), FakeNeon()

    result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.NEON
    assert neon.calls == 1
    assert cache.record == ClassListRecord(tuple(NEW_NAMES), NOW, ListSource.LIVE_READ)


def test_copy_at_max_age_is_still_a_hit() -> None:
    cache, neon = InMemoryClassListCache(copy_aged(MAX_AGE)), FakeNeon()

    assert service_for(cache, neon).for_request().served_from is ServedFrom.CACHE
    assert neon.calls == 0


def test_neon_failure_with_copy_serves_it_stale(caplog: pytest.LogCaptureFixture) -> None:
    old = copy_aged(datetime.timedelta(hours=30))
    cache, neon = InMemoryClassListCache(old), FakeNeon(error=NeonDown())

    with caplog.at_level("WARNING"):
        result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.STALE_CACHE
    assert result.stale is True
    assert result.record is old
    assert result.refresh is None
    assert cache.puts == []
    assert "Neon failed (NeonDown); serving the cached class list, 1800 minutes old" in caplog.text


def test_neon_failure_without_copy_reraises() -> None:
    error = NeonDown()
    cache, neon = InMemoryClassListCache(), FakeNeon(error=error)

    with pytest.raises(NeonDown) as raised:
        service_for(cache, neon).for_request()

    assert raised.value is error
    assert cache.puts == []


def test_empty_neon_answer_keeps_the_copy(caplog: pytest.LogCaptureFixture) -> None:
    old = copy_aged(EXPIRED)
    cache, neon = InMemoryClassListCache(old), FakeNeon(names=[])

    with caplog.at_level("WARNING"):
        result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.STALE_CACHE
    assert result.record is old
    assert cache.puts == []
    assert "Neon returned no classes; not caching them" in caplog.text


def test_empty_neon_answer_without_copy_is_not_cached() -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon(names=[])

    result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.NEON
    assert result.names == []
    assert result.record.refreshed_at == NOW
    assert cache.puts == []


def test_cache_read_failure_is_a_miss(caplog: pytest.LogCaptureFixture) -> None:
    cache, neon = InMemoryClassListCache(copy_aged(FRESH)), FakeNeon()
    cache.fail_get = "ProvisionedThroughputExceededException"

    with caplog.at_level("WARNING"):
        result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.NEON
    assert neon.calls == 1
    assert "Class list cache: read failed: ProvisionedThroughputExceededException" in caplog.text


def test_cache_write_failure_still_returns_live_list(caplog: pytest.LogCaptureFixture) -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon()
    cache.fail_put = "AccessDeniedException"

    with caplog.at_level("WARNING"):
        result = service_for(cache, neon).for_request()

    assert result.served_from is ServedFrom.NEON
    assert result.names == NEW_NAMES
    assert "Class list cache: write failed: AccessDeniedException" in caplog.text


# --- a manual refresh --------------------------------------------------------------


def test_manual_refresh_reads_neon_and_rewrites() -> None:
    cache, neon = InMemoryClassListCache(copy_aged(FRESH)), FakeNeon()

    result = service_for(cache, neon).refresh_on_request()

    assert result.served_from is ServedFrom.NEON
    assert result.refresh is RefreshOutcome.REFRESHED
    assert result.names == NEW_NAMES
    assert neon.calls == 1
    assert cache.record == ClassListRecord(tuple(NEW_NAMES), NOW, ListSource.MANUAL_REFRESH)


def test_manual_refresh_with_empty_cache_reads_neon() -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon()

    result = service_for(cache, neon).refresh_on_request()

    assert result.refresh is RefreshOutcome.REFRESHED
    assert cache.record is not None and cache.record.source is ListSource.MANUAL_REFRESH


def test_manual_refresh_too_soon_returns_copy_without_neon() -> None:
    recent = copy_aged(datetime.timedelta(seconds=59), ListSource.MANUAL_REFRESH)
    cache, neon = InMemoryClassListCache(recent), FakeNeon()

    result = service_for(cache, neon).refresh_on_request()

    assert result.served_from is ServedFrom.CACHE
    assert result.refresh is RefreshOutcome.TOO_SOON
    assert result.record is recent
    assert result.stale is False
    assert neon.calls == 0
    assert cache.puts == []


def test_manual_refresh_neon_failure_serves_copy_stale() -> None:
    old = copy_aged(FRESH)
    cache, neon = InMemoryClassListCache(old), FakeNeon(error=NeonDown())

    result = service_for(cache, neon).refresh_on_request()

    assert result.served_from is ServedFrom.STALE_CACHE
    assert result.refresh is RefreshOutcome.FAILED
    assert result.stale is True
    assert result.record is old
    assert cache.puts == []


def test_manual_refresh_empty_answer_serves_copy_stale() -> None:
    old = copy_aged(FRESH)
    cache, neon = InMemoryClassListCache(old), FakeNeon(names=[])

    result = service_for(cache, neon).refresh_on_request()

    assert result.refresh is RefreshOutcome.FAILED
    assert result.record is old


def test_manual_refresh_empty_answer_without_copy_reports_failed() -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon(names=[])

    result = service_for(cache, neon).refresh_on_request()

    assert result.refresh is RefreshOutcome.FAILED
    assert result.names == []
    assert result.stale is False
    assert cache.puts == []


def test_manual_refresh_without_copy_and_neon_failure_reraises() -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon(error=NeonDown())

    with pytest.raises(NeonDown):
        service_for(cache, neon).refresh_on_request()


# --- the schedule ------------------------------------------------------------------


def test_scheduled_refresh_writes_fresh_list() -> None:
    cache, neon = InMemoryClassListCache(copy_aged(datetime.timedelta(seconds=5))), FakeNeon()

    assert service_for(cache, neon).refresh_on_schedule() is True

    assert neon.calls == 1
    assert cache.record == ClassListRecord(tuple(NEW_NAMES), NOW, ListSource.SCHEDULE)


def test_scheduled_refresh_failure_keeps_copy_and_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    old = copy_aged(datetime.timedelta(hours=2))
    cache, neon = InMemoryClassListCache(old), FakeNeon(error=NeonDown())

    with caplog.at_level("WARNING"):
        assert service_for(cache, neon).refresh_on_schedule() is False

    assert cache.record is old
    assert cache.puts == []
    assert "Scheduled class list refresh failed (NeonDown); kept the cached list, 120 minutes old" in caplog.text


def test_scheduled_refresh_failure_with_empty_cache_logs_no_cached_list(caplog: pytest.LogCaptureFixture) -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon(error=NeonDown())

    with caplog.at_level("WARNING"):
        assert service_for(cache, neon).refresh_on_schedule() is False

    assert "Scheduled class list refresh failed (NeonDown); no cached list" in caplog.text


def test_scheduled_refresh_empty_answer_keeps_copy(caplog: pytest.LogCaptureFixture) -> None:
    old = copy_aged(datetime.timedelta(hours=2))
    cache, neon = InMemoryClassListCache(old), FakeNeon(names=[])

    with caplog.at_level("WARNING"):
        assert service_for(cache, neon).refresh_on_schedule() is False

    assert cache.record is old
    assert "Scheduled class list refresh failed (EmptyClassList)" in caplog.text


def test_scheduled_refresh_cache_write_failure_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    cache, neon = InMemoryClassListCache(), FakeNeon()
    cache.fail_put = "ResourceNotFoundException"

    with caplog.at_level("WARNING"):
        assert service_for(cache, neon).refresh_on_schedule() is False

    assert "Class list cache: write failed: ResourceNotFoundException" in caplog.text


def test_refreshed_at_is_taken_after_the_neon_read() -> None:
    times = iter([NOW, NOW + datetime.timedelta(seconds=8)])
    cache = InMemoryClassListCache(copy_aged(datetime.timedelta(hours=2)))
    service = ClassListService(cache, FakeNeon(), clock=lambda: next(times))

    result = service.refresh_on_request()

    assert result.record.refreshed_at == NOW + datetime.timedelta(seconds=8)


# --- logs and design ---------------------------------------------------------------


def test_age_seconds_uses_the_clock() -> None:
    cache = InMemoryClassListCache(copy_aged(datetime.timedelta(seconds=90)))
    service = service_for(cache, FakeNeon())

    assert service.age_seconds(service.for_request()) == 90


def test_logs_carry_no_class_names(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"):
        service_for(InMemoryClassListCache(), FakeNeon()).for_request()
        service_for(InMemoryClassListCache(copy_aged(EXPIRED)), FakeNeon(error=NeonDown())).for_request()
        service_for(InMemoryClassListCache(copy_aged(FRESH)), FakeNeon()).refresh_on_request()
        service_for(InMemoryClassListCache(), FakeNeon(error=NeonDown())).refresh_on_schedule()

    for name in set(OLD_NAMES) | set(NEW_NAMES):
        assert name not in caplog.text


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.lstrip(".").split(".")[0])
    return modules


@pytest.mark.parametrize("module", ["class_list_cache.py", "class_list_freshness.py", "class_list_service.py"])
def test_service_modules_do_not_import_boto3(module: str) -> None:
    imported = _imported_modules(MODULE_DIR / module)

    assert not imported & {"boto3", "botocore", "dynamodb_class_list_cache", "common"}
