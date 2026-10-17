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

> **Status:** [x] Complete — 2026-10-16 on branch feature/class-photo-loading

> **Amended 2026-10-16 (prep, owner changes).** The owner changed the refresh to once a
> day on prod only, added a manual refresh, and asked for the cache behind a small
> interface (README Decisions 19–22 and "Design"). Prep also added the DynamoDB and
> EventBridge read actions CloudFormation's handlers call (README Admin actions 1).
> Where this document and an older README decision disagree, this document and
> Decisions 19–22 win.

## Required reading

- `CLAUDE.md` ("Rules", "Done means verified"), this plan's README (Decisions 2, 3, 6–9,
  19–22, "Design", Security).
- #116 (the acceptance criteria) and #114 (the spec, "Done when").
- `functions/classes/class_photo_upload_api/lambda_function.py`: `load_classes()`,
  `handle_classes()`, `lambda_handler()` (the env check, then `caller_claims`, then the
  route), the relative-import fallback for sibling modules.
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
- `functions/purchase_request/slack_slash_reorder/`: the repository's other DynamoDB
  user and its moto test (but don't copy its module-level `os.environ` writes in tests).

## Goal

`GET /class-photo-upload/classes` answers from a per-stage cache: under 2 s once the cache
is filled. On prod an EventBridge schedule refreshes the cache once a day (10:00 UTC) by
invoking the existing API function; stage and other stages have no schedule. A miss or a
copy over 26 hours old reads Neon live and writes the cache; Neon failing while a copy
exists serves the copy, marked stale. Signed-in staff can ask for a refresh
(`GET /class-photo-upload/classes?refresh=1`, the page's **Refresh class list** button in
phase 3): it reads Neon live and rewrites the cache, unless the copy was written less than
60 s ago, in which case it answers that copy and says so. Every Neon read logs its time,
events, pages and classes; every class-list answer logs where the list came from and how
old it is; every manual refresh logs the caller's `sub` and its outcome.

The cache sits behind a small interface (README "Design"): the handler and the service
depend on `ClassListCache`, the DynamoDB implementation is the only code that knows boto3
or the item's shape, and the freshness rules are a pure class tested without AWS.

`POST /class-photo-upload/submit` is not changed in this phase (it keeps reading Neon live
through the same function; phase 2 moves it to the service).

## Files to create

All under `functions/classes/class_photo_upload_api/`:

- `class_list_cache.py`: the interface. `ListSource`, `ClassListRecord`, the
  `ClassListCache` protocol, `CacheUnavailable`. No boto3, no AWS.
- `dynamodb_class_list_cache.py`: `DynamoDBClassListCache`, the one implementation. The
  only module that imports boto3 or knows the item's attribute names.
- `class_list_freshness.py`: `FreshnessPolicy` and `Action`. Pure: no I/O, no clock, no
  logging.
- `class_list_service.py`: `ClassListService`, `ClassListResult`, `ServedFrom`,
  `RefreshOutcome`. Depends on the interface and the policy only.
- `tests/fake_class_list_cache.py`: `InMemoryClassListCache`, the in-memory fake
  implementing `ClassListCache` (records calls; can be told to raise `CacheUnavailable`).
- `tests/test_class_list_freshness.py`, `tests/test_class_list_service.py` (the fake, no
  AWS), `tests/test_dynamodb_class_list_cache.py` (moto).
- `tests/fixtures/scheduled_event.json`: an EventBridge scheduled event.

**Why a module beside the function and not `layers/common/`:** only this function reads or
writes the class list (phase 2's submit is the same function). CLAUDE.md asks for a
common helper before a *second* function calls the same endpoint; there is none, and the
record (class names) is specific to this page. If another function ever needs the list,
move `class_list_cache.py` and `dynamodb_class_list_cache.py` to the layer unchanged.

## Files to modify

- `functions/classes/class_photo_upload_api/lambda_function.py`: `CLASS_CACHE_TABLE_NAME`
  in `REQUIRED_ENV`; `class_list_cache()` and `class_list_service()`;
  `read_classes_from_neon()` (the old `load_classes` body plus timing); `handle_classes()`
  through the service, with the manual refresh; the scheduled-refresh branch in
  `lambda_handler()`.
- `functions/classes/class_photo_upload_api/class_names.py`: `import math`, `import time`;
  `NEON_PAGE_SIZE`; `fetch_classes()`'s log line gains milliseconds and pages.
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`: the fake cache
  in the fixtures; new route, refresh and wiring tests.
- `functions/classes/class_photo_upload_api/tests/test_class_names.py`: the page-size
  constant matches the helper's default; the log-line test.
- `templates/classes.yaml`: table, rule and invoke permission (prod only), environment
  variable, IAM statement.
- `template-cicd.yaml`: the table in both deploy policies; the rule in the prod policy only.
- `functions/classes/class_photo_upload_api/README.md`: "How It Works" (the cache, the
  design, the refresh), "Responses" (`refreshed_at`, `stale`, `refresh`), "AWS
  Infrastructure", "Configuration", "Limits", "Testing".
- `docs/README.md`: the Class Photo Upload entry (what it does, how it's triggered, config
  location).

## Implementation details

### lambda

**`class_names.py`**

- Add `import math` and `import time`.
- Add `NEON_PAGE_SIZE = 200  # NeonCRM.search_events's default page_size; not passed, so
  the call's arguments don't change`.
- `fetch_classes()` measures its own time (`time.monotonic()`) and logs, replacing today's
  line:
  `logger.info("Neon read %d events (%d pages) in %d ms: %d classes", len(events), pages, elapsed_ms, len(classes))`
  with `pages = max(1, math.ceil(len(events) / NEON_PAGE_SIZE))`. The call to
  `neon.search_events` keeps exactly its current arguments (the existing tests assert
  `timeout=4.0, max_pages=8`). Return type unchanged (`list[str]`).

**`class_list_cache.py`** (the interface; type hints on everything)

```python
class ListSource(enum.StrEnum):
    """What read this copy from Neon."""
    SCHEDULE = "schedule"              # the prod EventBridge rule
    LIVE_READ = "live_read"            # a request found no usable copy
    MANUAL_REFRESH = "manual_refresh"  # staff asked for a refresh

@dataclass(frozen=True)
class ClassListRecord:
    names: tuple[str, ...]
    refreshed_at: datetime.datetime    # aware, UTC, whole seconds
    source: ListSource

class CacheUnavailable(Exception):
    """The cache's backend failed. str() is a fixed reason (an error type or code), never a value."""

class ClassListCache(Protocol):
    def get(self) -> ClassListRecord | None: ...
        # None: nothing stored, or an item this code can't read (the implementation logs which).
        # Raises CacheUnavailable when the backend fails.
    def put(self, record: ClassListRecord) -> None: ...
        # Replaces the stored copy. Raises CacheUnavailable when the backend fails.
```

**`dynamodb_class_list_cache.py`** (the only module importing boto3 / botocore)

```python
CACHE_KEY = "class-list"
SCHEMA_VERSION = 1
TABLE_NAME_ENV = "CLASS_CACHE_TABLE_NAME"

def default_client() -> Any:
    # boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION"),
    #   config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1, "mode": "standard"}))

class DynamoDBClassListCache:
    def __init__(self, table_name: str, client_factory: Callable[[], Any] = default_client) -> None
    @classmethod
    def from_environment(cls) -> "DynamoDBClassListCache"   # os.environ[TABLE_NAME_ENV]
    def get(self) -> ClassListRecord | None
    def put(self, record: ClassListRecord) -> None
```

- The client is created on the first `get`/`put` (not at import, not in `__init__`) and
  kept on the instance. Creating it can fail (`NoRegionError`): that is a
  `CacheUnavailable` like any other backend failure (README Decision 7: the request still
  gets a live read).
- **Item** (low-level attribute values, names exact): `cache_key` (S, `"class-list"`),
  `version` (N, `"1"`), `classes` (S, `json.dumps(list(names))`), `class_count` (N),
  `refreshed_at` (S, ISO 8601 UTC with `Z`, seconds), `source` (S, a `ListSource` value).
  Nothing else: no event IDs, no instructor names (the names are already cut at " w/ "),
  no `sub`.
- **`get`**: `get_item(TableName=..., Key={"cache_key": {"S": CACHE_KEY}},
  ConsistentRead=True)`. No item → `None`, `logger.info("Class list cache: empty")`. An item
  whose `version` isn't 1, whose `classes` isn't a JSON list of non-empty strings, whose
  `refreshed_at` doesn't parse, or whose `source` isn't a `ListSource` → `None`,
  `logger.warning("Class list cache: unreadable item (%s)", reason)` with a fixed reason
  name (`version`, `classes`, `refreshed_at`, `source`), never the value.
  `BotoCoreError` / `ClientError` → `raise CacheUnavailable(reason) from None`, where the
  reason is the error code for `ClientError` and `type(e).__name__` otherwise.
- **`put`**: `put_item(TableName=..., Item=...)`, unconditional (two writers both write a
  fresh list; the last wins). Same error translation.
- `format_time(moment) -> str` and `parse_time(text) -> datetime | None` live here (the
  item's format). The API answer's `refreshed_at` uses the same `format_time` (imported by
  `lambda_function`, so the two can't drift).

**`class_list_freshness.py`** (pure)

```python
MAX_AGE = datetime.timedelta(hours=26)                 # README Decision 20
MIN_REFRESH_INTERVAL = datetime.timedelta(seconds=60)  # README Decision 21

class Action(enum.StrEnum):
    USE_CACHE = "use_cache"
    READ_NEON = "read_neon"
    TOO_SOON = "too_soon"

@dataclass(frozen=True)
class FreshnessPolicy:
    max_age: datetime.timedelta = MAX_AGE
    min_refresh_interval: datetime.timedelta = MIN_REFRESH_INTERVAL

    def age(self, record: ClassListRecord, now: datetime.datetime) -> datetime.timedelta
        # max(0, now - refreshed_at): a copy dated in the future counts as just written
    def for_request(self, record: ClassListRecord | None, now: datetime.datetime) -> Action
        # None → READ_NEON; age <= max_age → USE_CACHE; else READ_NEON
    def for_manual_refresh(self, record: ClassListRecord | None, now: datetime.datetime) -> Action
        # a record with age < min_refresh_interval → TOO_SOON; else READ_NEON
    def fallback(self, record: ClassListRecord | None) -> ClassListRecord | None
        # the copy to serve, marked stale, when a Neon read fails: any copy, whatever its age
```

The schedule always reads Neon (no policy call). The policy has no I/O, no clock, no
logging; `now` is always passed in.

**`class_list_service.py`**

```python
class ServedFrom(enum.StrEnum):
    CACHE = "cache"              # a copy the policy accepted
    NEON = "neon"                # read live just now
    STALE_CACHE = "stale_cache"  # Neon failed; the policy's fallback copy

class RefreshOutcome(enum.StrEnum):
    REFRESHED = "refreshed"
    TOO_SOON = "too_soon"
    FAILED = "failed"

@dataclass(frozen=True)
class ClassListResult:
    record: ClassListRecord
    served_from: ServedFrom
    refresh: RefreshOutcome | None = None    # set only for a manual refresh
    @property
    def names(self) -> list[str]: ...
    @property
    def stale(self) -> bool: ...             # served_from is STALE_CACHE

class ClassListService:
    def __init__(
        self,
        cache: ClassListCache,
        read_neon: Callable[[], list[str]],
        *,
        policy: FreshnessPolicy = FreshnessPolicy(),
        clock: Callable[[], datetime.datetime] = utc_now,   # aware UTC, microseconds dropped
    ) -> None
    def for_request(self) -> ClassListResult         # GET /classes, and phase 2's submit
    def refresh_on_request(self) -> ClassListResult  # GET /classes?refresh=1
    def refresh_on_schedule(self) -> bool            # the prod EventBridge rule
    def age_seconds(self, result: ClassListResult) -> int   # through the policy and the clock
```

- **Reading the cache**: `cache.get()`; `CacheUnavailable` → treated as `None` with
  `logger.warning("Class list cache: read failed: %s", e)`.
- **Writing the cache**: `cache.put(record)`; `CacheUnavailable` →
  `logger.warning("Class list cache: write failed: %s", e)` and the live list is still
  answered.
- **A Neon read** is `read_neon()`. It "fails" when it raises **or returns an empty list**
  (audit finding: an empty answer must not replace a good copy;
  `logger.warning("Neon returned no classes; not caching them")`).
- **`for_request`**: `record = get`; `policy.for_request(record, now)`:
  - `USE_CACHE` → `ClassListResult(record, CACHE)`; Neon not called.
  - `READ_NEON` → read Neon. Success: `put(ClassListRecord(names, now, LIVE_READ))`,
    `ClassListResult(new, NEON)`. Failure: `policy.fallback(record)`; a copy →
    `logger.warning("Neon failed (%s); serving the cached class list, %d minutes old", ...)`
    and `ClassListResult(copy, STALE_CACHE)`; no copy → an empty read answers the empty
    list (`NEON`, not written, as today); an exception is re-raised unchanged (the handler
    turns its `Refusal` into the 502).
- **`refresh_on_request`**: `record = get`; `policy.for_manual_refresh(record, now)`:
  - `TOO_SOON` → `ClassListResult(record, CACHE, TOO_SOON)`; Neon not called.
  - `READ_NEON` → read Neon. Success: `put(ClassListRecord(names, now, MANUAL_REFRESH))`,
    `ClassListResult(new, NEON, REFRESHED)`. Failure with a fallback copy →
    `ClassListResult(copy, STALE_CACHE, FAILED)`; with no copy, as `for_request`.
- **`refresh_on_schedule`**: read Neon; success → `put(..., SCHEDULE)` and `True`. Any
  failure (exception or empty) → `logger.warning("Scheduled class list refresh failed (%s);
  kept the cached list, %d minutes old", ...)` or `"...; no cached list"`, and `False`.
  Never raises (README Decision 6).
- Every log line carries type names, counts and ages only.

**`lambda_function.py`** (the composition root: the only place that picks the
implementation)

- Relative-import fallback gains `class_list_cache`, `class_list_service` and
  `dynamodb_class_list_cache` (both branches).
- `REQUIRED_ENV` gains `"CLASS_CACHE_TABLE_NAME"` (set by the template).
- The cache for the container, created on first use, never at import:

  ```python
  _class_list_cache: ClassListCache | None = None

  def class_list_cache() -> ClassListCache:
      global _class_list_cache
      if _class_list_cache is None:
          _class_list_cache = DynamoDBClassListCache.from_environment()
      return _class_list_cache

  def class_list_service() -> ClassListService:
      return ClassListService(class_list_cache(), read_classes_from_neon)
  ```

  Tests replace `_class_list_cache` with the fake through `monkeypatch.setattr` (an
  injected value, not a patched boto3).
- `read_classes_from_neon() -> list[str]`: today's `load_classes()` body (secret, then
  `class_names.fetch_classes`), unchanged in what it raises (`Refusal(502, NEON_ERROR,
  "neon_secret")` / `"neon"`); on the Neon failure it logs the elapsed time:
  `"Couldn't read the class list from Neon after %d ms: %s"`.
- Keep `load_classes()` as a thin alias of `read_classes_from_neon()` for `handle_submit`
  in this phase (phase 2 replaces that call). Its docstring says so.
- `wants_refresh(event) -> bool`: `queryStringParameters` is a dict and its `refresh` is
  exactly `"1"`. Anything else is a normal load.
- `handle_classes(event: dict[str, Any], sub: str, dry_run: bool, service: ClassListService) -> dict[str, Any]`:

  ```python
  if wants_refresh(event):
      result = service.refresh_on_request()
      logger.info("Class list refresh by sub %s: %s", sub, result.refresh)
  else:
      result = service.for_request()
  logger.info("Class list from %s (age %d s): %d classes", result.served_from, service.age_seconds(result), len(result.names))
  return _response(200, {
      "dry_run": dry_run,
      "classes": class_list_entries(result.names),
      "refreshed_at": format_time(result.record.refreshed_at),
      "stale": result.stale,
      "refresh": result.refresh,          # null, "refreshed", "too_soon" or "failed"
  })
  ```

  A `Refusal` from `read_classes_from_neon` (no copy, Neon or the secret failed) passes
  through to the existing `except Refusal` (502, `NEON_ERROR`).
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

  def handle_scheduled_refresh(service: ClassListService) -> dict[str, Any]:
      try:
          refreshed = service.refresh_on_schedule()
      except Exception as e:  # a bug in the refresh path must not make Lambda retry
          logger.error("Scheduled class list refresh failed: %s", type(e).__name__)
          refreshed = False
      logger.info("Scheduled class list refresh: %s", "done" if refreshed else "kept the cached list")
      return {"refreshed": refreshed}
  ```

  The HTTP route and the schedule call the same `ClassListService`. The refresh never
  reads `GITHUB_APP_SECRET_NAME` or the SSM config and never calls GitHub. Its return
  value is ignored by EventBridge. Its log lines have no `sub`.
- Everything else (claims check, routes, `handle_submit`) is unchanged.

**Responses** (`GET /class-photo-upload/classes`, 200), new fields after the existing ones:

```json
{"dry_run": true, "classes": [...], "refreshed_at": "2026-10-17T14:05:00Z", "stale": false, "refresh": null}
```

`refresh` is `null` on a normal load; on `?refresh=1` it is `"refreshed"` (read from Neon
just now), `"too_soon"` (the copy was written under 60 s ago; that copy is answered) or
`"failed"` (Neon failed; the old copy is answered with `stale: true`). 502 `NEON_ERROR`
only when there is no copy and Neon (or the Neon secret) fails.

**Logs** (new or changed lines, no names of people, no tokens, no bodies):
`Neon read %d events (%d pages) in %d ms: %d classes`;
`Couldn't read the class list from Neon after %d ms: %s`;
`Class list from %s (age %d s): %d classes`; `Class list refresh by sub %s: %s`;
`Class list cache: empty` / `unreadable item (%s)` / `read failed: %s` / `write failed: %s`;
`Neon returned no classes; not caching them`;
`Neon failed (%s); serving the cached class list, %d minutes old`;
`Scheduled class list refresh: done` / `kept the cached list`;
`Scheduled class list refresh failed (%s); kept the cached list, %d minutes old` /
`...; no cached list`; `Scheduled class list refresh failed: %s`. Together with
`submit`'s live read (still `Neon read …` in this phase) every route logs Neon's time
(#116 criterion 6).

### infra

**`templates/classes.yaml`**: add after `ClassPhotoUploadConfigParameter`:

```yaml
  # One item: the class names read from Neon and when. Refreshed daily on prod by
  # ClassPhotoClassListRefreshRule, on a miss or an expired copy, and by the page's
  # Refresh button; no TTL, so a copy outlives a Neon outage.
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

Update its `Description` to mention the cache ("Lists classes from Neon (cached per stage)
and turns …").

After the function, **prod only** (README Decision 19):

```yaml
  # Prod only: refreshes the cached class list once a day, before Austin's day starts.
  # Other stages fill the cache on a visit or from the page's Refresh button.
  ClassPhotoClassListRefreshRule:
    Type: AWS::Events::Rule
    Condition: IsProd
    Properties:
      Name: !Sub "class-photo-class-list-refresh-${Stage}"
      Description: "Refreshes the class photo upload page's cached class list from Neon once a day."
      ScheduleExpression: "cron(0 10 * * ? *)"
      State: "ENABLED"
      Targets:
        - Arn: !GetAtt ClassPhotoUploadApiFunction.Arn
          Id: "ClassPhotoClassListRefreshTarget"
      Tags:
        - Key: Project
          Value: classes:class-photo-upload

  ClassPhotoClassListRefreshPermission:
    Type: AWS::Lambda::Permission
    Condition: IsProd
    Properties:
      FunctionName: !GetAtt ClassPhotoUploadApiFunction.Arn
      Action: "lambda:InvokeFunction"
      Principal: "events.amazonaws.com"
      SourceArn: !GetAtt ClassPhotoClassListRefreshRule.Arn
```

No new template parameter (so nothing new to pass from `template.yaml`); no new output.
`template.yaml` is not changed (`?refresh=1` is a query string on the existing route;
the proxy integration passes it through).

**`template-cicd.yaml`**

In **both** `GitHubDeployPolicystage` and `GitHubDeployPolicyprod` (with that policy's
stage name):

- `AllowDynamoDBTableManagement`: `Resource` becomes a list with
  `table/SlackReorderStateTable-<stage>` and `table/ClassPhotoClassListCache-<stage>`.
- A new statement right after it, on the new table's ARN only. CloudTrail of a real
  CloudFormation table create in this account (2026-10-02) shows the handler calling
  these after `CreateTable`; the existing statement has none of them, and
  `SlackReorderStateTable` was created before the role was scoped (prep finding):

  ```yaml
          - Sid: AllowClassListCacheTableReads
            Effect: Allow
            Action:
              - dynamodb:DescribeContinuousBackups
              - dynamodb:DescribeContributorInsights
              - dynamodb:DescribeKinesisStreamingDestination
              - dynamodb:GetResourcePolicy
              - dynamodb:ListTagsOfResource
            Resource: !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/ClassPhotoClassListCache-stage"
  ```

In **`GitHubDeployPolicyprod` only** (the rule exists only on prod):

- `AllowEventBridgeRuleManagement`: `Resource` becomes a list with
  `rule/pm-reminder-bot-schedule-prod` and `rule/class-photo-class-list-refresh-prod`.
- A new statement right after it, on that rule's ARN only (the rule has `Tags`;
  CloudFormation's `AWS::Events::Rule` handler tags on create and lists targets on
  delete, which a rollback of the first deploy needs):

  ```yaml
          - Sid: AllowClassListRefreshRuleTagging
            Effect: Allow
            Action:
              - events:TagResource
              - events:UntagResource
              - events:ListTagsForResource
              - events:ListTargetsByRule
            Resource: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:rule/class-photo-class-list-refresh-prod"
  ```

`GitHubDeployPolicystage` gets no EventBridge change: CloudFormation makes no call for a
resource whose condition is false. No other deploy-role change:
`lambda:AddPermission`/`RemovePermission` on `ClassPhotoUploadApiFunction-{stage,prod}`
(the only action `AWS::Lambda::Permission`'s create handler needs) and the
role-management statements already cover the permission and the function's policy. No
wildcard is added.

### docs

- API `README.md`: a new section **The Class List Cache**: what is stored (the item's six
  attributes), the design (interface, DynamoDB implementation, freshness policy, service;
  why it is beside the function and not in the layer), the refresh (daily at 10:00 UTC on
  prod; none on other stages), the 26-hour maximum age, the outcomes (hit, miss, expired,
  Neon down with a copy, manual refresh, too soon), how to empty it by hand (delete the
  item `cache_key = class-list`; the next request reads Neon). "Responses"
  (`refreshed_at`, `stale`, `refresh`, `?refresh=1`, when 502 happens now). "AWS
  Infrastructure" (table, prod rule and permission, IAM statement). "Configuration"
  (`CLASS_CACHE_TABLE_NAME`, now five required variables). "Limits": Neon is off the
  request path when the cache is warm; a refresh takes one of the 3 concurrent slots for a
  few seconds; `stale` means "Neon failed and an older copy was served", not "over a day
  old"; a live read that runs past the function's 25 s timeout (a very slow Neon) ends in
  API Gateway's 502 without the stale copy, as today (audit finding, accepted); a
  scheduled refresh cut off by the timeout logs only Lambda's "Task timed out", and Lambda
  retries it twice. "Testing" (the fake, the policy and service tests, moto for the
  DynamoDB implementation). Note that submit still reads Neon live until phase 2.
- `docs/README.md`, Class Photo Upload entry: **What it does** gains one sentence (the class
  list is cached per stage, refreshed from Neon once a day on prod, on a miss or a copy
  over 26 hours old, and when staff press **Refresh class list**); **How it's triggered**
  adds the prod-only EventBridge rule `class-photo-class-list-refresh-prod` (daily, 10:00
  UTC) invoking `ClassPhotoUploadApiFunction`, and `GET /class-photo-upload/classes?refresh=1`;
  **Config Location** adds the table `ClassPhotoClassListCache-${Stage}` (created by
  `templates/classes.yaml`).

## Tests

**`tests/test_class_list_freshness.py`** (pure; `now` fixed):

- `test_no_record_reads_neon` (request and manual refresh).
- `test_fresh_record_is_used`, `test_record_at_max_age_is_used`,
  `test_record_past_max_age_reads_neon` (26 h exactly → use; one second more → read).
- `test_future_record_counts_as_age_zero`.
- `test_manual_refresh_too_soon_under_a_minute` (59 s → `TOO_SOON`; 60 s → `READ_NEON`).
- `test_fallback_serves_any_copy` (a week-old copy is still the fallback; `None` → `None`).
- `test_defaults_are_26_hours_and_60_seconds`.

**`tests/test_class_list_service.py`** (`InMemoryClassListCache`, a fixed clock, a scripted
`read_neon`; no AWS):

- `test_hit_serves_cache_without_neon` (#114 "a hit").
- `test_miss_reads_neon_and_writes_cache` (#114 "a miss"): `LIVE_READ`, written once.
- `test_expired_copy_reads_neon_and_replaces_it` (#114 "a stale entry").
- `test_neon_failure_with_copy_serves_it_stale` (#114 "Neon failing while a cached copy
  exists"): `STALE_CACHE`, `stale` true, copy unchanged, warning with minutes.
- `test_neon_failure_without_copy_reraises`: the same exception object; nothing written.
- `test_empty_neon_answer_keeps_the_copy` and `test_empty_neon_answer_without_copy_is_not_cached`.
- `test_cache_read_failure_is_a_miss` and `test_cache_write_failure_still_returns_live_list`
  (the fake raises `CacheUnavailable`).
- `test_manual_refresh_reads_neon_and_rewrites` (`REFRESHED`, `MANUAL_REFRESH`, even when
  the copy is fresh).
- `test_manual_refresh_too_soon_returns_copy_without_neon` (`TOO_SOON`, Neon not called).
- `test_manual_refresh_neon_failure_serves_copy_stale` (`FAILED`, `stale` true).
- `test_manual_refresh_without_copy_and_neon_failure_reraises`.
- `test_scheduled_refresh_writes_fresh_list` (`SCHEDULE`), even within 60 s of a write.
- `test_scheduled_refresh_failure_keeps_copy_and_returns_false` (logs the age),
  `test_scheduled_refresh_failure_with_empty_cache_logs_no_cached_list`,
  `test_scheduled_refresh_empty_answer_keeps_copy`.
- `test_logs_carry_no_class_names`.

**`tests/test_dynamodb_class_list_cache.py`** (moto `mock_aws`; a fixture creating
`ClassPhotoClassListCache-test`; fake credentials and `AWS_REGION` set with `monkeypatch`,
never at module level):

- `test_get_empty_table_is_none` (logs "empty").
- `test_put_then_get_round_trips` (names, time and source come back equal) and
  `test_item_has_exactly_six_attributes`.
- `test_unreadable_items_are_none` (parametrized: wrong `version`, `classes` not JSON,
  `classes` not a list of strings, an empty string in `classes`, bad `refreshed_at`,
  unknown `source`): `None`, logs the reason name, not the value.
- `test_client_error_raises_cache_unavailable` (a missing table → `ResourceNotFoundException`
  as the reason) for `get` and `put`.
- `test_client_created_lazily`: constructing the cache calls no factory; the first `get`
  calls it once; a second `get` reuses it.
- `test_client_creation_failure_is_cache_unavailable` (a factory raising `NoRegionError`).
- `test_from_environment_reads_the_table_name`.

**`tests/test_lambda_function.py`**:

- Fixtures: a `fake_cache` fixture puts an `InMemoryClassListCache` into
  `lambda_function._class_list_cache` with `monkeypatch.setattr`; `mocks` uses it and
  exposes it as `mocks.cache`, so every existing test runs against an empty cache (a live
  read, as today). `ENV` gains `CLASS_CACHE_TABLE_NAME`, so
  `test_missing_env_returns_500` covers it.
- The existing `test_classes_*` tests keep passing unchanged.
  `test_classes_returns_names_problems_and_warnings` also asserts `stale is False`,
  `refresh is None` and a `refreshed_at` matching `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$`.
- `test_classes_second_call_is_served_from_cache`: two calls; Neon's `search_events`
  called once; the log says `Class list from cache`.
- `test_classes_cached_list_survives_neon_failure`: a copy older than 26 hours, Neon
  raises `NeonCRMError` → 200, the copy's names, `stale` true.
- `test_classes_neon_failure_without_cache_returns_502` (the existing 502 test, now
  explicit about the empty cache).
- `test_classes_logs_neon_time`: after a live read the log has
  `Neon read 5 events (1 pages) in` and `ms: 4 classes`.
- `test_classes_refresh_reads_neon_and_logs_sub`: a fresh copy, `?refresh=1` → Neon called,
  `refresh` `"refreshed"`, the log has `Class list refresh by sub <SUB>: refreshed` and no
  `USERMARKER`.
- `test_classes_refresh_twice_in_a_minute_is_too_soon`: the second answer has `refresh`
  `"too_soon"` and Neon was called once.
- `test_classes_refresh_neon_failure_serves_copy_stale`: `refresh` `"failed"`, `stale` true.
- `test_classes_refresh_param_other_values_are_a_normal_load` (parametrized: `"0"`,
  `"true"`, `""`, missing, `queryStringParameters` `null`).
- `test_classes_refresh_needs_claims`: `?refresh=1` with the claims removed → 403, Neon and
  the cache not touched.
- `test_scheduled_event_refreshes_cache_without_github`: the fixture event → `{"refreshed":
  True}`; the cache holds the names with source `schedule`; `github_app` and
  `aws.get_secret_json` / `aws.get_json_parameter` not called.
- `test_scheduled_refresh_neon_failure_keeps_cache`: Neon raises → `{"refreshed": False}`,
  the copy unchanged, warning logged, no exception.
- `test_scheduled_refresh_unexpected_error_returns_normally`: the service raising a
  `RuntimeError` → `{"refreshed": False}` and an error log with the type name.
- `test_http_event_with_scheduled_keys_still_needs_claims`: the classes fixture event with
  `source` and `detail-type` added and the claims removed → 403, Neon and the cache not
  touched.
- `test_scheduled_refresh_logs_no_names`: no class name, `USERMARKER` or token in the log.
- `test_default_cache_is_the_dynamodb_table_from_env` (moto): with
  `lambda_function._class_list_cache` reset to `None` and a moto table named by
  `CLASS_CACHE_TABLE_NAME`, two `/classes` calls → Neon once, the item exists in the
  table; `class_list_cache()` returns the same instance both times.

**`tests/test_class_names.py`**:

- `test_page_size_matches_the_helper_default`: `NEON_PAGE_SIZE ==
  inspect.signature(NeonCRM.search_events).parameters["page_size"].default`.
- `test_fetch_classes_logs_counts_not_names` (line 153) asserts today's
  `"Read 1 events, 1 classes"`; update it to the new line (`"Neon read 1 events (1 pages)
  in "` and `" ms: 1 classes"`), keeping its `"Pat" not in caplog.text` check. This is a
  log line, not a message anyone sees. `test_module_logs_nothing_but_fetch_classes` keeps
  passing.

**Design checks** (reviewers verify by reading; README "Design"): `class_list_service.py`,
`class_list_freshness.py` and `class_list_cache.py` import no boto3/botocore and no
attribute name of the item; `lambda_function.py` is the only other module that names
`DynamoDBClassListCache` (the composition root, in `class_list_cache()`); no boto3 client
is created at import.
`test_service_modules_do_not_import_boto3` asserts the first part by reading the three
files' imports.

## Acceptance criteria

1. With a copy under 26 hours old, `GET /class-photo-upload/classes` doesn't call Neon or
   read the Neon secret, and answers the cached names with `refreshed_at`, `stale: false`
   and `refresh: null` (#116 AC1). Tests: `test_hit_serves_cache_without_neon`,
   `test_classes_second_call_is_served_from_cache`.
2. With an empty cache, the first request reads Neon live, answers the list and writes it
   (#116 AC3). Test: `test_miss_reads_neon_and_writes_cache`.
3. With a copy over 26 hours old and Neon failing, the answer is 200 with the copy and
   `stale: true`; with no copy and Neon failing, 502 "Couldn't load the class list. Try
   again in a minute." (#116 AC4). An empty Neon answer never replaces a copy.
4. `GET /class-photo-upload/classes?refresh=1` (same authorizer and claims check) reads
   Neon live and rewrites the cache (`refresh: "refreshed"`); within 60 s of the last
   write it answers that copy with `refresh: "too_soon"` without calling Neon; with Neon
   failing it answers the copy with `stale: true`, `refresh: "failed"`. The log names the
   caller's `sub`, never the username (#116 AC2, AC5).
5. On prod an EventBridge scheduled event refreshes the item without reading the GitHub
   secret or the SSM config; a failed refresh keeps the item and returns normally; an HTTP
   event with the scheduled keys still needs valid claims (#116 AC5).
6. Every live Neon read logs its milliseconds, events, pages and classes; every class-list
   answer logs its source and age (#116 AC6).
7. `templates/classes.yaml` has `ClassPhotoClassListCache-${Stage}` (on-demand, `Project`
   tag, no TTL) on every stage, and on prod only `class-photo-class-list-refresh-prod`
   (`cron(0 10 * * ? *)`, `Project` tag) and the permission for `events.amazonaws.com`
   from that rule only; the function can only `GetItem` and `PutItem` on its table (#116
   AC7).
8. Both deploy policies list the table (with the five read actions on its ARN only); only
   the prod policy lists the rule, with its tagging and `ListTargetsByRule` on that
   rule's ARN only.
9. The cached item holds only `cache_key`, `version`, `classes`, `class_count`,
   `refreshed_at` and `source` (#116 AC7).
10. The design holds (README "Design"): the handler and the service use `ClassListCache`;
    only `dynamodb_class_list_cache.py` imports boto3 or knows the item; the freshness
    policy is pure and tested without AWS; the service is tested with the in-memory fake;
    the DynamoDB implementation with moto; no boto3 client at import.
11. The API README and `docs/README.md` describe the cache, how it is refreshed and where it
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
  --region us-east-2` answers `ResourceNotFoundException` (stage has no schedule).
- Open the stage page: the first load may take about 8 s (cache empty); reload: the class
  list arrives in under 2 s, and `/asmbly/lambda/ClassPhotoUploadApiFunction-stage` shows
  `Class list from cache (age … s)`, with a `Neon read … ms` line from the first load.
- After 15 or more idle minutes (a cold container, warm cache), load the page again: still
  under 2 s (audit finding: the cold start plus the DynamoDB client).
- Press **Refresh class list** (phase 3) twice within a minute: the first logs
  `Class list refresh by sub …: refreshed` and a `Neon read` line; the second
  `…: too_soon` and no `Neon read`.

After the prod deploy: `aws events describe-rule --name class-photo-class-list-refresh-prod
--region us-east-2` shows `cron(0 10 * * ? *)`, `ENABLED`; after the next 10:00 UTC the
prod log shows `Scheduled class list refresh: done`.

## Admin actions

Before this reaches `stage`: redeploy `AsmblyFacilitiesMaintTrackingStack-cicd`
(`docs/Deploying.md`, "CI/CD Infrastructure (The Deployer Role)"); the table is new in
both deploy policies and the rule in the prod policy, and the deploy fails without them.
README Admin actions 1 and 2.

## Hand-off

Done. Phase 2 can rely on:
`lambda_function.class_list_service() -> ClassListService` and its `for_request() ->
ClassListResult` (`record`, `names`, `served_from`, `stale`, `refresh`),
`service.age_seconds(result)`, `class_list_freshness.MAX_AGE`,
`lambda_function.read_classes_from_neon()`, the `fake_cache` test fixture
(`InMemoryClassListCache`, filled with `put(ClassListRecord(...))`), and `load_classes()`
still used by `handle_submit` (phase 2 deletes it). In tests, `mocks.cache` is the fake
the handler uses (empty unless a test sets `mocks.cache.record`), and the module-level
`cached_copy(age, source)` helper in `tests/test_lambda_function.py` builds a record of the
two `CACHED_NAMES`. Phase 3 can rely on `/classes` answering `refreshed_at`
(ISO 8601 UTC, `Z`), `stale` (boolean) and `refresh` (`null`, `"refreshed"`,
`"too_soon"`, `"failed"`), and on `GET /classes?refresh=1`. The docs describe the refresh as `?refresh=1` and don't
name the button yet; phase 3's "docs" section names it.

As built, differences from the text above: DynamoDB calls make one attempt, not two
(independent review: a DynamoDB outage cost a live read about 16 s), set as
`retries={"total_max_attempts": 1}` because botocore reads a client config's
`max_attempts` as retries (review #2); a scheduled refresh whose cache write fails returns
`False` (review #2); `refreshed_at` is the time the Neon read finished; `format_time` /
`parse_time` live in `class_list_cache.py` (the interface), so the API answer and the
item can't drift; a few test names differ from the list (for example
`test_missing_table_raises_cache_unavailable`). `pytest.ini` already sets `AWS_REGION`
and fake credentials, but another test module overwrites `AWS_REGION` at import, so the
moto fixtures pin it with `monkeypatch`. The deploy role grants the rule to the prod
policy only; the standards scan's "named resource in both policies" grep reports
`class-photo-class-list-refresh-stage` as missing, which is intended (Decision 19).

**Manual QA notes (for `/offshore`'s QA doc, #116):** the stage checks under
Verification, in order: empty cache then cached reload; the cold-container reload after
15 idle minutes; **Refresh class list** twice within a minute (refreshed, then too soon);
stage has no rule. Prod, after the prod deploy: the rule exists with `cron(0 10 * * ? *)`
and the next day's log shows the scheduled refresh.
