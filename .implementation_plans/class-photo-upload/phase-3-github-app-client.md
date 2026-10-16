---
phase_id: 3
title: GitHub App client
epic: 73
implements: []
depends_on: []
domain: [layer]
estimated_size: M
---

# Phase 3: GitHub App client

> **Status:** [x] Complete — 2026-10-16 on branch claude/inspiring-bell-o4i5t9

## Required reading

- `CLAUDE.md` ("Rules": helpers in the common layer, no secrets in logs or errors).
- `layers/common/python/common/aws.py` (`_error_summary`, how a helper logs an error
  without its text) and `layers/common/tests/test_aws.py` (layer test layout).
- GitHub REST docs, API version `2022-11-28`:
  "Authenticating as a GitHub App" (JWT: RS256, `iat` 60 s in the past, `exp` at most
  10 minutes ahead, `iss` = App ID); "Create an installation access token for an app"
  (`POST /app/installations/{installation_id}/access_tokens`, body `repositories` and
  `permissions` to narrow the token; 201 with `token`, `expires_at`); Git database
  (`git/ref`, `git/refs`, `git/commits`, `git/blobs`, `git/trees`); "Get repository
  content"; "List pull requests" (`head=owner:branch`, `state=open`); "Create a pull
  request"; "Update a pull request".

## Goal

A tested helper that turns the App's secret into a short-lived, narrowed installation
token and makes the handful of GitHub calls the pull request flow needs, without ever
logging or raising with a token, a key, or a response body. It can't write to a branch
outside the prefix it was given. Nothing calls it yet.

## Files to create

- `layers/common/python/common/github_app.py`.
- `layers/common/tests/test_github_app.py`.

## Files to modify

- `requirements-dev.txt`: add `PyJWT[crypto]==2.10.1` (prep: confirm the newest
  2.x release that is at least two weeks old and pin that; `cryptography` comes with it).

## Implementation details

### layer: `common/github_app.py`

Module docstring: "Requires `PyJWT[crypto]`, which the common layer does not bundle; a
function that imports this module lists it in its own `requirements.txt`."

```python
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT = 10.0

class GitHubError(Exception):
    """A GitHub call failed. Message: operation and HTTP status only."""
    def __init__(self, operation: str, status: int | None) -> None: ...
    status: int | None

class GitHubConflict(GitHubError):
    """422 or 409: a ref update that isn't a fast-forward, or a pull request that exists."""

def app_jwt(app_id: str, private_key: str, now: int | None = None) -> str:
    """RS256 JWT: iat = now - 60, exp = now + 540, iss = app_id."""

def installation_token(
    app_id: str,
    installation_id: str,
    private_key: str,
    repository: str,
    permissions: dict[str, str],
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """POST /app/installations/{installation_id}/access_tokens with
    {"repositories": [repository], "permissions": permissions}; returns `token`."""

class GitHubRepo:
    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        writable_branch_prefix: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None: ...

    def get_branch_sha(self, branch: str) -> str | None          # GET git/ref/heads/{branch}; 404 → None
    def get_commit_tree_sha(self, commit_sha: str) -> str        # GET git/commits/{sha} → tree.sha
    def list_directory(self, path: str, ref: str) -> list[str]   # GET contents/{path}?ref=…; names of type "file"; 404 → []
    def create_blob(self, content_base64: str) -> str            # POST git/blobs {"content", "encoding": "base64"}
    def create_tree(self, base_tree: str, entries: list[dict]) -> str
    def create_commit(self, message: str, tree_sha: str, parent_sha: str) -> str
    def create_branch(self, branch: str, sha: str) -> None       # POST git/refs {"ref": "refs/heads/…", "sha"}
    def update_branch(self, branch: str, sha: str, force: bool) -> None   # PATCH git/refs/heads/{branch}
    def find_open_pull_request(self, branch: str, base: str) -> dict | None
        # GET pulls?state=open&head={owner}:{branch}&base={base}; first item's {"number", "html_url"} or None
    def create_pull_request(self, title: str, branch: str, base: str, body: str) -> dict
        # POST pulls {"title", "head": branch, "base", "body", "maintainer_can_modify": False}
    def update_pull_request(self, number: int, title: str, body: str) -> dict   # PATCH pulls/{number}
```

- Every request sends `Authorization: Bearer <token>` (installation calls) or
  `Bearer <jwt>` (the token call), `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`, and `User-Agent: asmbly-class-photo-upload`, with
  `timeout`. Path segments (branch names, paths) are URL-quoted with
  `urllib.parse.quote(..., safe="/")`.
- `create_branch` and `update_branch` raise `ValueError` before any request when
  `branch` doesn't start with `writable_branch_prefix` (or the prefix is empty). There
  is no method that merges or deletes anything.
- Errors: `requests.exceptions.RequestException` → `GitHubError(operation, None)`; a
  non-2xx answer → `GitHubConflict` for 409 and 422, else `GitHubError(operation,
  status)`; the token call's answer without `token` → `GitHubError`. Each logs
  `logger.error("GitHub %s failed: status %s", operation, status)` where `operation` is a
  fixed name like `"update_branch"`. Never the response body, headers, token, JWT or key.
- No retries inside the helper; the caller decides (the API Gateway limit is 29 s).
- Type hints throughout, lazy logging, `logger = logging.getLogger(__name__)`.

## Tests

`layers/common/tests/test_github_app.py`, with `requests-mock` and a 2048-bit RSA key
generated once per module with `cryptography`:

