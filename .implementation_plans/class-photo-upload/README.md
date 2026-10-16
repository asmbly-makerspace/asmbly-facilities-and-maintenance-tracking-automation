---
plan: class-photo-upload
epic: 73
---

# Class photo upload: implementation plan

**Created:** 2026-10-16

## Overview

Changing a class's picture on classes.asmbly.org means a pull request on
`asmbly-makerspace/asmbly-classes` with a 3:2 `.jpg` under an exact file name, which
staff who aren't developers can't easily do, and which goes wrong often (PR #49 there
has several names the site never matches). This plan adds a signed-in page at
`https://facilities.asmbly.org/class-photo-upload`: a staff member picks a class (read
from Neon), drops in a photo, sees at once whether it is acceptable, and clicks Submit.
The server checks the photo again, builds the file name itself, and a GitHub App opens
(or updates) one pull request per class on `asmbly-classes`. Stage is a dry run that
shows what it would do and opens nothing. Nothing is stored.

The spec is the body of #73 (owner-approved, decisions of 13 and 16 October 2026). Where
this plan adds detail, the detail is under **Decisions**.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #104 | Sign in and pick the class from Neon | 1, 5, 6 |
| #105 | Check the photo at once and say how to fix it | 2, 5, 6 |
| #106 | Remove location data before the photo leaves the device | 2, 5, 6 |
| #107 | Submit opens a pull request on asmbly-classes with the right file name | 1, 4, 5, 6 |
| #108 | A second photo for the same class updates the open pull request | 4, 5, 6 |
| #109 | Stage is a dry run that shows what it would do | 4, 5, 6 |

Every story's last phase is phase 6, so only the pull request that lands phase 6 says
`Closes #104 … #109` (and `Closes #73` when every box in #73's "Done when" is ticked);
earlier pull requests say `Refs`. Inside `/offshore` all phases land in one pull request,
which closes them all.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Class list and file-name rule](phase-1-class-names.md) | layer, lambda | L | [x] Complete |
| 2 | [Photo checks](phase-2-photo-checks.md) | lambda | M | [x] Complete |
| 3 | [GitHub App client](phase-3-github-app-client.md) | layer | M | [x] Complete |
| 4 | [Pull request flow and dry run](phase-4-pull-request-flow.md) | lambda | M | [x] Complete |
| 5 | [API function, routes and Cognito authorizer](phase-5-api-and-infra.md) | lambda, infra | L | [x] Complete |
| 6 | [The upload page and docs](phase-6-upload-page.md) | lambda, infra, docs | L | [ ] Pending |

## Dependencies

**Outside this plan**

- #74 (escape the kiln drop-off page) is merged. It shares the host with this page.
- The admin actions below. Phases 1–4 build and test without them; phase 5's stage
  deploy fails until the SSM parameters and the deploy-role redeploy exist; the page
  works on stage only once the app client exists; prod opens pull requests only once
  the GitHub App and its secret exist.
- New Python dependency: `PyJWT[crypto]` (pulls in `cryptography`) for the App's RS256
  JWT. Phase 3 adds it to `requirements-dev.txt`; phase 5 adds it to the API function's
  own `requirements.txt` so `sam build` bundles it. The common layer stays as it is.

**Between phases** (direct predecessors)

| Phase | depends_on | Why |
| --- | --- | --- |
| 1 | — | |
| 2 | 1 | Phase 1 creates the `functions/classes/` and `class_photo_upload_api/` packages |
| 3 | — | |
| 4 | 1, 3 | Uses `class_names` (file name, fuzzy key, branch) and `common.github_app` |
| 5 | 2, 4 | The handler calls `photo_checks` and `submission` |
| 6 | 5 | The page calls the API routes and joins `templates/classes.yaml` |

## Parallelism

