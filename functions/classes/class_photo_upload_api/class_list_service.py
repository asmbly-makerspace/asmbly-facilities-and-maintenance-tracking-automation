"""The class list for a request, a manual refresh or the schedule: the cache first, Neon when needed.

Depends on the ``ClassListCache`` interface and the freshness policy only; the cache and
the Neon reader are injected (plan README, "Design"). Logs carry counts, ages and error
types, never a class name.
"""

import datetime
import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass

try:
    from .class_list_cache import CacheUnavailable, ClassListCache, ClassListRecord, ListSource
    from .class_list_freshness import Action, FreshnessPolicy
except ImportError:  # Under Lambda this module is top-level, beside its helpers.
    from class_list_cache import (  # type: ignore[no-redef]
        CacheUnavailable,
        ClassListCache,
        ClassListRecord,
        ListSource,
    )
    from class_list_freshness import Action, FreshnessPolicy  # type: ignore[no-redef]

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ServedFrom(enum.StrEnum):
    CACHE = "cache"  # a copy the policy accepted
    NEON = "neon"  # read live just now
    STALE_CACHE = "stale_cache"  # Neon failed; the policy's fallback copy


class RefreshOutcome(enum.StrEnum):
    REFRESHED = "refreshed"
    TOO_SOON = "too_soon"
    FAILED = "failed"


@dataclass(frozen=True)
class ClassListResult:
    record: ClassListRecord
    served_from: ServedFrom
    refresh: RefreshOutcome | None = None  # set only for a manual refresh

    @property
    def names(self) -> list[str]:
        return list(self.record.names)

    @property
    def stale(self) -> bool:
        return self.served_from is ServedFrom.STALE_CACHE


class EmptyClassList(Exception):
    """Neon answered no classes. Treated as a failed read, so it never replaces a copy."""


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _minutes(age: datetime.timedelta) -> int:
    return int(age.total_seconds() // 60)


class ClassListService:
    def __init__(
        self,
        cache: ClassListCache,
        read_neon: Callable[[], list[str]],
        *,
        policy: FreshnessPolicy = FreshnessPolicy(),
        clock: Callable[[], datetime.datetime] = utc_now,
    ) -> None:
        self._cache = cache
        self._read_neon = read_neon
        self._policy = policy
        self._clock = clock

    def age_seconds(self, result: ClassListResult) -> int:
        return int(self._policy.age(result.record, self._clock()).total_seconds())

    def for_request(self) -> ClassListResult:
        """The list for ``GET /classes`` (and submit): the copy while fresh, else Neon."""
        record = self._get()
        if self._policy.for_request(record, self._clock()) is Action.USE_CACHE and record is not None:
            return ClassListResult(record, ServedFrom.CACHE)
        return self._read(record, ListSource.LIVE_READ, refresh=None)

    def refresh_on_request(self) -> ClassListResult:
        """``GET /classes?refresh=1``: Neon now, unless the copy was written moments ago."""
        record = self._get()
        if self._policy.for_manual_refresh(record, self._clock()) is Action.TOO_SOON and record is not None:
            return ClassListResult(record, ServedFrom.CACHE, RefreshOutcome.TOO_SOON)
        return self._read(record, ListSource.MANUAL_REFRESH, refresh=RefreshOutcome.REFRESHED)

    def refresh_on_schedule(self) -> bool:
        """The prod EventBridge rule: read Neon and keep it. Never raises."""
        try:
            names = self._neon_names()
        except Exception as e:
            record = self._get()
            if record is None:
                logger.warning("Scheduled class list refresh failed (%s); no cached list", type(e).__name__)
            else:
                logger.warning(
                    "Scheduled class list refresh failed (%s); kept the cached list, %d minutes old",
                    type(e).__name__,
                    _minutes(self._policy.age(record, self._clock())),
                )
            return False
        # Only a stored copy counts: a write that failed leaves the old copy to age out.
        return self._put(ClassListRecord(tuple(names), self._clock(), ListSource.SCHEDULE))

    def _read(
        self, record: ClassListRecord | None, source: ListSource, refresh: RefreshOutcome | None
    ) -> ClassListResult:
        try:
            names = self._neon_names()
        except EmptyClassList:
            now = self._clock()
            fallback = self._policy.fallback(record)
            if fallback is None:
                # Nothing to fall back on: answer the empty list, as before the cache, unwritten.
                # A manual refresh didn't get a list to keep, so it reports a failure.
                return ClassListResult(
                    ClassListRecord((), now, source),
                    ServedFrom.NEON,
                    RefreshOutcome.FAILED if refresh is not None else None,
                )
            return self._serve_fallback(fallback, "EmptyClassList", now, refresh)
        except Exception as e:
            fallback = self._policy.fallback(record)
            if fallback is None:
                raise
            return self._serve_fallback(fallback, type(e).__name__, self._clock(), refresh)
        # The time the list was read, so a slow read doesn't shorten the refresh guard.
        fresh = ClassListRecord(tuple(names), self._clock(), source)
        self._put(fresh)
        return ClassListResult(fresh, ServedFrom.NEON, refresh)

    def _serve_fallback(
        self, record: ClassListRecord, error: str, now: datetime.datetime, refresh: RefreshOutcome | None
    ) -> ClassListResult:
        logger.warning(
            "Neon failed (%s); serving the cached class list, %d minutes old",
            error,
            _minutes(self._policy.age(record, now)),
        )
        return ClassListResult(
            record, ServedFrom.STALE_CACHE, RefreshOutcome.FAILED if refresh is not None else None
        )

    def _neon_names(self) -> list[str]:
        names = self._read_neon()
        if not names:
            logger.warning("Neon returned no classes; not caching them")
            raise EmptyClassList()
        return names

    def _get(self) -> ClassListRecord | None:
        try:
            return self._cache.get()
        except CacheUnavailable as e:
            logger.warning("Class list cache: read failed: %s", e)
            return None

    def _put(self, record: ClassListRecord) -> bool:
        try:
            self._cache.put(record)
        except CacheUnavailable as e:
            logger.warning("Class list cache: write failed: %s", e)
            return False
        return True
