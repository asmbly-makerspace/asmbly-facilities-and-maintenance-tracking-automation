---
phase_id: 1
title: Class list and file-name rule
epic: 73
implements: [104, 107]
depends_on: []
domain: [layer, lambda]
estimated_size: L
---

# Phase 1: Class list and file-name rule

> **Status:** [x] Complete — 2026-10-16 on branch claude/inspiring-bell-o4i5t9

## Required reading

- `CLAUDE.md`, and #73's sections "The class list" and "The file name".
- `layers/common/python/common/neoncrm.py` and its tests in
  `layers/common/python/tests/test_neoncrm.py` (the `NeonCRM` client, Basic auth header).
- `functions/networking/dynamic_dns_update/lambda_function.py`: the style for new code
  (lazy logging, type hints).
- The site's rules, quoted here so the build doesn't need `asmbly-classes`
  (read at `bdf601b`):
  - Class name: `event['Event Name'].split(' w/ ')[0].trim()`
    (`cron-service/prisma/dailyClassMaintenance.js:179`).
  - Fuzzy (class list, `app/src/lib/models/neonEventInstance.js:94-99`), applied to the
    class name and to each image's path:
    ```js
    const simplifyName = s =>
      s.toLowerCase()
        .replace(/(\s|:|-|_)+/g, '')
        .replace('&', 'and')       // first '&' only
        .split('/').at(-1)
        .split('.')[0];
    ```
  - Exact (My Classes, `app/src/lib/components/myClassCard.svelte:5`):
    `'/src/lib/images/' + eventName.replace(/(\s+|:)/g, '_') + '.jpg'`.
  - Images the site loads: `import.meta.glob('$lib/images/*.{avif,gif,heif,jpeg,jpg,png,tiff,webp}')`
    (top level of `app/src/lib/images/` only).
- Neon's event search as the site calls it (`cron-service/prisma/neonHelpers.js`):
  `POST https://api.neoncrm.com/v2/events/search` with `searchFields`, `outputFields`
  and `pagination: {currentPage, pageSize: 200}`; the response has `searchResults` and
  `pagination.totalPages`.

## Goal

The server can turn Neon events into the list of classes the page offers, and, for a
chosen class, compute everything the pull request needs from its name: the exact file
name, the fuzzy key, which existing images it supersedes, whether the name is refused,
which other classes it collides with, and its branch name. Pure functions plus one
read-only Neon helper; nothing is wired to a route yet.

## Files to create

- `functions/classes/__init__.py`: empty.
- `functions/classes/class_photo_upload_api/__init__.py`: empty.
- `functions/classes/class_photo_upload_api/class_names.py`: the rules below.
- `functions/classes/class_photo_upload_api/tests/__init__.py`: empty.
- `functions/classes/class_photo_upload_api/tests/test_class_names.py`.
- `functions/classes/class_photo_upload_api/tests/fixtures/asmbly_classes_images_bdf601b.json`:
  the 131 names in "Fixture: current images" below, as a JSON array.
- `functions/classes/class_photo_upload_api/tests/fixtures/asmbly_classes_pr49_images.json`:
  the 56 names in "Fixture: PR #49" below, as a JSON array of `{"status", "name"}`.
- `functions/classes/class_photo_upload_api/tests/fixtures/neon_events_search_page0.json`
  and `neon_events_search_page1.json`: two pages of a Neon search response (fake event
  names and IDs; no people).

## Files to modify

- `layers/common/python/common/neoncrm.py`: add `NeonCRMError` and
  `NeonCRM.search_events`. Leave the existing methods and the module-level logger as
  they are (#95 covers them).
- `layers/common/python/tests/test_neoncrm.py`: tests for `search_events`.

## Implementation details

### layer: `NeonCRM.search_events`

```python
class NeonCRMError(Exception):
    """A Neon call failed. The message carries the operation and HTTP status only."""


def search_events(
    self,
    search_fields: list[dict[str, str]],
    output_fields: list[str],
    page_size: int = 200,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
```

- `POST {base_url}/events/search` with `{"searchFields": ..., "outputFields": ...,
  "pagination": {"currentPage": n, "pageSize": page_size}}`, starting at page 0 and
  continuing while `n + 1 < pagination.totalPages`; stop at 50 pages as a guard (log a
  warning). Concatenate `searchResults`.
- Each call has `timeout=timeout`. On `requests.exceptions.RequestException`, a body
  that isn't JSON, or a JSON body without a list `searchResults` (a 200 carrying an error
  object), log `logger.error("Neon event search failed: %s", <class name and
  status>)` and raise `NeonCRMError("events/search failed (status <n>)")`. Never log or
  include the response body, the URL's credentials or the headers. When there is no
  response (a timeout or connection error), the message says `(no response)` instead of
  a status. A missing `pagination.totalPages` means one page.