| Pair | Verdict | Deciding paths |
| --- | --- | --- |
| 1 and 3 | Parallel-safe | No shared path (phase 1: `neoncrm.py`, `functions/classes/…`; phase 3: `github_app.py`, `requirements-dev.txt`, `layers/common/tests/`) |
| 2 and 3 | Parallel-safe | No shared path |
| 1 and 2 | Sequential-only | Phase 2 depends on 1 (`functions/classes/__init__.py`, `class_photo_upload_api/__init__.py`, `tests/__init__.py`) |
| 2 and 4 | Parallel-safe | No shared path (phase 4 adds `submission.py` and its tests only) |
| 5 and 6 | Sequential-only | `template.yaml`, `templates/classes.yaml`, `template-cicd.yaml` |

Every other pair has a `depends_on` path between it.

## Admin actions

All of these happen outside the repository. Exact steps for each are in the phase that
needs it; the summary:

1. **Before the plan's pull request reaches `stage` (deploy fails otherwise):** create
   three SSM String parameters in us-east-2, all read by both stages:
   - `/config/cognito/staff/user-pool-id`: the staff sign-in pool's ID (for example
     `us-east-2_AbCdEf123`), from the AsmblyMCPs stack.
   - `/config/cognito/staff/auth-domain`: the pool's hosted sign-in domain, host only,
     no `https://` (for example `asmbly-staff.auth.us-east-2.amazoncognito.com`).
   - `/config/cognito/staff/class-photo-app-client-id`: the app client ID from step 3.