- `test_app_jwt_claims_and_signature`: decodes with the public key (RS256); `iss` is the
  App ID, `iat == now - 60`, `exp == now + 540`.
- `test_installation_token_narrows_repository_and_permissions`: the POST body is
  `{"repositories": ["asmbly-classes"], "permissions": {"contents": "read",
  "pull_requests": "read"}}`, the bearer is a JWT, and the token comes back.
- `test_installation_token_error_hides_body_and_key`: a 401 with a body marker raises
  `GitHubError` with status 401; the marker, the JWT and any line of the key are absent
  from the exception text and `caplog`.
- `test_requests_carry_headers_and_timeout`: `Accept`, `X-GitHub-Api-Version`,
  `User-Agent`, bearer token; a patched `requests.request` (or session) sees `timeout`.
- `test_get_branch_sha_missing_returns_none` (404) and `..._found`.
- `test_list_directory_returns_file_names_only`: `dir` entries are skipped; 404 → `[]`.
- `test_create_blob_tree_commit_shapes`: request bodies as specified, SHAs returned;
  a delete entry in `create_tree` is passed through with `"sha": None` serialized as JSON
  `null`.
- `test_branch_names_are_quoted`: a branch with spaces or `#` is quoted in the URL.
- `test_update_branch_non_fast_forward_raises_conflict` (422).
- `test_write_outside_prefix_is_refused`: `create_branch("main", …)` and
  `update_branch("main", …)` raise `ValueError` and send no request (`requests_mock`
  call count 0).
- `test_find_open_pull_request_uses_head_and_base`: query string has
  `head=asmbly-makerspace:class-photo/x-1234abcd`, `state=open`, `base=main`; empty list
  → `None`.
- `test_create_pull_request_existing_raises_conflict` (422).
- `test_timeout_raises_github_error`.

## Acceptance criteria

1. `installation_token` requests a token for exactly one repository and exactly the
   permissions passed in. (Supports #109 AC3: stage asks for read-only.)
2. No exception message or log line from this module contains a token, the JWT, the
   private key, a response body or a header.
3. The client can't create or move a branch outside its prefix, and has no merge or
   delete method. (Supports #107 AC6.)
4. `.venv/bin/python -m pytest` passes with the new dev dependency installed.

## Verification

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest layers/common/tests/test_github_app.py
.venv/bin/python -m pytest
```

No template change. `sam build` is unaffected (the layer still has no requirements file).

## Admin actions

None for this phase. (The App itself is admin action 4 in the README; nothing calls this
helper until phase 5.)

## Hand-off

- `common.github_app` (`layers/common/python/common/github_app.py`):
  - `app_jwt(app_id, private_key, now=None) -> str`.
  - `installation_token(app_id, installation_id, private_key, repository, permissions,
    timeout=10.0) -> str`. `repository` is the bare name (`"asmbly-classes"`, no owner);
    an empty name, a name with `/`, or an empty `permissions` raises `ValueError` before
    any request (an empty `permissions` would get every permission the App has).
  - `GitHubRepo(token, owner, repo, writable_branch_prefix, timeout=10.0)` with
    `get_branch_sha`, `get_commit_tree_sha`, `list_directory`, `create_blob`,
    `create_tree`, `create_commit`, `create_branch`, `update_branch`,
    `find_open_pull_request`, `create_pull_request`, `update_pull_request`, as specified
    above. Pull request methods return `{"number", "html_url"}` only.
  - `GitHubRepo(...)` raises `ValueError` when `writable_branch_prefix` doesn't end with
    `/` (so an empty or mistyped prefix like `"m"` can't admit `main`). Phase 5's config
    must set the prefix to `class-photo/`.
  - `create_branch` / `update_branch` raise `ValueError` (no request) when the branch is
    not strictly under the prefix (equal to it, or containing `..`, is refused too).
  - Errors: `GitHubError(operation, status)` with `.operation` and `.status`;
    `GitHubConflict` (subclass) for a 409 or 422 from `create_branch`, `update_branch`
    or `create_pull_request` only. Every other operation's 409 or 422 (including
    `installation_token`, `create_blob`, `create_tree`, `create_commit`,
    `update_pull_request`) is a plain `GitHubError`. GitHub also answers 422 to these
    three for reasons that aren't races (a deleted ref, "no commits between"), so phase 4
    should treat a conflict as "look again", not always as a concurrent submission. A network error or timeout has
    `status=None`; a 2xx answer that isn't JSON or lacks a field the method reads is a
    `GitHubError` too (`status` is the HTTP status, or `None` for a missing field). Every
    failure logs one line, `GitHub <operation> failed: status <status> (<reason>)`, where
    reason is a fixed phrase or an exception class name. Errors are raised `from None`,
    so no chained exception carries a key, URL or body into a traceback.
  - `list_directory` on a path that is a file raises `GitHubError`; a missing path
    returns `[]`. The contents API lists at most 1,000 entries per directory (the
    images directory has far fewer).
- The module imports `jwt` and `requests` at import time, so the phase 5 function needs
  `PyJWT[crypto]==2.15.1` in its `requirements.txt` and the requests layer
  (`RequestsLayerARN`), like the other functions that use the common layer.
- `requirements-dev.txt` pins `PyJWT[crypto]==2.15.1` (newest 2.x at least two weeks old
  on 2026-10-16); phase 5 pins the same version.
- Tests: `layers/common/tests/test_github_app.py` (`requests_mock`, a module-scoped RSA
  key from `cryptography`).
