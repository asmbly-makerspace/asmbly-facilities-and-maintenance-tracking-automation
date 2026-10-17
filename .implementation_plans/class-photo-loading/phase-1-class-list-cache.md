---
phase_id: 1
title: Class-list cache, scheduled refresh and Neon timing
epic: 114
implements: [116]
depends_on: []
domain: [lambda, infra, docs]
estimated_size: L
---

# Phase 1: Class-list cache, scheduled refresh and Neon timing

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md` ("Rules", "Done means verified"), this plan's README (Decisions 2–9, Security).
- #116 (the acceptance criteria) and #114 (the spec, "Done when").
- `functions/classes/class_photo_upload_api/lambda_function.py`: `load_classes()`,
  `handle_classes()`, `lambda_handler()` (the env check, then `caller_claims`, then the
  route).
- `functions/classes/class_photo_upload_api/class_names.py`: `fetch_classes()` and its log
  line; `NEON_PAGE_TIMEOUT_SECONDS`, `NEON_MAX_PAGES`.
- `layers/common/python/common/neoncrm.py`: `search_events()` (default `page_size=200`;
  not changed in this plan).
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`: the `env` and
  `mocks` fixtures and `test_classes_*`.
- `templates/classes.yaml` (`ClassPhotoUploadApiFunction`, `IsProd`) and the closest
  examples: `SlackReorderStateTable` in `templates/purchase_request.yaml` (table) and
  `PMReminderBotScheduleRule` / `PMReminderBotSchedulePermission` in
  `templates/facilities.yaml` (rule and permission).
- `template-cicd.yaml`: `AllowDynamoDBTableManagement` and
  `AllowEventBridgeRuleManagement` in both `GitHubDeployPolicystage` and
  `GitHubDeployPolicyprod`.
- `functions/networking/dynamic_dns_update/lambda_function.py`: the style to follow
  (lazy logging, typed helpers, plain messages).

## Goal

`GET /class-photo-upload/classes` answers from a per-stage cache: under 2 s once the cache
is filled. An EventBridge schedule refreshes the cache in the background (every 15
minutes on prod, 60 on other stages) by invoking the existing API function. A miss or an
entry over 3 hours old reads Neon live and writes the cache; Neon failing while a copy
exists serves the copy, marked stale. Every Neon read logs its time, events, pages and
classes, and every class-list answer logs where the list came from and how old it is.
`POST /class-photo-upload/submit` is not changed in this phase (it keeps reading Neon live
through the same function; phase 2 moves it to the cache).

## Files to create

- `functions/classes/class_photo_upload_api/class_cache.py`: the cache (read, write,
  decide, refresh). No AWS client is created here; callers pass the table.
- `functions/classes/class_photo_upload_api/tests/test_class_cache.py`: unit tests with
  `moto`.

## Files to modify

- `functions/classes/class_photo_upload_api/lambda_function.py`: `CLASS_CACHE_TABLE_NAME`
  in `REQUIRED_ENV`; `_cache_table()`; `read_classes_from_neon()` (the old `load_classes`
  body plus timing); `handle_classes()` through the cache; the scheduled-refresh branch in
  `lambda_handler()`.
- `functions/classes/class_photo_upload_api/class_names.py`: `NEON_PAGE_SIZE`, and
  `fetch_classes()`'s log line gains milliseconds and pages.
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`: a moto table
  in the fixtures; new route and refresh tests.
- `functions/classes/class_photo_upload_api/tests/test_class_names.py`: the page-size
  constant matches the helper's default.
- `templates/classes.yaml`: table, rule, invoke permission, environment variable, IAM
  statement.
- `template-cicd.yaml`: the table and the rule in both deploy policies.
- `functions/classes/class_photo_upload_api/README.md`: "How It Works" (the cache and the
  refresh), "Responses" (`refreshed_at`, `stale`), "AWS Infrastructure", "Configuration",
  "Limits", "Testing".
- `docs/README.md`: the Class Photo Upload entry (what it does, how it's triggered, config
  location).

## Implementation details

### lambda

**`class_names.py`**

- Add `NEON_PAGE_SIZE = 200  # NeonCRM.search_events's default page_size; not passed, so
  the call's arguments don't change`.
- `fetch_classes()` measures its own time (`time.monotonic()`) and logs, replacing today's
  line:
  `logger.info("Neon read %d events (%d pages) in %d ms: %d classes", len(events), pages, elapsed_ms, len(classes))`
  with `pages = max(1, math.ceil(len(events) / NEON_PAGE_SIZE))`. The call to
  `neon.search_events` keeps exactly its current arguments (the existing test asserts
  `{"timeout": 4.0, "max_pages": 8}`). Return type unchanged (`list[str]`).

**`class_cache.py`** (new; type hints on everything; `logging` with lazy arguments)

```python
CACHE_KEY = "class-list"          # the one item's partition key value
SCHEMA_VERSION = 1
MAX_AGE_SECONDS = 3 * 60 * 60     # README Decision 5