2. **Before the plan's pull request reaches `stage`:** redeploy the deploy role,
   `AsmblyFacilitiesMaintTrackingStack-cicd` (docs/Deploying.md, "CI/CD Infrastructure
   (The Deployer Role)"). Phases 5 and 6 add `ClassPhotoUploadApiFunction-{stage,prod}`,
   `ClassPhotoUploadPageFunction-{stage,prod}`, their log groups,
   `/{stage,prod}/config/class-photo-upload`, and read access to the three
   `/config/cognito/staff/...` parameters.
3. **Sign-in pool (AsmblyMCPs), before stage testing:** create one app client for this
   page, `class-photo-upload`: public client (no client secret), authorization code
   grant with PKCE, scope `openid`, identity provider the user pool. Callback URLs and
   sign-out URLs, both: `https://facilities.asmbly.org/class-photo-upload` and
   `https://<stage FacilitiesApi id>.execute-api.us-east-2.amazonaws.com/stage/class-photo-upload`
   (the stage stack's `FacilitiesApiUrl` output plus `/class-photo-upload`). Put its ID
   in `/config/cognito/staff/class-photo-app-client-id`.
4. **A GitHub organization owner, before stage testing:** create the GitHub App
   `Asmbly Class Photos` (owned by `asmbly-makerspace`). Repository permissions:
   **Contents: Read and write**, **Pull requests: Read and write**, **Metadata:
   Read-only** (required); nothing else, no organization or account permissions.
   Webhook: off (uncheck "Active"). "Where can this GitHub App be installed?": Only on
   this account. Install it on **`asmbly-classes` only** ("Only select repositories").
   Note the App ID (App settings, "About") and the installation ID (the number at the
   end of the installation's settings URL), and generate a private key (`.pem`).
5. **Right after step 4:** store the key in Secrets Manager (us-east-2) as the secret
   **`github/class-photo-upload-app`**, a JSON object with exactly these string keys:

   ```json
   {
     "app_id": "1234567",
     "installation_id": "87654321",
     "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n"
   }
   ```

   `private_key` is the whole `.pem` file with its line breaks as `\n`. One way that
   gets the escaping right:
   `aws secretsmanager create-secret --region us-east-2 --name github/class-photo-upload-app --secret-string "$(jq -n --arg app_id 1234567 --arg installation_id 87654321 --rawfile private_key ./asmbly-class-photos.private-key.pem '{app_id:$app_id, installation_id:$installation_id, private_key:$private_key}')"`.
   Then delete the local `.pem`. Both stages read this one secret; stage asks GitHub for
   a read-only token (see Security).
6. **After prod deploy:** nothing to configure; the prod URL is
   `https://facilities.asmbly.org/class-photo-upload`.
7. **Labels (optional):** the `epic` and `story` labels don't exist in this repository;
   add them to #73 and #104–#109 if you want the planning convention's labels.

## Related work

- #79 "Check who is calling each public route": this plan's data routes use a Cognito
  authorizer; the page route itself is a sign-in shell (see Decisions and Security).
- #95 (shared helpers' exception text): phase 1 adds `NeonCRM.search_events` to
  `neoncrm.py` in the new style but leaves the module's existing problems to #95.
- #92 (scope the SAM-generated roles to their own log groups): the two new functions
  use explicit log groups; their generated roles follow the existing pattern.
- PR #68 (lint step, open, from a fork) touches CI only; no shared files.
- Found while planning, not fixed here: `MethodSettings` `ResourcePath: "/nic/update"`
  in `template.yaml` may need `~1` encoding (`/~1nic~1update`) to take effect
  (CloudFormation `MethodSetting.ResourcePath` encodes `/` as `~1`). Phase 5's prep
  confirms it; if true, open an issue rather than changing it here.

## Out of scope

- Anything in `asmbly-classes` besides the pull requests the App opens: no checks, rules,
  `CODEOWNERS` or reviewers there (decided 16 October 2026).
- Notifying anyone (for example the Education Director) when a pull request opens.
- A hostname of its own for the page.
- Storing photos anywhere (no bucket, no Drive).
- Resizing, cropping or re-encoding photos.
- Writing to Neon.
- A JavaScript test runner in CI for the page's script (see Decisions).

## Security

- **Who can call.** `GET /class-photo-upload/classes` and `POST /class-photo-upload/submit`
  sit behind an API Gateway Cognito user-pool authorizer on the staff pool (invitation
  only). Because that authorizer accepts an ID token from any app client of the pool,
  the API function also requires `aud` to equal this page's app client ID and
  `token_use` to be `id` (403 otherwise).
- **The page route `GET /class-photo-upload`** is the sign-in entry point: a browser
  navigation can't carry a bearer token, so this route can't use the authorizer. It
  returns one fixed HTML document whose only inputs are public values (the auth domain
  and app client ID), reads nothing, calls nothing and changes nothing, and the page
  shows nothing until sign-in completes. This is a deliberate, documented exception to
  "a new route must check its caller"; see Decisions.
- **The page** sends a strict `Content-Security-Policy` (per-request nonce for its one
  inline script and style, `connect-src 'self' https://<auth domain>`,
  `frame-ancestors 'none'`). Class names are inserted with `textContent`, never
  `innerHTML`; the server-rendered config is JSON with `<`, `>` and `&` escaped.
- **Tokens** stay in `sessionStorage` for the tab's life (sign-in code exchange with
  PKCE; no client secret exists). The server never logs the `Authorization` header or a
  request body.
- **GitHub.** The App is installed on `asmbly-classes` only. Each request mints a
  one-hour installation token narrowed to `asmbly-classes` and to the permissions that
  request needs: prod asks for `contents: write, pull_requests: write`; stage (dry run)
  asks for `contents: read, pull_requests: read`, so stage cannot write even by mistake.
  The App never updates `main`, never merges, and force-updates only its own
  `class-photo/…` branches when they have no open pull request.
- **Secrets.** `github/class-photo-upload-app` and the existing Neon secret, read through
  `common.aws`, on exact `secret:<name>-*` ARNs. The private key and tokens are never
  logged or returned.
- **Personal data.** The pull request says "Requested by `<cognito:username>`", which the
  owner chose because `asmbly-classes` is public. Logs carry the Cognito `sub`, the class
  name, the branch and the pull request number; never the username, a name or an email.
- **Location data** is removed in the browser; the server refuses any photo that still
  has EXIF GPS or XMP GPS fields, so a browser bug shows up as a refusal, never as a
  leak.
- **Input limits.** The server decodes at most 4 MB of photo, parses only JPEG headers
  (no image decoding library), and builds every path and branch name itself from the
  Neon class list, never from the uploaded file's name.

## Decisions

Made without asking, inside `/offshore` (16 October 2026):

1. **#73 is the epic without the `epic` label.** The label doesn't exist and the GitHub
   tools available can't create labels; the stories are attached as sub-issues, which is
   what `/prep` and `/offshore` read. Alternative: stop until a label exists. Rejected:
   the label carries no behavior here.
2. **#73's body was not edited.** The story list and planning decisions went into a
   comment on #73, so the owner-approved text isn't retyped. Alternative: append a
   `## Stories` section to the body.
3. **3:2 tolerance is 1%:** `abs(width / height - 1.5) / 1.5 <= 0.01`, after the
   orientation flag. 2000×1334 (0.04% off) passes; 4:3, 16:9 and 1:1 fail. Alternative:
   a pixel tolerance; a relative one works the same at every size.
4. **Characters that can't be in a file name:** `/`, `\` and control characters
   (U+0000–U+001F, U+007F). An empty name after trimming is refused too. Other
   punctuation (`&`, `(`, `'`, `.`) is allowed because the site's own rules handle it.
5. **Cognito values come from SSM-typed template parameters** (`/config/cognito/staff/...`),
   the same pattern as `AsmblyHostedZoneId`, so no account-specific ID is in the
   repository and the pool stays owned by AsmblyMCPs. Alternative: values in
   `samconfig.toml` `parameter_overrides`. Rejected: account-specific IDs in the repo,
   and a value change would need a code change.
6. **One app client for both stages**, as #73 says ("an app client for this page, with
   return addresses for prod and stage").
7. **The page route is unauthenticated** (see Security). The issue's design (a Cognito
   authorizer, "no sign-in code to write here") implies a static sign-in shell; the
   authorizer guards every route that reads or does anything. The maintainer can
   revisit this under #79.
8. **ID token, `aud` check.** The page sends the Cognito ID token in `Authorization`
   (what a REST API Cognito authorizer without scopes expects), and the function checks
   `aud` and `token_use` because the authorizer alone accepts any client of the pool.
9. **Two functions:** a page function with no secrets, and an API function for the two
   data routes. Alternative: one function for all three routes. Rejected: the page
   would hold the GitHub key it never needs.
10. **New area `classes`:** `functions/classes/`, `templates/classes.yaml`, nested stack
    `ClassesStack`, `Project` tag `classes:class-photo-upload`.
11. **Repository coordinates are configuration:** `configs/class_photo_upload.json` →
    SSM `/${Stage}/config/class-photo-upload` (owner, repo, base branch, images
    directory, branch prefix, extensions the site loads). The App's IDs are in its
    secret.
12. **One secret, `github/class-photo-upload-app`, for both stages**, with stage
    requesting read-only installation tokens. Alternative: no GitHub access on stage and
    read the public repository anonymously. Rejected: anonymous API calls share a
    60-an-hour limit per IP. Alternative: a second, read-only App for stage. Rejected as
    more admin work for little gain; noted in Security.
13. **The `PyJWT[crypto]` dependency lives with the function** (its `requirements.txt`),
    not in the common layer, whose build copies files as they are. `common/github_app.py`
    imports `jwt`; only the API function imports that module.
14. **Branch per class:** `class-photo/<slug>-<hash8>`, where `slug` is the exact file
    stem lowercased with runs of other characters as `-` (at most 50 characters), and
    `hash8` the first 8 hex digits of SHA-256 of the class name. Two classes never share
    a branch, even when their fuzzy keys collide.
15. **Repeat submission:** an open pull request from the class's branch gets a new
    commit on that branch (non-force). If the branch exists with no open pull request
    (merged, closed, or a failed earlier run), the branch is force-moved to a new commit
    on the current `main` and a new pull request is opened. A concurrent submission that
    loses the non-force race gets 409 "Someone else just submitted a photo for this
    class. Try again."
16. **The pull request description is rewritten on each submission** to the latest
    submission; the commit message of each commit names its requester, so the history
    keeps every requester.
17. **Fuzzy removal covers every extension the site loads** (`avif, gif, heif, jpeg, jpg,
    png, tiff, webp`, from `import.meta.glob` in `classCard.svelte`), top level of
    `app/src/lib/images/` only, matching the site.
18. **Location removal in the browser:** the GPS IFD pointer (tag `0x8825`) is removed
    from EXIF IFD0 and the GPS IFD's bytes are zeroed; any XMP segment (standard or
    extended) that contains GPS properties is dropped whole, because rewriting XMP
    safely in the browser is out of proportion. Orientation is in EXIF IFD0 and is kept.
    Compressed image data is never touched.