- Read only. No other Neon endpoint is added.

### lambda: `class_names.py`

Module constants:

```python
CLASS_LOOKBACK_MONTHS = 4          # #73: the list looks back 4 months
NAME_SPLIT = " w/ "
FORBIDDEN_CHARACTERS_PATTERN = re.compile(r"[/\\\x00-\x1f\x7f]")
NEON_SEARCH_OUTPUT_FIELDS = ["Event ID", "Event Name"]
```

Functions (all typed, all pure except `fetch_classes`):

- `class_name_from_event_name(event_name: str) -> str`: `event_name.split(" w/ ")[0].strip()`.
  `class_names_from_events` treats a missing or non-string `Event Name` as empty.
- `lookback_start(today: datetime.date, months: int = CLASS_LOOKBACK_MONTHS) -> datetime.date`:
  calendar months back, day clamped to the month's length (2026-06-30 minus 4 months is
  2026-02-28).
- `neon_search_fields(today: datetime.date) -> list[dict[str, str]]`:
  `[{"field": "Event End Date", "operator": "GREATER_AND_EQUAL", "value": "<YYYY-MM-DD>"}]`.
  No `Event Archived` filter: past classes are archived and still wanted.
- `class_names_from_events(events: list[dict]) -> list[str]`: class name of each event's
  `Event Name`, empty names dropped, de-duplicated exactly (case-sensitive, as the site's
  `neonEventType` upsert is), sorted case-insensitively.
- `fetch_classes(neon: NeonCRM, today: datetime.date) -> list[str]`: calls
  `neon.search_events(neon_search_fields(today), NEON_SEARCH_OUTPUT_FIELDS)` and returns
  `class_names_from_events(...)`. Lets `NeonCRMError` propagate.
- `fuzzy_key(name: str) -> str`: the site's `simplifyName`, in Python:
  lowercase; `re.sub(r"(\s|:|-|_)+", "", s)`; `s.replace("&", "and", 1)`;
  `s.split("/")[-1]`; `s.split(".")[0]`. Apply it to a bare file name or a class name.
- `exact_file_name(class_name: str) -> str`: `re.sub(r"(\s+|:)", "_", class_name) + ".jpg"`.
- `file_name_problem(class_name: str) -> str | None`: `None` when the name is usable;
  otherwise a message for the person:
  - empty after trimming: "This class has no name in Neon, so it can't have a photo."
  - a match of `FORBIDDEN_CHARACTERS_PATTERN`: `'The class name "<name>" contains "<char>",
    which can't be in a file name. Rename the class in Neon first.'` (a control character
    is shown as `U+00XX`).
- `fuzzy_collisions(class_name: str, all_classes: list[str]) -> list[str]`: the other
  class names (not equal to `class_name`) with the same `fuzzy_key`, sorted.
- `collision_warning(class_name: str, others: list[str]) -> str | None`:
  `'Another class, "<other>", matches the same photo on the class list. Both classes
  will show this photo there.'` (names joined with ", " when several); `None` when none.
