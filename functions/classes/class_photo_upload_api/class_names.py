"""Class names from Neon, and the file-name rules of classes.asmbly.org.

The rules mirror asmbly-classes (read at bdf601b):

- class name: ``event['Event Name'].split(' w/ ')[0].trim()``
  (cron-service/prisma/dailyClassMaintenance.js)
- fuzzy key, used by the class list: ``simplifyName`` in
  app/src/lib/models/neonEventInstance.js
- exact file name, used by My Classes: app/src/lib/components/myClassCard.svelte
"""

import calendar
import datetime
import hashlib
import logging
import re
from typing import Any

from common.neoncrm import NeonCRM

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CLASS_LOOKBACK_MONTHS = 4  # #73: the list looks back 4 months
NAME_SPLIT = " w/ "
FORBIDDEN_CHARACTERS_PATTERN = re.compile(r"[/\\\x00-\x1f\x7f]")
NEON_SEARCH_OUTPUT_FIELDS = ["Event ID", "Event Name"]
# The class list must load well inside API Gateway's 29 s: at most 8 pages of 200
# events (several times the 4-month window), giving up on a request that doesn't
# connect or answer for 4 s.
NEON_PAGE_TIMEOUT_SECONDS = 4.0
NEON_MAX_PAGES = 8

_FUZZY_STRIP_PATTERN = re.compile(r"(\s|:|-|_)+")
_EXACT_REPLACE_PATTERN = re.compile(r"(\s+|:)")
_BRANCH_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_BRANCH_SLUG_MAX_LENGTH = 50


def class_name_from_event_name(event_name: str) -> str:
    """The class name the site shows: the event name up to " w/ ", trimmed."""
    return event_name.split(NAME_SPLIT)[0].strip()


def lookback_start(today: datetime.date, months: int = CLASS_LOOKBACK_MONTHS) -> datetime.date:
    """``today`` minus ``months`` calendar months, the day clamped to the month's length."""
    month_index = today.year * 12 + (today.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def neon_search_fields(today: datetime.date) -> list[dict[str, str]]:
    """Neon search fields for events that ended on or after the lookback start.

    No ``Event Archived`` filter: past classes are archived and still wanted.
    """
    return [
        {
            "field": "Event End Date",
            "operator": "GREATER_AND_EQUAL",
            "value": lookback_start(today).isoformat(),
        }
    ]


def class_names_from_events(events: list[dict[str, Any]]) -> list[str]:
    """One entry per class name, sorted case-insensitively.

    De-duplication is exact (case-sensitive), as the site's class upsert is. A
    missing or non-string ``Event Name`` (or an entry that isn't an object)
    counts as empty and is dropped.
    """
    names: set[str] = set()
    for event in events:
        event_name = event.get("Event Name") if isinstance(event, dict) else None
        if not isinstance(event_name, str):
            continue
        name = class_name_from_event_name(event_name)
        if name:
            names.add(name)
    return sorted(names, key=lambda n: (n.casefold(), n))


def fetch_classes(
    neon: NeonCRM,
    today: datetime.date,
    *,
    timeout: float = NEON_PAGE_TIMEOUT_SECONDS,
    max_pages: int = NEON_MAX_PAGES,
) -> list[str]:
    """Reads the class list from Neon. ``NeonCRMError`` propagates to the caller."""
    events = neon.search_events(
        neon_search_fields(today), NEON_SEARCH_OUTPUT_FIELDS, timeout=timeout, max_pages=max_pages
    )
    classes = class_names_from_events(events)
    logger.info("Read %d events, %d classes", len(events), len(classes))
    return classes


def fuzzy_key(name: str) -> str:
    """The site's ``simplifyName``, for a class name or a bare image file name."""
    key = _FUZZY_STRIP_PATTERN.sub("", name.lower())
    key = key.replace("&", "and", 1)
    key = key.split("/")[-1]
    return key.split(".")[0]


def exact_file_name(class_name: str) -> str:
    """The file name My Classes looks for: each run of spaces and each ":" as "_"."""
    return _EXACT_REPLACE_PATTERN.sub("_", class_name) + ".jpg"


def file_name_problem(class_name: str) -> str | None:
    """None when the class name can be a file name; otherwise a message for the person."""
    if not class_name.strip():
        return "This class has no name in Neon, so it can't have a photo."
    match = FORBIDDEN_CHARACTERS_PATTERN.search(class_name)
    if match is None:
        return None
    character = match.group()
    shown = character if character in "/\\" else f"U+{ord(character):04X}"
    return (
        f'The class name "{class_name}" contains "{shown}", which can\'t be in a file name. '
        "Rename the class in Neon first."
    )


def fuzzy_collisions(class_name: str, all_classes: list[str]) -> list[str]:
    """The other classes whose fuzzy key equals this class's, sorted."""
    key = fuzzy_key(class_name)
    return sorted({c for c in all_classes if c != class_name and fuzzy_key(c) == key})


def collision_warning(class_name: str, others: list[str]) -> str | None:
    """A warning naming the classes that share this class's photo on the class list."""
    if not others:
        return None
    names = ", ".join(f'"{other}"' for other in others)
    if len(others) == 1:
        return (
            f"Another class, {names}, matches the same photo on the class list. "
            "Both classes will show this photo there."
        )
    return (
        f"Other classes, {names}, match the same photo on the class list. "
        "All of these classes will show this photo there."
    )


def superseded_images(class_name: str, image_names: list[str], extensions: list[str]) -> list[str]:
    """The other images the class list's fuzzy lookup would match for this class.

    ``image_names`` are bare file names in the images directory. The extension
    is compared case-sensitively, as the site's ``import.meta.glob`` does.
    """
    key = fuzzy_key(class_name)
    exact = exact_file_name(class_name)
    allowed = set(extensions)
    return sorted(
        name
        for name in image_names
        if "." in name
        and name.rsplit(".", 1)[1] in allowed
        and name != exact
        and fuzzy_key(name) == key
    )


def branch_name(class_name: str, prefix: str) -> str:
    """The class's own branch: ``<prefix><slug>-<first 8 hex of SHA-256 of the name>``."""
    stem = exact_file_name(class_name)[: -len(".jpg")]
    slug = _BRANCH_SLUG_PATTERN.sub("-", stem.lower()).strip("-")
    slug = slug[:_BRANCH_SLUG_MAX_LENGTH].rstrip("-")
    digest = hashlib.sha256(class_name.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{slug}-{digest}"