SOURCE_CACHE = "cache"            # a cached copy under MAX_AGE_SECONDS
SOURCE_NEON = "neon"              # read live (miss, or the copy was too old)
SOURCE_STALE = "stale_cache"      # too old, and Neon failed

@dataclass(frozen=True)
class CachedList:
    names: list[str]
    refreshed_at: datetime.datetime   # aware, UTC

@dataclass(frozen=True)
class ClassList:
    names: list[str]
    refreshed_at: datetime.datetime
    source: str                       # one of the SOURCE_* values
    @property
    def stale(self) -> bool: ...      # source == SOURCE_STALE
    def age_seconds(self, now: datetime.datetime) -> int: ...   # never negative

def read_cache(table: Any) -> CachedList | None
def write_cache(table: Any, names: list[str], refreshed_at: datetime.datetime) -> None
def get_class_list(table: Any, read_neon: Callable[[], list[str]], now: datetime.datetime) -> ClassList
def refresh(table: Any, read_neon: Callable[[], list[str]], now: datetime.datetime) -> bool
def format_time(moment: datetime.datetime) -> str   # "2026-10-17T14:05:00Z"
```

- **Item** (attribute names exact): `cache_key` (S, `"class-list"`), `version` (N, `1`),
  `classes` (S, `json.dumps(names)`), `class_count` (N), `refreshed_at` (S, ISO 8601 UTC
  with `Z`, seconds precision). Nothing else: no event IDs, no instructor names (the names
  are already cut at " w/ " by `class_names_from_events`).
- **`read_cache`**: `table.get_item(Key={"cache_key": CACHE_KEY}, ConsistentRead=True)`.
  Returns `None` (a miss) and logs at INFO/WARNING with a fixed reason when: there is no
  item (`"Class list cache: empty"`); `version` isn't 1, `classes` isn't a JSON list of
  non-empty strings, or `refreshed_at` doesn't parse (`"Class list cache: unreadable
  item (%s)"` with the reason name, never the value); the call raises
  `botocore.exceptions.BotoCoreError` or `ClientError` (`"Class list cache: read failed:
  %s"`, `type(e).__name__`, plus the error code for `ClientError`).
- **`write_cache`**: `table.put_item(Item=...)` (unconditional; two writers both write a
  fresh list, last wins). A `BotoCoreError` or `ClientError` is logged as a warning
  (`"Class list cache: write failed: %s"`) and swallowed: the caller still has the live
  list.
- **`get_class_list`** (the request path):
  1. `cached = read_cache(table)`.
  2. `cached` and its age ≤ `MAX_AGE_SECONDS` → `ClassList(cached.names, cached.refreshed_at, SOURCE_CACHE)`. Neon is not called.
  3. Otherwise call `read_neon()`. On success: `write_cache(table, names, now)` and return
     `ClassList(names, now, SOURCE_NEON)`.
  4. `read_neon()` raised: if `cached` exists, log a warning
     (`"Neon failed; serving the cached class list, %d minutes old"`) and return
     `ClassList(cached.names, cached.refreshed_at, SOURCE_STALE)`; otherwise re-raise the
     same exception (the handler turns it into the 502).
  An age is `max(0, now - refreshed_at)`, so a clock skew can't make it negative.
- **`refresh`** (the schedule): `read_neon()`; on success `write_cache(...)` and return
  `True`. On any exception: log a warning with `type(e).__name__` and the cached copy's
  age in minutes (`read_cache`), or `"no cached list"`, and return `False`. Never raises
  (README Decision 6).

**`lambda_function.py`**

