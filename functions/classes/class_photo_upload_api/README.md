# Class Photo Upload API

## Table of Contents

- [Purpose](#purpose)
- [Routes](#routes)
- [How It Works](#how-it-works)
- [The Class List Cache](#the-class-list-cache)
- [Responses](#responses)
- [Dry Run (stage)](#dry-run-stage)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Limits](#limits)
- [Undoing a Pull Request](#undoing-a-pull-request)
- [Testing](#testing)

## Purpose

The server side of the class photo upload page (epic #73). It reads the class list from
NeonCRM (kept in a per-stage cache, epic #114), checks a submitted photo, and turns it
into a pull request on [`asmbly-makerspace/asmbly-classes`](https://github.com/asmbly-makerspace/asmbly-classes)
that adds the photo under the exact file name the class pages look for and removes the
older images the class list would match instead. The photo is never stored: it goes
straight into the pull request. Only the class list (class names and when they were read)
is kept, in the cache described below.

Its caller is the [Class Photo Upload Page](../class_photo_upload_page/README.md), which
signs the person in, removes location data and runs the same photo checks in the browser
before it submits.

## Routes

Both routes are on `FacilitiesApi` (`https://facilities.asmbly.org` in prod, the stage
stack's `FacilitiesApiUrl` on stage), behind the `StaffCognitoAuthorizer` in
`template.yaml`. The caller sends the staff pool's **ID token** in the `Authorization`
header, as it is (no `Bearer ` prefix).

| Method and path | What it does |
| --- | --- |
| `GET /class-photo-upload/classes` | The class list (from the cache, or Neon), with each class's file name, file-name problem and shared-photo warning |
| `GET /class-photo-upload/classes?refresh=1` | The same, read from Neon again now (at most once a minute), for the page's refresh button (epic #114, phase 3) |
| `POST /class-photo-upload/submit` | `{"class_name": "...", "photo_base64": "..."}`: checks, then opens or updates the pull request (prod) or reports what it would do (stage) |

Who can call:

1. API Gateway answers **401** to a missing, expired or foreign-pool token; the function
   never runs.
2. The authorizer accepts an ID token from *any* app client of the staff pool, so the
   function also requires the token's `aud` to be this page's app client
   (`CLASS_PHOTO_APP_CLIENT_ID`, compared with `hmac.compare_digest`), `token_use` to be
   `id`, and non-empty `sub` and `cognito:username`. Otherwise it answers **403** and
   reads nothing.

## How It Works

`lambda_function.py` routes the request; the work is in the modules beside it:

- `class_names.py`: the class list from Neon (events whose end date is today or no more
  than 4 months ago, by name up to ` w/ `), and the site's file-name rules: the exact
  file name, the fuzzy key the class list matches on, the branch name.
- `class_list_cache.py`, `dynamodb_class_list_cache.py`, `class_list_freshness.py` and
  `class_list_service.py`: the class list cache ([below](#the-class-list-cache)).
- `photo_checks.py`: the photo checks, from the JPEG headers only: at most 4 MB, a JPEG,
  3:2 landscape after the orientation flag, and no GPS data (EXIF or XMP, in the main
  image or any embedded one).
- `submission.py`: what the submission does on `asmbly-classes` (`plan_submission`, read
  calls only) and doing it (`apply_submission`): one commit on the class's own branch
  `class-photo/<slug>-<hash8>`, and that branch's pull request opened or updated.

A submission runs in this order, and stops at the first refusal:

1. Parse the body (base64-decoded first when `isBase64Encoded`).
2. Refuse a photo whose base64 is longer than a 4 MB photo can be, without decoding it;
   decode the rest and run the photo checks. A failing photo never reaches Neon or GitHub.
3. Read the class list from Neon (live: submit doesn't use the cache yet; epic #114 moves
   it there); refuse a class that isn't in it, or whose name can't be a file name.
4. Read the repository config (SSM) and the GitHub App's credentials (Secrets Manager).
5. Ask GitHub for an installation token for `asmbly-classes` only: read-only on a dry
   run, `contents: write, pull_requests: write` on prod.
6. Plan the submission; on prod, apply it (only when at least 8 s of the function's time
   are left, so a slow read never leaves a half-made commit).

The imports of the modules work both under pytest (as the package
`functions.classes.class_photo_upload_api`) and under Lambda, where the handler is the
top-level module `lambda_function` (a relative import with a top-level fallback).

## The Class List Cache

Reading the class list from Neon takes about 8 seconds (a 4-month search, two pages of
200 events). So the list is kept per stage in one DynamoDB item and answered from there,
well under 2 seconds.

**What is stored.** One item in `ClassPhotoClassListCache-${Stage}`, key
`cache_key = "class-list"`, with exactly six attributes: `cache_key`, `version` (1),
`classes` (a JSON list of class names, already cut at ` w/ `, so no instructor names),
`class_count`, `refreshed_at` (when they were read from Neon, `2026-10-17T14:05:00Z`) and
`source` (what read them: `schedule`, `live_read` or `manual_refresh`). No event IDs, no
user IDs, no personal data. No TTL: a copy outlives a Neon outage.

**When Neon is read.**

| Situation | What happens | `stale` | `refresh` |
| --- | --- | --- | --- |
| A copy no older than 26 hours | It is answered; Neon isn't called | `false` | `null` |
| No copy, or one over 26 hours old | Neon is read live, the copy replaced, the list answered | `false` | `null` |
| The same, and Neon fails | The old copy is answered (502 if there is none) | `true` | `null` |
| `?refresh=1` | Neon is read live and the copy replaced, however fresh it was | `false` | `"refreshed"` |
| `?refresh=1` within 60 s of the last write | That copy is answered; Neon isn't called | `false` | `"too_soon"` |
| `?refresh=1` and Neon fails | The old copy is answered (502 if there is none) | `true` | `"failed"` |
| Prod, every day at 10:00 UTC | The EventBridge rule reads Neon and replaces the copy | | |

Neon "fails" when it errors, times out, or answers no classes at all: an empty answer
never replaces a good copy (with no copy, the empty list is answered, not stored, and a
refresh reports `"failed"`). A failed scheduled refresh (Neon failed, or the copy couldn't be
written) keeps the copy and logs a warning; it returns normally, so Lambda doesn't retry it. Stage and dev stacks have
no schedule: their copy is read on a visit, when it expires, or on a refresh.

**Design.** The cache is behind a small interface, so the handler doesn't depend on
DynamoDB (plan `.implementation_plans/class-photo-loading/README.md`, "Design"):

- `class_list_cache.py`: the record (`ClassListRecord`: names, `refreshed_at`, `source`)
  and the `ClassListCache` protocol (`get()`, `put(record)`). No AWS.
- `dynamodb_class_list_cache.py`: `DynamoDBClassListCache`, the one implementation and
  the only module that imports boto3 or knows the item's attribute names. Its client is
  created on first use (2 s timeouts, one attempt and no retry, so a DynamoDB outage costs a
  request at most about 8 s); any DynamoDB error becomes
  `CacheUnavailable`, which the service treats as a miss (on read) or a warning (on
  write), so a DynamoDB problem never stops the list from loading.
- `class_list_freshness.py`: `FreshnessPolicy`, the rules above (26 hours, 60 seconds, the
  stale fallback) as a pure class: no I/O, no clock.
- `class_list_service.py`: `ClassListService`, which applies the policy to the cache and
  Neon for a request, a manual refresh and the schedule. The HTTP route and the schedule
  call the same service.
- `lambda_function.py` picks the DynamoDB implementation (`class_list_cache()`, once per
  container) and injects it with the Neon reader (`class_list_service()`).

These modules sit beside the function, not in the common layer, because only this
function uses the class list. If another function needs it, the interface and the
DynamoDB implementation can move to the layer unchanged.

**Emptying it by hand.** Delete the item (`cache_key = class-list`) in
`ClassPhotoClassListCache-<stage>`; the next request reads Neon. Or ask for a refresh
(`?refresh=1`).

## Responses

Every response is JSON with `Content-Type: application/json; charset=utf-8` and
`Cache-Control: no-store`. Errors are `{"error": "<message>"}`; the messages are meant
to be shown to the person as they are, and never carry an exception's text, a status
code from Neon or GitHub, or vendor text.

`GET /class-photo-upload/classes`, 200:

```json
{"dry_run": true,
 "classes": [{"name": "Ceramics: Glazing Workshop", "file_name": "Ceramics__Glazing_Workshop.jpg",
              "problem": null, "warning": null}],
 "refreshed_at": "2026-10-17T14:05:00Z", "stale": false, "refresh": null}
```

`file_name` is `null` when `problem` is set (a name with `/`, `\` or a control character
can't be a file name). `warning` names the other classes whose photo would be the same
on the class list. `refreshed_at` is when the list was read from Neon (UTC). `stale` is
`true` only when Neon failed and an older copy was answered instead. `refresh` is `null`
on a normal load and, on `?refresh=1`, `"refreshed"`, `"too_soon"` or `"failed"` (see
[The Class List Cache](#the-class-list-cache)).

`POST /class-photo-upload/submit`, 200:

```json
{"dry_run": false, "action": "opened",
 "pull_request": {"number": 12, "url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/12"},
 "file_path": "app/src/lib/images/Ceramics__Glazing_Workshop.jpg", "replaces_existing": true,
 "removed_paths": ["app/src/lib/images/Ceramics_Glazing_Workshop.jpg"],
 "title": "...", "body": "...", "warnings": ["..."]}
```

`action` is `opened` or `updated` on prod, `would_open` or `would_update` on a dry run;
`pull_request` is `null` for `would_open`.

| Status | Message | When |
| --- | --- | --- |
| 400 | The photo check's message (size, not a JPEG, unreadable, ratio, not landscape, location) | The photo fails a check |
| 400 | `The photo didn't arrive whole. Choose it again and submit.` | Invalid JSON, a missing or wrong-typed field, bad base64 |
| 400 | `Pick a class from the list.` | The class isn't in the Neon list (or is empty or over 200 characters) |
| 400 | `The class name "..." contains "/", which can't be in a file name. Rename the class in Neon first.` | The class's name can't be a file name |
| 403 | `You're not allowed to use this page.` | Wrong app client, an access token, or missing claims |
| 404 | `Not found.` | Any other method or path |
| 409 | `Someone else just submitted a photo for this class. Try again.` | Another submission moved the class's branch first |
| 500 | `Something went wrong on our side. Try again later.` | A missing environment variable, an unreadable config or App secret, anything unexpected |
| 502 | `Couldn't load the class list. Try again in a minute.` | Neon, or the Neon secret, failed, and no cached copy exists (the class list), or always (submit, which still reads Neon live) |
| 502 | `Couldn't open the pull request. Try again in a minute.` | A GitHub call failed, or too little time was left to write |

Submitting again after a 409 or a 502 finishes the job without opening a second pull
request.

## Dry Run (stage)

`CLASS_PHOTO_DRY_RUN` is `'false'` only when the template's `Stage` is `prod`
(`templates/classes.yaml`); any other value, or none, is a dry run. A dry run runs every
check with the same messages, asks GitHub for a **read-only** installation token, plans
the submission with read calls only, and answers what it would do (`would_open`, or
`would_update` with the open pull request's number), the file it would add or replace,
the files it would remove, and the pull request's title and description. Nothing on
GitHub changes, and the token couldn't change anything if the code tried.

## AWS Infrastructure

Defined in `templates/classes.yaml` (nested stack `ClassesStack`), wired in
`template.yaml`:

| Resource | Name |
| --- | --- |
| Function | `ClassPhotoUploadApiFunction-${Stage}` (Python 3.12, 256 MB, 25 s timeout, at most 3 at once) |
| Log group | `/asmbly/lambda/ClassPhotoUploadApiFunction-${Stage}`, 14 days |
| DynamoDB table | `ClassPhotoClassListCache-${Stage}` (on demand, key `cache_key`, no TTL) |
| EventBridge rule (prod only) | `class-photo-class-list-refresh-prod`, `cron(0 10 * * ? *)` (10:00 UTC daily), invoking this function; its permission `ClassPhotoClassListRefreshPermission` lets only that rule invoke it |
| SSM parameter | `/${Stage}/config/class-photo-upload`, from `configs/class_photo_upload.json` |
| Authorizer | `StaffCognitoAuthorizer` in `FacilitiesApi`, on the pool in `/config/cognito/staff/user-pool-id` |
| Invoke permission | `ClassPhotoUploadApiInvokePermission`, for `FacilitiesApi` paths under `/class-photo-upload/` |
| Throttle | `POST /class-photo-upload/submit`: 1 request a second, bursts of 5 |

Layers: the common layer (`common.aws`, `common.neoncrm`, `common.github_app`) and the
requests layer. `PyJWT[crypto]==2.15.1` (for the GitHub App's RS256 JWT) is in this
function's `requirements.txt`, so `sam build` bundles it with `cryptography`.

The function may read only its SSM parameter, the Neon secret and the GitHub App
secret, each by its exact ARN, and only `GetItem` and `PutItem` on its cache table. Tag: `Project: classes:class-photo-upload`.

## Configuration

Environment variables (all set by `templates/classes.yaml`):

| Variable | Value |
| --- | --- |
| `NEON_SECRET_NAME` | The Neon secret (`prod/neon_token` by default), with `NEON_ORG_ID` and `NEON_API_KEY` |
| `GITHUB_APP_SECRET_NAME` | `github/class-photo-upload-app` |
| `CLASS_PHOTO_CONFIG_PARAM_NAME` | `/${Stage}/config/class-photo-upload` |
| `CLASS_PHOTO_APP_CLIENT_ID` | The page's app client ID, from `/config/cognito/staff/class-photo-app-client-id` |
| `CLASS_PHOTO_DRY_RUN` | `false` on prod, `true` elsewhere |
| `CLASS_CACHE_TABLE_NAME` | `ClassPhotoClassListCache-${Stage}` |

All but `CLASS_PHOTO_DRY_RUN` (five) are required; without one the function logs its name
and answers 500.

The GitHub App secret, `github/class-photo-upload-app` (us-east-2), is a JSON object with
three string keys: `app_id`, `installation_id` and `private_key` (the whole `.pem`, line
breaks as `\n`). A missing key makes a submission answer 500 and log the key's name. How
to create the App and the secret, step by step:
[docs/Deploying.md, "One-Time Admin Setup: Class Photo Upload"](../../../docs/Deploying.md#one-time-admin-setup-class-photo-upload)
(also the plan's README, admin actions 4 and 5,
`.implementation_plans/class-photo-upload/README.md`).

`configs/class_photo_upload.json` holds the repository's coordinates: `repo_owner`,
`repo_name`, `base_branch`, `images_dir`, `branch_prefix` (must end with `/`; the client
can only create or move branches under it) and `image_extensions` (every extension the
site loads, lowercase).

Logs carry the route, the caller's Cognito `sub`, the class name, which check failed,
the action, the pull request number and the branch. For the class list they also carry
Neon's time (`Neon read 180 events (1 pages) in 3750 ms: 84 classes`), where the answer
came from and how old it was (`Class list from cache (age 120 s): 84 classes`), and who
asked for a refresh (`Class list refresh by sub <sub>: refreshed`). They never carry the username (it
appears only in the pull request, as "Requested by"), the `Authorization` header, the
request body, the photo, a token or the App's key.

## Limits

- **Request size.** Lambda takes at most 6 MB in a synchronous request. A 4 MB photo is
  about 5.6 MB of base64, which with the headers and request context still fits. A
  larger request never reaches the function: API Gateway answers it with an error and no
  details. The page checks the size before it sends.
- **Time.** API Gateway gives up after 29 s; the function's timeout is 25 s. The Neon
  search reads at most 8 pages of 200 events and gives up on a request that doesn't
  connect or answer for 4 s; a GitHub call gives up after 5 s. These bound the usual
  slow cases; a response that trickles in can still run longer, and then the function's
  own 25 s timeout ends the request (API Gateway answers 502, with no details).
- **Concurrency.** At most 3 requests run at once (`ReservedConcurrentExecutions`). The
  daily refresh on prod takes one of them for a few seconds. The refresh guard is
  checked before Neon is read, so two refreshes pressed in the same second can both read
  Neon; the concurrency limit bounds that.
- **Cache.** With a warm cache the class list spends no time in Neon. A live read that
  runs past the 25 s timeout (a very slow Neon) ends in API Gateway's 502 without the
  stale copy, as before the cache. A scheduled refresh cut off by the timeout logs only
  Lambda's "Task timed out", and Lambda retries it twice. `stale` means "Neon failed and
  an older copy was answered", not "over a day old".

## Undoing a Pull Request

The App never merges and never touches `main`. To undo a submission, close its pull
request on `asmbly-classes` (and delete its `class-photo/...` branch if you like). The
photo stays visible in the closed pull request's history; to remove it from GitHub
entirely, ask GitHub support to purge the branch's commits. The next submission for that
class starts a fresh pull request from the current `main`.

## Testing

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_api
```

- `tests/test_class_list_freshness.py`: the freshness policy alone.
- `tests/test_class_list_service.py`: the service with an in-memory cache
  (`tests/fake_class_list_cache.py`) and a fixed clock; no AWS. It also checks that the
  interface, policy and service modules import no boto3.
- `tests/test_dynamodb_class_list_cache.py`: the DynamoDB implementation against `moto`.

`tests/test_lambda_function.py` puts the in-memory cache into the handler (an empty cache
unless a test fills it), patches `aws`, `NeonCRM` and `github_app` where the
handler uses them and the two `submission` calls, uses the real photo checks and class
rules with JPEGs from `tests/jpeg_builder.py`, and reads the API Gateway events in
`tests/fixtures/api_event_*.json` (fake claims, no real token) and
`tests/fixtures/scheduled_event.json`. One test runs the default DynamoDB wiring against
`moto`.