19. **The page's JavaScript has no automated tests** in this plan: the repository has no
    JavaScript test runner and CI is Python only. The server re-checks everything the
    browser checks, Python tests cover the served HTML (escaping, config, CSP), and
    `MANUAL_QA.md` covers the browser behavior. Alternative: add `node --test` to CI;
    left as a follow-up.
20. **Class list window:** Neon events whose `Event End Date` is on or after today minus
    4 calendar months (UTC), archived or not, no category filter; one entry per class
    name. `CLASS_LOOKBACK_MONTHS = 4` is a named constant in `class_names.py`.
21. **Request shape:** JSON `{"class_name": "...", "photo_base64": "..."}`. A 4 MB photo
    is about 5.6 MB in base64, under Lambda's 6 MB request limit; the server refuses a
    decoded photo over 4 MB (4 × 1024 × 1024 bytes) with the size message.
22. **Logging the requester:** logs carry the Cognito `sub`, not the username (CLAUDE.md:
    log IDs, not names); the username appears only in the pull request, as #73 decided.
23. **PR #49's names** came from a read-only clone of `asmbly-classes` (public); the list
    and the current image names at `bdf601b` are written into phase 1 so the build does
    not need access to that repository.
24. **Phase 3 implements no story directly** (`implements: []`): it is a helper with no
    caller until phase 5. Phases 5 and 6 list every story their wiring and page complete;
    stories close with phase 6.