- `REQUIRED_ENV` gains `"CLASS_CACHE_TABLE_NAME"` (set by the template).
- `_dynamodb: Any = None` at module level and
  `def _cache_table() -> Any:` which creates once
  `boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION"), config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 2}))`
  and returns `.Table(os.environ["CLASS_CACHE_TABLE_NAME"])` (README Decision 7). Import
  `boto3` and `botocore.config.Config` (both in the Lambda runtime and
  `requirements-dev.txt`).
- `read_classes_from_neon() -> list[str]`: today's `load_classes()` body (secret, then
  `class_names.fetch_classes`), unchanged in what it raises (`Refusal(502, NEON_ERROR,
  "neon_secret")` / `"neon"`); on the Neon failure it also logs the elapsed time:
  `"Couldn't read the class list from Neon after %d ms: %s"`.
- Keep `load_classes()` as a thin alias of `read_classes_from_neon()` for `handle_submit`
  in this phase (phase 2 replaces that call). Its docstring says so.
- `handle_classes(dry_run: bool) -> dict[str, Any]`:

  ```python
  now = datetime.datetime.now(datetime.timezone.utc)
  class_list = class_cache.get_class_list(_cache_table(), read_classes_from_neon, now)
  logger.info("Class list from %s (age %d s): %d classes", class_list.source, class_list.age_seconds(now), len(class_list.names))
  return _response(200, {"dry_run": dry_run, "classes": class_list_entries(class_list.names),
                         "refreshed_at": class_cache.format_time(class_list.refreshed_at),
                         "stale": class_list.stale})
  ```

  A `Refusal` from `read_classes_from_neon` (no cached copy, Neon or the secret failed)
  passes through to the existing `except Refusal` (502, `NEON_ERROR`).
- **Scheduled refresh**, in `lambda_handler` after the `REQUIRED_ENV` loop and before
  `caller_claims`:

  ```python
  def is_scheduled_refresh(event: Any) -> bool:
      return (
          isinstance(event, dict)
          and event.get("source") == "aws.events"
          and event.get("detail-type") == "Scheduled Event"
          and "httpMethod" not in event
          and "requestContext" not in event
      )

  def handle_refresh() -> dict[str, Any]:
      now = datetime.datetime.now(datetime.timezone.utc)
      try:
          refreshed = class_cache.refresh(_cache_table(), read_classes_from_neon, now)
      except Exception as e:  # a bug in the refresh path must not make Lambda retry
          logger.error("Scheduled class list refresh failed: %s", type(e).__name__)
          refreshed = False
      logger.info("Scheduled class list refresh: %s", "done" if refreshed else "kept the cached list")
      return {"refreshed": refreshed}
  ```

  The refresh never reads `GITHUB_APP_SECRET_NAME` or the SSM config and never calls
  GitHub. Its return value is ignored by EventBridge. Its log lines have no `sub`.
- Everything else (claims check, routes, `handle_submit`) is unchanged.

**Responses** (`GET /class-photo-upload/classes`, 200), new fields after the existing ones:

```json
{"dry_run": true, "classes": [...], "refreshed_at": "2026-10-17T14:05:00Z", "stale": false}
```

502 `NEON_ERROR` only when there is no cached copy and Neon (or the Neon secret) fails.

**Logs** (new or changed lines, no names of people, no tokens, no bodies):
`Neon read %d events (%d pages) in %d ms: %d classes`;
`Couldn't read the class list from Neon after %d ms: %s`;
`Class list from %s (age %d s): %d classes`; `Class list cache: empty` /
`unreadable item (%s)` / `read failed: %s` / `write failed: %s`;
`Neon failed; serving the cached class list, %d minutes old`;
`Scheduled class list refresh: done` / `kept the cached list`;
`Scheduled class list refresh failed: %s`. Together with `submit`'s live read (still
`Neon read …` in this phase) every route logs Neon's time (#116 criterion 6).

### infra

**`templates/classes.yaml`**: add after `ClassPhotoUploadConfigParameter`:

```yaml
  # One item: the class names read from Neon and when. Refreshed by
  # ClassPhotoClassListRefreshRule; no TTL, so a copy outlives a Neon outage.
  ClassPhotoClassListCacheTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub "ClassPhotoClassListCache-${Stage}"
      AttributeDefinitions:
        - AttributeName: cache_key
          AttributeType: S
      KeySchema:
        - AttributeName: cache_key
          KeyType: HASH
      BillingMode: PAY_PER_REQUEST
      Tags:
        - Key: Project
          Value: classes:class-photo-upload
```