- `superseded_images(class_name: str, image_names: list[str], extensions: list[str]) -> list[str]`:
  every name in `image_names` (bare file names in the images directory) whose extension
  (after the last `.`, compared case-sensitively, as the site's `import.meta.glob` does:
  Vite's glob is case-sensitive, so `Foo.JPG` is never loaded) is in `extensions`, whose `fuzzy_key` equals the
  class's, and which is not `exact_file_name(class_name)`. Sorted.
- `branch_name(class_name: str, prefix: str) -> str`: `prefix + slug + "-" + hash8`,
  `slug` = `re.sub(r"[^a-z0-9]+", "-", exact_file_name(class_name)[:-4].lower()).strip("-")[:50]`,
  `hash8` = first 8 hex digits of `hashlib.sha256(class_name.encode("utf-8"))`.

Logging: `class_names.py` logs nothing except `fetch_classes`
(`logger.info("Read %d events, %d classes", ...)`).

## Tests

`layers/common/python/tests/test_neoncrm.py` (`requests-mock`, no network):

- `test_search_events_posts_fields_and_pagination`: the request body has the given
  `searchFields`, `outputFields` and `pagination` `{currentPage: 0, pageSize: 200}`, and
  the Basic auth header.
- `test_search_events_reads_every_page`: `totalPages: 2` gives two calls (pages 0 and 1)
  and the results of both, in order.
- `test_search_events_raises_on_http_error`: a 500 raises `NeonCRMError` whose message
  has the status and not the response body (assert a marker string from the body is
  absent from the message and from `caplog`).
- `test_search_events_raises_on_timeout`: `requests.exceptions.ConnectTimeout` raises
  `NeonCRMError`.
- `test_search_events_raises_on_non_json`, and a 200 JSON body without `searchResults`
  raises `NeonCRMError` too.

`functions/classes/class_photo_upload_api/tests/test_class_names.py`:

- `test_class_name_from_event_name` (parametrized): `"Intro to Forging w/ Pat"` →
  `"Intro to Forging"`; `"  Woodshop Safety  "` → `"Woodshop Safety"`; a name without
  ` w/ ` is only trimmed; `"Glaze w/o fear w/ Sam"` → `"Glaze w/o fear"` (only ` w/ `
  with spaces splits).
- `test_lookback_start` (parametrized): 2026-10-16 → 2026-06-16; 2026-06-30 → 2026-02-28;
  2028-06-30 → 2028-02-29; 2026-02-15 → 2025-10-15.
- `test_neon_search_fields_uses_end_date_and_lookback`.
- `test_class_names_from_events_dedupes_and_sorts`: three events of one class with
  different instructors give one entry; empty names are dropped.
- `test_fetch_classes_reads_neon_once_and_returns_names`: a `MagicMock` Neon client;
  asserts `search_events` was called with the lookback fields and
  `["Event ID", "Event Name"]`.
- `test_fetch_classes_propagates_neon_error`.
- `test_fuzzy_key` (parametrized, from the site's rule): `"Ceramics: Glazing Workshop"`
  and `"Ceramics__Glazing_Workshop.jpg"` → `ceramicsglazingworkshop`;
  `"Tormach_Part_2_CNC Milling.jpg"` → `tormachpart2cncmilling`;
  `"Beginner_Handbuilding__Slabs(1).jpg"` → `beginnerhandbuildingslabs(1)`;
  `"A & B & C"` → `aandb&c` (first `&` only); `"Ver. 2: Intro"` → `ver`.
- `test_exact_file_name` (parametrized): `"Ceramics: Glazing Workshop"` →
  `Ceramics__Glazing_Workshop.jpg`; `"Tormach Part 2: CNC Milling"` →
  `Tormach_Part_2__CNC_Milling.jpg`; `"Weaponized Plastic Bots"` →
  `Weaponized_Plastic_Bots.jpg`; `"Ceramics - Make a Tile Relief"` →
  `Ceramics_-_Make_a_Tile_Relief.jpg`; `"Two  spaces"` → `Two_spaces.jpg` (one `_` per run).
- `test_exact_file_name_always_passes_fuzzy` (parametrized over the class names above and
  every class-like name in the fixtures): `fuzzy_key(exact_file_name(n)) == fuzzy_key(n)`.
- `test_file_name_problem` (parametrized): `"AC/DC Basics"` and `"Back\\slash"` and a name
  with `\x07` are refused, the message naming the character; `"   "` is refused;
  `"Tea & Clay (Ages 12+)"` is accepted.
- `test_superseded_images_against_current_repository` (uses
  `asmbly_classes_images_bdf601b.json`; these are the expected results for those files):

  | Class name | Exact file | Superseded (removed) |
  | --- | --- | --- |
  | Tormach Part 2: CNC Milling | `Tormach_Part_2__CNC_Milling.jpg` (exists, replaced) | `Tormach_Part_2_CNC Milling.jpg`, `Tormach_Part_2__CNC Milling.jpg` |
  | Ceramics: Glazing Workshop | `Ceramics__Glazing_Workshop.jpg` | `Ceramics_Glazing_Workshop.jpg` |
  | Forging: Make a Tool | `Forging__Make_a_Tool.jpg` | `Forging_Make_a_Tool.jpg` |
  | Leatherworking: Make a Belt | `Leatherworking__Make_a_Belt.jpg` | `Leatherworking_-_Make_A_Belt.jpg` |
  | Bambulab P1S: Techniques | `Bambulab_P1S__Techniques.jpg` | `Bambulab_P1S___Techniques.jpg` (not `Bambulabs_P1S__Techniques.jpg`, a different key) |
  | Weaponized Plastic Bots | `Weaponized_Plastic_Bots.jpg` (new) | `Weaponized Plastic Bots.jpg` |
  | Microcontrollers: Make a Robotic Arm | `Microcontrollers__Make_a_Robotic_Arm.jpg` (new) | `Microcontrollers_Make_a_Robotic_Arm.jpg` (not the misspelt `Microcontollers_…`) |
  | Epoxy Resin: Techniques | `Epoxy_Resin__Techniques.jpg` | none (`Epoxy_Resin__Techniques(1).jpg` has key `…techniques(1)`) |
  | Beginner Handbuilding: Slabs | `Beginner_Handbuilding__Slabs.jpg` | none (`…Slabs(1).jpg` doesn't match) |
  | Beginner Handbuilding: Pinch and Coil | `Beginner_Handbuilding__Pinch_and_Coil.jpg` (new) | none (`Beginner_Hanbuilding__Pinch and Coil.jpg` is misspelt) |

  The class names are assumed (the Neon names aren't in this repository); the test says
  so in a comment. No row ever removes `GabriellePierce.jpg`, `SavannaHarvey.jpg`,
  `CNCMentorPlaceholder.jpg`, `NeonLogo.jpg` or a `*Default.jpg`.
- `test_pr49_names` (uses `asmbly_classes_pr49_images.json`): for each PR #49 name,
  record whether `exact_file_name` of the class name it was meant for would produce it.
  Concretely assert: `Tormach_Part_2_CNC Milling.jpg`, `Beginner_Hanbuilding__Pinch and Coil.jpg`,
  `Beginner_Handbuilding__Slabs(1).jpg`, `Epoxy_Resin__Techniques(1).jpg`,
  `Forging_Make_a_Tool.jpg` and `Microcontollers_Make_a_Robotic_Arm.jpg` are not the
  exact file name of their (assumed) classes, and that `Ceramics__Glazing_Workshop.jpg`,
  `Forging__Make_a_Railroad_Spike_Knife.jpg`, `Leatherworking__Make_a_Set_of_Bracers.jpg`
  and `Woodworking__Make_a_Side_Table.jpg` are. Also assert every PR #49 name that
  contains a space is never an exact file name (the exact rule turns spaces into `_`).
- `test_superseded_images_respects_extensions`: `Foo_Bar.png` is superseded for
  "Foo: Bar" when `png` is in `extensions`; `Foo_Bar.txt` is not; `Foo_Bar.JPG` is not
  (the site's glob is case-sensitive and never loads it).
- `test_fuzzy_collisions_and_warning`: `["A-B Basics", "A B Basics", "Other"]` →
  collisions of `"A B Basics"` are `["A-B Basics"]`; the warning names it; no collisions
  gives `None`.
- `test_branch_name`: stable for the same name; `class-photo/tormach-part-2-cnc-milling-<8 hex>`
  for "Tormach Part 2: CNC Milling"; `"A-B Basics"` and `"A B Basics"` get different
  branches; a 200-character name gives a slug of at most 50 characters; only
  `[a-z0-9/-]` characters.

## Acceptance criteria

1. `NeonCRM.search_events` reads every page of `POST /v2/events/search`, has a timeout,
   and raises `NeonCRMError` (no body, no headers in message or logs) on failure. (#104)
2. `fetch_classes` lists each class once by `Event Name` up to ` w/ `, trimmed, for
   events ending on or after today minus `CLASS_LOOKBACK_MONTHS` (4). (#104 AC2)
3. Nothing in this phase writes to Neon: the only Neon call is `events/search`. (#104 AC6)
4. `exact_file_name` matches the My Classes rule and always passes the fuzzy rule; the
   PR #49 names it would not have produced are identified by test. (#107 AC2)
5. `superseded_images` returns exactly the other images the class list's fuzzy lookup
   would match, across the site's extensions, and nothing else. (#107 AC3)
6. `file_name_problem` refuses `/`, `\`, control characters and empty names with a message
   naming the character; `collision_warning` names the colliding classes. (#107 AC5)
7. `.venv/bin/python -m pytest` passes.

## Verification

```bash
.venv/bin/python -m pytest layers/common/python/tests/test_neoncrm.py functions/classes
.venv/bin/python -m pytest
```

No template change, so no `cfn-lint`, `sam validate` or `sam build` is needed for this
phase alone. Nothing to see on stage yet.

## Admin actions

None.

## Hand-off

- `common.neoncrm.NeonCRM.search_events(search_fields, output_fields, page_size=200,
  timeout=10.0) -> list[dict]` and `common.neoncrm.NeonCRMError`.
- `functions.classes.class_photo_upload_api.class_names`: `CLASS_LOOKBACK_MONTHS`,
  `fetch_classes(neon, today)`, `fuzzy_key`, `exact_file_name`, `file_name_problem`,
  `fuzzy_collisions`, `collision_warning`, `superseded_images(class_name, image_names,
  extensions)`, `branch_name(class_name, prefix)`.
- The packages `functions/classes/` and `functions/classes/class_photo_upload_api/`
  (with `tests/`) exist.
- `common.neoncrm.MAX_SEARCH_PAGES = 50` (the page guard). `NeonCRMError`'s message is
  `events/search failed (status <n>)` or `events/search failed (no response)`; it is
  raised `from None`, so it carries no vendor text. A JSON body without a list
  `searchResults` raises it too.
- `class_names_from_events` sorts by `str.casefold()` (ties by the exact name) and drops
  events whose `Event Name` is missing, not a string, or empty after the split.
- `collision_warning` with several classes says `Other classes, "A", "B", match the same
  photo on the class list. All of these classes will show this photo there.`; with one,
  the sentence above.
- `superseded_images` compares extensions case-sensitively (the site's glob does), so
  pass the extensions lowercase, as the site lists them.
- `branch_name` trims a trailing `-` after cutting the slug to 50 characters.
- `fetch_classes(neon, today)` expects `today` as the UTC date (phase 5 passes it).
- The function's `README.md` is phase 5's (no handler exists yet). Nothing deferred.

For phase 5 (raised by phase 1's independent review):

- **Importing `class_names` from the handler.** No existing function imports a sibling
  module. Under Lambda the handler loads as the top-level module `lambda_function`, so
  `from . import class_names` fails there; under pytest (repository root on the path) a
  bare `import class_names` fails. Phase 5 settles this, for example a relative import
  with an absolute fallback, or a `conftest.py` `sys.path` entry, and tests that the
  import works the way Lambda loads it.
- **Neon time budget.** `search_events` defaults to 10 s per page and stops at 50 pages,
  which can outlast API Gateway's 29 s. Phase 5 passes a shorter `timeout` and keeps the
  page count small enough that the whole search ends well inside 29 s (add a `max_pages`
  argument to `search_events` if needed).
- **Class names starting with `.`.** `exact_file_name` keeps a leading `.`, which gives a
  dotfile (`.Foo.jpg`) that Vite's glob never loads. Add it to the manual QA notes
  (or refuse it in `file_name_problem`, with a test).

## Fixture: current images

The names in `app/src/lib/images/` of `asmbly-classes` at `bdf601b` (131):

```json
[
  "3dprintingDefault.jpg",
  "Addressable_LEDs_-_Make_a_Lantern.jpg",
  "Addressable_LEDs__Make_a_Lantern.jpg",
  "Advanced_TIG_Welding_Aluminum.jpg",
  "Advanced_TIG_Welding__Aluminum.jpg",
  "Advanced_Turning_Vases.jpg",
  "Advanced_Turning__Vases.jpg",
  "Bambulab_P1S__Techniques.jpg",
  "Bambulab_P1S___Techniques.jpg",
  "Bambulabs_P1S__Techniques.jpg",
  "Bandsaw_Box.jpg",
  "Beginner_CNC_Router.jpg",
  "Beginner_Hanbuilding__Pinch and Coil.jpg",
  "Beginner_Handbuilding__Slabs(1).jpg",
  "Beginner_Handbuilding__Slabs.jpg",
  "Beginner_Wheel_Throwing.jpg",
  "Big_Lasers_Rotary_Engraving_Techniques.jpg",
  "Big_Lasers_Techniques.jpg",
  "Big_Lasers__Rotary_Engraving_Techniques.jpg",
  "Big_Lasers__Techniques.jpg",
  "Bowl_Turning.jpg",
  "CNCMentorPlaceholder.jpg",
  "CNC_Router_Techniques.jpg",
  "CNC_Router__Techniques.jpg",
  "Ceramics_-_Make_a_Decorative_Coil_Pot.jpg",
  "Ceramics_-_Make_a_Tile_Relief.jpg",
  "Ceramics_Glazing_Workshop.jpg",
  "Ceramics_Make_Miniature_Pottery.jpg",
  "Ceramics_Safety_and_Information_(CSI).jpg",
  "Ceramics_Studio_Introduction.jpg",
  "Ceramics__Glazing_Workshop.jpg",
  "Ceramics__Make_a_Decorative_Coil_Pot.jpg",
  "Ceramics__Wheel_Throwing_(6_Week_Course).jpg",
  "Circuit_Building_Basic_Techniques.jpg",
  "Copy of Intro_Wood_Turning__Handles.jpg",
  "Epoxy_Resin__Techniques(1).jpg",
  "Epoxy_Resin__Techniques.jpg",
  "Festool_Domino_Techniques.jpg",
  "Festool_Domino__Techniques.jpg",
  "Filament_3D_Printing_Techniques.jpg",
  "Filament_3D_Printing__Techniques.jpg",
  "Forging_Make_a_Tool.jpg",
  "Forging_Techniques.jpg",
  "Forging__Make_a_Railroad_Spike_Knife.jpg",
  "Forging__Make_a_Tool.jpg",
  "Forging__Techniques.jpg",
  "Fusion_360_CAM.jpg",
  "Fusion_360_for_3D_Printing__Beginner_Techniques.jpg",
  "GabriellePierce.jpg",
  "High_Carbon_Steel_Knife_Forge_a_Kiridashi.jpg",
  "Intro_Wood_Turning_Bowls.jpg",
  "Intro_Wood_Turning_Handles.jpg",
  "Intro_Wood_Turning__Bowls.jpg",
  "Intro_Wood_Turning__Handles.jpg",
  "Intro_to_Epoxy_Resin.jpg",
  "Intro_to_Filament_3D_Printing.jpg",
  "Intro_to_Forging.jpg",
  "Intro_to_Fusion_360_for_Wood_CNC.jpg",
  "Intro_to_Metal_Lathe.jpg",
  "Intro_to_Resin_3D_Printing.jpg",
  "Intro_to_Sublimation.jpg",
  "Intro_to_Wood_Lathe.jpg",
  "LEDs_and_Microcontrollers.jpg",
  "Leatherworking_-_Make_A_Belt.jpg",
  "Leatherworking_-_Make_A_Wallet.jpg",
  "Leatherworking_Make_a_Set_of_Bracers.jpg",
  "Leatherworking_Stamping_and_Tooling_Techniques.jpg",
  "Leatherworking__Make_a_Belt.jpg",
  "Leatherworking__Make_a_Set_of_Bracers.jpg",
  "Leatherworking__Make_a_Wallet.jpg",
  "Leatherworking__Stamping_and_Tooling_Techniques.jpg",
  "MIG_Welding.jpg",
  "MIG_Welding__Techniques.jpg",
  "Machine_Embroidery__Techniques.jpg",
  "Metal_Lathe_Techniques.jpg",
  "Metal_Lathe__Techniques.jpg",
  "Metal_Shop_Safety.jpg",
  "Metalshop_Safety.jpg",
  "Microcontollers_Make_a_Robotic_Arm.jpg",
  "Microcontrollers_Make_a_Robotic_Arm.jpg",
  "Mig_Welding_Techniques.jpg",
  "Milling_Techniques.jpg",
  "Milling__Techniques.jpg",
  "NeonLogo.jpg",
  "PCBWay_Soldering_Activity.jpg",
  "Resin_3D_Printing_Techniques.jpg",
  "Resin_3D_Printing__Techniques.jpg",
  "SavannaHarvey.jpg",
  "Serger_-_Techniques.jpg",
  "Serger__Techniques.jpg",
  "Sewing_-_Make_a_Lined_Tote_Bag.jpg",
  "Sewing_-_Techniques.jpg",
  "Sewing_Make_a_Pillowcase.jpg",
  "Sewing__Make_a_Pillowcase.jpg",
  "Sewing__Techniques.jpg",
  "Shaper_Origin_Techniques.jpg",
  "Shaper_Origin__Techniques.jpg",
  "Small_Laser__Rotary_Engraving_Techniques.jpg",
  "Small_Lasers_Rotary_Engraving_Techniques.jpg",
  "Small_Lasers_Techniques.jpg",
  "Small_Lasers__Rotary_Engraving_Techniques.jpg",
  "Small_Lasers__Techniques.jpg",
  "Stationary_Sanders_Techniques.jpg",
  "Stationary_Sanders__Techniques.jpg",
  "Sublimation_-_Techniques.jpg",
  "Sublimation_Printing__Techniques.jpg",
  "TIG_Welding_Steel.jpg",
  "TIG_Welding__Steel.jpg",
  "Tormach_Part_1_Fusion_360_CAM.jpg",
  "Tormach_Part_1__Fusion_360_CAM.jpg",
  "Tormach_Part_2_CNC Milling.jpg",
  "Tormach_Part_2__CNC Milling.jpg",
  "Tormach_Part_2__CNC_Milling.jpg",
  "Vinyl_Cutter_-_Techniques.jpg",
  "Vinyl_Cutter__Techniques.jpg",
  "Weaponized Plastic Bots.jpg",
  "Woodshop_Safety.jpg",
  "Woodworking_Box_Building_Techniques.jpg",
  "Woodworking_Make_a_Groovy_Cutting_Board.jpg",
  "Woodworking_Make_a_Side_Table.jpg",
  "Woodworking_Make_a_Sturdy_Cutting_Board.jpg",
  "Woodworking__Box_Building_Techniques.jpg",
  "Woodworking__Make_a_Groovy_Cutting_Board.jpg",
  "Woodworking__Make_a_Side_Table.jpg",
  "ceramicsDefault.jpg",
  "classDefault.jpg",
  "electronicsDefault.jpg",
  "lasersDefault.jpg",
  "metalworkingDefault.jpg",
  "textilesDefault.jpg",
  "woodworkingDefault.jpg"
]
```

## Fixture: PR #49

The image files PR #49 adds (`A`) or changes (`M`), relative to its merge base
`54b8448` (56):

```json
[
  {"status": "A", "name": "Advanced_TIG_Welding_Aluminum.jpg"},
  {"status": "M", "name": "Bambulabs_P1S__Techniques.jpg"},
  {"status": "A", "name": "Beginner_Hanbuilding__Pinch and Coil.jpg"},
  {"status": "A", "name": "Beginner_Handbuilding__Slabs(1).jpg"},
  {"status": "M", "name": "Beginner_Handbuilding__Slabs.jpg"},
  {"status": "M", "name": "Beginner_Wheel_Throwing.jpg"},
  {"status": "A", "name": "Big_Lasers_Rotary_Engraving_Techniques.jpg"},
  {"status": "A", "name": "Big_Lasers_Techniques.jpg"},
  {"status": "A", "name": "CNCMentorPlaceholder.jpg"},
  {"status": "M", "name": "CNC_Router_Techniques.jpg"},
  {"status": "M", "name": "Ceramics_-_Make_a_Decorative_Coil_Pot.jpg"},
  {"status": "M", "name": "Ceramics_-_Make_a_Tile_Relief.jpg"},
  {"status": "M", "name": "Ceramics_Studio_Introduction.jpg"},
  {"status": "A", "name": "Ceramics__Glazing_Workshop.jpg"},
  {"status": "A", "name": "Epoxy_Resin__Techniques(1).jpg"},
  {"status": "M", "name": "Epoxy_Resin__Techniques.jpg"},
  {"status": "M", "name": "Festool_Domino_Techniques.jpg"},
  {"status": "M", "name": "Filament_3D_Printing_Techniques.jpg"},
  {"status": "A", "name": "Forging_Make_a_Tool.jpg"},
  {"status": "A", "name": "Forging_Techniques.jpg"},
  {"status": "A", "name": "Forging__Make_a_Railroad_Spike_Knife.jpg"},
  {"status": "M", "name": "Fusion_360_for_3D_Printing__Beginner_Techniques.jpg"},
  {"status": "A", "name": "GabriellePierce.jpg"},
  {"status": "A", "name": "High_Carbon_Steel_Knife_Forge_a_Kiridashi.jpg"},
  {"status": "M", "name": "Intro_Wood_Turning_Bowls.jpg"},
  {"status": "M", "name": "Intro_Wood_Turning_Handles.jpg"},
  {"status": "M", "name": "Leatherworking_-_Make_A_Belt.jpg"},
  {"status": "M", "name": "Leatherworking_-_Make_A_Wallet.jpg"},
  {"status": "A", "name": "Leatherworking__Make_a_Set_of_Bracers.jpg"},
  {"status": "A", "name": "Leatherworking__Stamping_and_Tooling_Techniques.jpg"},
  {"status": "A", "name": "Metal_Lathe_Techniques.jpg"},
  {"status": "A", "name": "Metalshop_Safety.jpg"},
  {"status": "A", "name": "Microcontollers_Make_a_Robotic_Arm.jpg"},
  {"status": "A", "name": "Mig_Welding_Techniques.jpg"},
  {"status": "A", "name": "Milling_Techniques.jpg"},
  {"status": "M", "name": "Resin_3D_Printing_Techniques.jpg"},
  {"status": "A", "name": "SavannaHarvey.jpg"},
  {"status": "M", "name": "Serger_-_Techniques.jpg"},
  {"status": "M", "name": "Sewing_-_Make_a_Lined_Tote_Bag.jpg"},
  {"status": "M", "name": "Sewing_-_Techniques.jpg"},
  {"status": "A", "name": "Sewing__Make_a_Pillowcase.jpg"},
  {"status": "M", "name": "Shaper_Origin_Techniques.jpg"},
  {"status": "A", "name": "Small_Lasers_Rotary_Engraving_Techniques.jpg"},
  {"status": "A", "name": "Small_Lasers_Techniques.jpg"},
  {"status": "M", "name": "Stationary_Sanders_Techniques.jpg"},
  {"status": "M", "name": "Sublimation_-_Techniques.jpg"},
  {"status": "M", "name": "TIG_Welding_Steel.jpg"},
  {"status": "A", "name": "Tormach_Part_1_Fusion_360_CAM.jpg"},
  {"status": "A", "name": "Tormach_Part_2_CNC Milling.jpg"},
  {"status": "M", "name": "Vinyl_Cutter_-_Techniques.jpg"},
  {"status": "M", "name": "Weaponized Plastic Bots.jpg"},
  {"status": "M", "name": "Woodshop_Safety.jpg"},
  {"status": "A", "name": "Woodworking_Box_Building_Techniques.jpg"},
  {"status": "M", "name": "Woodworking_Make_a_Sturdy_Cutting_Board.jpg"},
  {"status": "A", "name": "Woodworking__Make_a_Groovy_Cutting_Board.jpg"},
  {"status": "A", "name": "Woodworking__Make_a_Side_Table.jpg"}
]
```
