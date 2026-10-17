"""When a cached class list is good enough: the maximum age, the refresh guard, the fallback.

Pure: no I/O, no clock, no logging. ``now`` is always passed in.
"""

import datetime
import enum
from dataclasses import dataclass

try:
    from .class_list_cache import ClassListRecord
except ImportError:  # Under Lambda this module is top-level, beside class_list_cache.py.
    from class_list_cache import ClassListRecord  # type: ignore[no-redef]

# A bit over a day: prod's daily refresh normally keeps the copy fresh, and a missed run
# still falls back to a live read (plan README, Decision 20).
MAX_AGE = datetime.timedelta(hours=26)
# A manual refresh within this long of the last write answers that copy (Decision 21).
MIN_REFRESH_INTERVAL = datetime.timedelta(seconds=60)


class Action(enum.StrEnum):
    USE_CACHE = "use_cache"
    READ_NEON = "read_neon"
    TOO_SOON = "too_soon"


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age: datetime.timedelta = MAX_AGE
    min_refresh_interval: datetime.timedelta = MIN_REFRESH_INTERVAL

    def age(self, record: ClassListRecord, now: datetime.datetime) -> datetime.timedelta:
        """How old the copy is; a copy dated in the future counts as just written."""
        return max(datetime.timedelta(0), now - record.refreshed_at)

    def for_request(self, record: ClassListRecord | None, now: datetime.datetime) -> Action:
        """A normal load: the copy while it is no older than ``max_age``, else Neon."""
        if record is not None and self.age(record, now) <= self.max_age:
            return Action.USE_CACHE
        return Action.READ_NEON

    def for_manual_refresh(self, record: ClassListRecord | None, now: datetime.datetime) -> Action:
        """A refresh asked for by staff: Neon, unless the copy was written moments ago."""
        if record is not None and self.age(record, now) < self.min_refresh_interval:
            return Action.TOO_SOON
        return Action.READ_NEON

    def fallback(self, record: ClassListRecord | None) -> ClassListRecord | None:
        """The copy to serve, marked stale, when a Neon read fails: any copy, whatever its age."""
        return record
