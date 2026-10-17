# Class Photo Upload API

## Table of Contents

- [Purpose](#purpose)
- [Routes](#routes)
- [How It Works](#how-it-works)
- [Responses](#responses)
- [Dry Run (stage)](#dry-run-stage)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Limits](#limits)
- [Undoing a Pull Request](#undoing-a-pull-request)
- [Testing](#testing)

## Purpose

The server side of the class photo upload page (epic #73). It reads the class list from
NeonCRM, checks a submitted photo, and turns it into a pull request on
[`asmbly-makerspace/asmbly-classes`](https://github.com/asmbly-makerspace/asmbly-classes)
that adds the photo under the exact file name the class pages look for and removes the
older images the class list would match instead. Nothing is stored: the photo goes
straight into the pull request.

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
| `GET /class-photo-upload/classes` | The class list, with each class's file name, file-name problem and shared-photo warning |
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

`lambda_function.py` routes the request; the work is in three modules beside it:

- `class_names.py`: the class list from Neon (events whose end date is today or no more
  than 4 months ago, by name up to ` w/ `), and the site's file-name rules: the exact
  file name, the fuzzy key the class list matches on, the branch name.
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
3. Read the class list from Neon; refuse a class that isn't in it, or whose name can't be
   a file name.
4. Read the repository config (SSM) and the GitHub App's credentials (Secrets Manager).
5. Ask GitHub for an installation token for `asmbly-classes` only: read-only on a dry
   run, `contents: write, pull_requests: write` on prod.
6. Plan the submission; on prod, apply it (only when at least 8 s of the function's time
   are left, so a slow read never leaves a half-made commit).

The imports of the three modules work both under pytest (as the package
`functions.classes.class_photo_upload_api`) and under Lambda, where the handler is the
top-level module `lambda_function` (a relative import with a top-level fallback).

## Responses

Every response is JSON with `Content-Type: application/json; charset=utf-8` and
`Cache-Control: no-store`. Errors are `{"error": "<message>"}`; the messages are meant
to be shown to the person as they are, and never carry an exception's text, a status
code from Neon or GitHub, or vendor text.

`GET /class-photo-upload/classes`, 200:

```json
{"dry_run": true,
 "classes": [{"name": "Ceramics: Glazing Workshop", "file_name": "Ceramics__Glazing_Workshop.jpg",
              "problem": null, "warning": null}]}
```

`file_name` is `null` when `problem` is set (a name with `/`, `\` or a control character
can't be a file name). `warning` names the other classes whose photo would be the same
on the class list.

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
| 502 | `Couldn't load the class list. Try again in a minute.` | Neon, or the Neon secret, failed |
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
| SSM parameter | `/${Stage}/config/class-photo-upload`, from `configs/class_photo_upload.json` |
| Authorizer | `StaffCognitoAuthorizer` in `FacilitiesApi`, on the pool in `/config/cognito/staff/user-pool-id` |
| Invoke permission | `ClassPhotoUploadApiInvokePermission`, for `FacilitiesApi` paths under `/class-photo-upload/` |
| Throttle | `POST /class-photo-upload/submit`: 1 request a second, bursts of 5 |

Layers: the common layer (`common.aws`, `common.neoncrm`, `common.github_app`) and the
requests layer. `PyJWT[crypto]==2.15.1` (for the GitHub App's RS256 JWT) is in this
function's `requirements.txt`, so `sam build` bundles it with `cryptography`.

The function may read only its SSM parameter, the Neon secret and the GitHub App
secret, each by its exact ARN. Tag: `Project: classes:class-photo-upload`.

## Configuration

Environment variables (all set by `templates/classes.yaml`):

| Variable | Value |
| --- | --- |
| `NEON_SECRET_NAME` | The Neon secret (`prod/neon_token` by default), with `NEON_ORG_ID` and `NEON_API_KEY` |
| `GITHUB_APP_SECRET_NAME` | `github/class-photo-upload-app` |
| `CLASS_PHOTO_CONFIG_PARAM_NAME` | `/${Stage}/config/class-photo-upload` |
| `CLASS_PHOTO_APP_CLIENT_ID` | The page's app client ID, from `/config/cognito/staff/class-photo-app-client-id` |
| `CLASS_PHOTO_DRY_RUN` | `false` on prod, `true` elsewhere |

The first four are required; without one the function logs its name and answers 500.

The GitHub App secret, `github/class-photo-upload-app` (us-east-2), is a JSON object with
three string keys: `app_id`, `installation_id` and `private_key` (the whole `.pem`, line
breaks as `\n`). A missing key makes a submission answer 500 and log the key's name. How
to create the App and the secret: the plan's README, admin actions 4 and 5
(`.implementation_plans/class-photo-upload/README.md`).

`configs/class_photo_upload.json` holds the repository's coordinates: `repo_owner`,
`repo_name`, `base_branch`, `images_dir`, `branch_prefix` (must end with `/`; the client
can only create or move branches under it) and `image_extensions` (every extension the
site loads, lowercase).

Logs carry the route, the caller's Cognito `sub`, the class name, which check failed,
the action, the pull request number and the branch. They never carry the username (it
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
- **Concurrency.** At most 3 requests run at once (`ReservedConcurrentExecutions`).

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

`tests/test_lambda_function.py` patches `aws`, `NeonCRM` and `github_app` where the
handler uses them and the two `submission` calls, uses the real photo checks and class
rules with JPEGs from `tests/jpeg_builder.py`, and reads the API Gateway events in
`tests/fixtures/api_event_*.json` (fake claims, no real token).