25. **Location data means GPS coordinates; reverse-geocoded place names are not
    checked.** The server and the page look for EXIF GPS (the `0x8825` pointer in IFD0,
    IFD1 or the Exif sub-IFD) and XMP GPS properties, in the main image, in every JPEG
    embedded in the file (thumbnails, MPF images, gain maps) and in any trailer. Place
    names that photo apps add (IPTC-IIM City/Sub-location/State in APP13, XMP
    `photoshop:City`, `Iptc4xmpCore:Location`, `Iptc4xmpExt:LocationCreated`) are not
    looked for or removed. Decided in phase 2's review (16 October 2026) to keep this
    pull request's scope; the owner can widen it later. Alternative: refuse or strip
    those fields too.
26. **Embedded images and trailers** (phase 2 review): the server walks every further
    JPEG start in the file (at most 16; more refuse the file as unreadable) and searches
    the bytes after the main headers for XMP GPS. It does not refuse a photo just for
    carrying embedded images, which most phone photos do. Phase 6's page removes the
    location from them or, where it can't, refuses with its own message.
27. **A repeat submission's commit merges the current `main`** (phase 4 prep, 16 October
    2026). With an open pull request, the new commit has two parents, the branch head and
    the base head (only the branch head when the base hasn't moved), and its tree is the base tree plus the photo minus the superseded
    images, so the branch moves without force and the pull request's diff and description
    are both relative to the current `main` (images added to `main` since the branch was
    made are removed too). This needs `GitHubRepo.create_commit(..., extra_parent=...)`.
    A commit pushed by hand to a `class-photo/` branch is not carried into the next
    submission. Alternative: build on the branch head and list images there. Rejected:
    the second submission's description said "Removed: none" while the pull request
    removed files, and images that reached `main` later were never removed. Every outside
    value in the pull request description, including the other classes in a collision
    warning, is in a code span fenced longer than any backtick run in it.