In `ClassPhotoUploadApiFunction`:

```yaml
      Environment:
        Variables:
          # ...existing five...
          CLASS_CACHE_TABLE_NAME: !Ref ClassPhotoClassListCacheTable
      Policies:
        - Version: '2012-10-17'
          Statement:
            # ...existing two statements...
            - Effect: Allow
              Action:
                - dynamodb:GetItem
                - dynamodb:PutItem
              Resource: !GetAtt ClassPhotoClassListCacheTable.Arn
```

Update its `Description` to mention the cache ("Lists classes from Neon (cached, refreshed
on a schedule) and turns …").

After the function:

```yaml
  # Refreshes the cached class list in the background (README of the API function,
  # "The class list cache"). Every stage reads the prod Neon account, so non-prod
  # stages refresh less often.
  ClassPhotoClassListRefreshRule:
    Type: AWS::Events::Rule
    Properties:
      Name: !Sub "class-photo-class-list-refresh-${Stage}"
      Description: "Refreshes the class photo upload page's cached class list from Neon."
      ScheduleExpression: !If [IsProd, "rate(15 minutes)", "rate(60 minutes)"]
      State: "ENABLED"
      Targets:
        - Arn: !GetAtt ClassPhotoUploadApiFunction.Arn
          Id: "ClassPhotoClassListRefreshTarget"
      Tags:
        - Key: Project
          Value: classes:class-photo-upload

  ClassPhotoClassListRefreshPermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !GetAtt ClassPhotoUploadApiFunction.Arn
      Action: "lambda:InvokeFunction"
      Principal: "events.amazonaws.com"
      SourceArn: !GetAtt ClassPhotoClassListRefreshRule.Arn
```

No new template parameter (so nothing new to pass from `template.yaml`); no new output.
`template.yaml` is not changed.

**`template-cicd.yaml`**, in `GitHubDeployPolicystage` (and the same with `-prod` in
`GitHubDeployPolicyprod`):

- `AllowDynamoDBTableManagement`: `Resource` becomes a list:

  ```yaml
            Resource:
              - !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/SlackReorderStateTable-stage"
              - !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/ClassPhotoClassListCache-stage"
  ```

- `AllowEventBridgeRuleManagement`: `Resource` becomes a list with
  `rule/pm-reminder-bot-schedule-stage` and
  `rule/class-photo-class-list-refresh-stage`.
- A new statement right after it, for the new rule's tags only (the rule has `Tags`, and
  CloudFormation's `AWS::Events::Rule` handler needs these to apply them):

  ```yaml
          - Sid: AllowClassListRefreshRuleTagging
            Effect: Allow
            Action:
              - events:TagResource
              - events:UntagResource
              - events:ListTagsForResource
            Resource: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/class-photo-class-list-refresh-stage"
  ```

No other deploy-role change: `lambda:AddPermission`/`RemovePermission` on
`ClassPhotoUploadApiFunction-{stage,prod}` and the role-management statements already
cover the permission and the function's policy. No wildcard is added.

### docs

- API `README.md`: a new section **The Class List Cache** (what is stored, the item's
  attributes, the schedule per stage, the 3-hour maximum age, the four outcomes: hit,
  miss, too old, Neon down with a copy; how to empty it by hand: delete the item
  `cache_key = class-list` in the table; the next request reads Neon), "Responses"
  (`refreshed_at`, `stale`, when 502 happens now), "AWS Infrastructure" (table, rule,
  permission, IAM statement), "Configuration" (`CLASS_CACHE_TABLE_NAME`, now five required
  variables), "Limits" (Neon is off the request path when the cache is warm; the refresh
  takes one of the 3 concurrent slots for a few seconds), "Testing" (`test_class_cache.py`,
  moto). Note that submit still reads Neon live until phase 2.
- `docs/README.md`, Class Photo Upload entry: **What it does** gains one sentence (the class
  list is cached per stage and refreshed from Neon every 15 minutes on prod, 60 on stage);
  **How it's triggered** adds the EventBridge rule
  `class-photo-class-list-refresh-${Stage}` invoking `ClassPhotoUploadApiFunction`;
  **Config Location** adds the table `ClassPhotoClassListCache-${Stage}` (created by
  `templates/classes.yaml`).

## Tests

`tests/test_class_cache.py` (moto `mock_aws`, a fixture creating the table
`ClassPhotoClassListCache-test` with key `cache_key`; `now` passed explicitly):

- `test_read_cache_empty_table_is_a_miss`: no item → `None`, logs "empty".
- `test_write_then_read_round_trips`: names and `refreshed_at` come back equal; the stored
  item has exactly the five attributes.
- `test_read_cache_unreadable_items_are_a_miss` (parametrized: wrong `version`, `classes`
  not JSON, `classes` not a list of strings, bad `refreshed_at`): `None`, logs the reason
  name, not the value.
- `test_read_cache_dynamodb_error_is_a_miss`: a table whose `get_item` raises
  `ClientError` → `None`, logs the error type.
- `test_hit_serves_cache_without_neon` (#114 "a hit"): fresh item → `SOURCE_CACHE`,
  `read_neon` not called.
- `test_miss_reads_neon_and_writes_cache` (#114 "a miss"): empty table → `SOURCE_NEON`,
  `read_neon` called once, item now holds the names and `now`.
- `test_entry_at_max_age_is_still_a_hit` and `test_stale_entry_reads_neon_and_replaces_it`
  (#114 "a stale entry"): age exactly `MAX_AGE_SECONDS` → hit; one second more → Neon
  called, item replaced, `SOURCE_NEON`.
- `test_neon_failure_with_cached_copy_serves_it_stale` (#114 "Neon failing while a cached
  copy exists"): old item, `read_neon` raises → `SOURCE_STALE`, `stale` true, the old
  names and time, item unchanged, warning logged with minutes.
- `test_neon_failure_without_copy_reraises`: empty table, `read_neon` raises a sentinel
  exception → the same exception propagates; nothing written.
- `test_write_failure_still_returns_live_list`: `put_item` raises `ClientError` → the live
  list with `SOURCE_NEON`, warning logged.
- `test_future_refreshed_at_counts_as_fresh`: `refreshed_at` after `now` → age 0, hit.
- `test_refresh_writes_fresh_list` / `test_refresh_failure_keeps_item_and_returns_false`
  (logs age) / `test_refresh_failure_with_empty_cache_logs_no_cached_list`.

`tests/test_lambda_function.py`:

- Fixtures: a `cache_table` fixture (moto `mock_aws`, creates
  `ClassPhotoClassListCache-test`, sets `CLASS_CACHE_TABLE_NAME`, resets
  `lambda_function._dynamodb` with `monkeypatch.setattr`), used by `mocks`, so every
  existing test runs against an empty cache (a live read, as today). `ENV` gains
  `CLASS_CACHE_TABLE_NAME`, so `test_missing_env_returns_500` covers it.
- The existing `test_classes_*` tests keep passing unchanged (empty cache → live read).
  `test_classes_returns_names_problems_and_warnings` also asserts `stale is False` and a
  `refreshed_at` matching `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$`.
- `test_classes_second_call_is_served_from_cache`: two calls; Neon's `search_events`
  called once; the log says `Class list from cache`.
- `test_classes_cached_list_survives_neon_failure`: an item older than 3 hours, Neon
  raises `NeonCRMError` → 200, the cached names, `stale` true.
- `test_classes_neon_failure_without_cache_returns_502` (the existing 502 test, now
  explicit about the empty cache).
- `test_classes_logs_neon_time`: after a live read the log has
  `Neon read 5 events (1 pages) in` and `ms: 4 classes`.
- `test_scheduled_event_refreshes_cache_without_github`: an EventBridge scheduled event
  (`{"source": "aws.events", "detail-type": "Scheduled Event", "detail": {}, ...}`, a new
  fixture `tests/fixtures/scheduled_event.json`) → `{"refreshed": True}`; the item holds
  the names; `github_app` and `aws.get_secret_json` / `aws.get_json_parameter` not called.
- `test_scheduled_refresh_neon_failure_keeps_cache`: Neon raises → `{"refreshed": False}`,
  item unchanged, warning logged, no exception.
- `test_http_event_with_scheduled_keys_still_needs_claims`: the classes fixture event with
  `source` and `detail-type` added and the claims removed → 403, Neon and the table not
  touched.
- `test_scheduled_refresh_logs_no_names`: no class name, `USERMARKER` or token in the log
  of a refresh.

`tests/test_class_names.py`:

- `test_page_size_matches_the_helper_default`: `NEON_PAGE_SIZE ==
  inspect.signature(NeonCRM.search_events).parameters["page_size"].default`.
- `test_fetch_classes_logs_counts_not_names` (line 153) asserts today's
  `"Read 1 events, 1 classes"`; update it to the new line (`"Neon read 1 events (1 pages)
  in "` and `" ms: 1 classes"`), keeping its `"Pat" not in caplog.text` check. This is a
  log line, not a message anyone sees. `test_module_logs_nothing_but_fetch_classes` keeps
  passing (the module still logs only from `fetch_classes`).

## Acceptance criteria

1. With an item under 3 hours old, `GET /class-photo-upload/classes` doesn't call Neon or
   read the Neon secret, and answers the cached names with `refreshed_at` and
   `stale: false` (#116 AC1). Tests: `test_hit_serves_cache_without_neon`,
   `test_classes_second_call_is_served_from_cache`.
2. With an empty cache, the first request reads Neon live, answers the list and writes it
   (#116 AC3). Test: `test_miss_reads_neon_and_writes_cache`.
3. With a copy over 3 hours old and Neon failing, the answer is 200 with the copy and
   `stale: true`; with no copy and Neon failing, 502 "Couldn't load the class list. Try
   again in a minute." (#116 AC4).
4. An EventBridge scheduled event refreshes the item without reading the GitHub secret or
   the SSM config; a failed refresh keeps the item and returns normally; an HTTP event
   with the scheduled keys still needs valid claims (#116 AC5).
5. Every live Neon read logs its milliseconds, events, pages and classes; every class-list
   answer logs its source and age (#116 AC6).
6. `templates/classes.yaml` has `ClassPhotoClassListCache-${Stage}` (on-demand, `Project`
   tag, no TTL), `class-photo-class-list-refresh-${Stage}` (`rate(15 minutes)` on prod,
   `rate(60 minutes)` otherwise, `Project` tag), and the permission for
   `events.amazonaws.com` from that rule only; the function can only `GetItem` and
   `PutItem` on its table (#116 AC7).
7. Both deploy policies list the table and the rule for their stage, and the rule's
   tagging actions are on that rule's ARN only.
8. The cached item holds only `cache_key`, `version`, `classes`, `class_count` and
   `refreshed_at` (#116 AC7).
9. The API README and `docs/README.md` describe the cache, how it is refreshed and where it
   lives (#114 "Done when", last box).

## Verification

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_api
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

After the stage deploy (and Admin action 1 before it):

- `aws dynamodb describe-table --table-name ClassPhotoClassListCache-stage --region us-east-2`
  shows the table; `aws events describe-rule --name class-photo-class-list-refresh-stage
  --region us-east-2` shows `rate(60 minutes)`, `ENABLED`.
- Open the stage page: the first load may take about 8 s (cache empty); reload: the class
  list arrives in under 2 s, and `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` shows
  `Class list from cache (age … s)`, with a `Neon read … ms` line from the first load.
- Within an hour, the log shows `Scheduled class list refresh: done`.

## Admin actions

Before this reaches `stage`: redeploy `AsmblyFacilitiesMaintTrackingStack-cicd`
(`docs/Deploying.md`, "CI/CD Infrastructure (The Deployer Role)"); the table and the rule
names are new in both deploy policies, and the stage deploy fails without them. README
Admin actions 1 and 2.

## Hand-off

_Filled in when the phase is done._ Phase 2 can rely on:
`class_cache.get_class_list(table, read_neon, now) -> ClassList` (`names`,
`refreshed_at`, `source`, `stale`, `age_seconds(now)`), `class_cache.MAX_AGE_SECONDS`,
`lambda_function._cache_table()`, `lambda_function.read_classes_from_neon()`, the
`cache_table` test fixture, and `load_classes()` still used by `handle_submit`. Phase 3
can rely on `/classes` answering `refreshed_at` (ISO 8601 UTC, `Z`) and `stale` (boolean).
