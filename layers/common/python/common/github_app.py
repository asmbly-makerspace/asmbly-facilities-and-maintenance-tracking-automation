"""A small GitHub App client: installation tokens and the calls the class photo flow needs.

Requires `PyJWT[crypto]`, which the common layer does not bundle; a function that imports
this module lists it in its own `requirements.txt`.

Nothing here logs or raises with a token, the App's JWT, its private key, a header or a
response body: errors carry an operation name and an HTTP status only. The client can
create or move only branches under the prefix it is given, and has no method that merges
a pull request or deletes a branch. It does not retry; the caller decides.
"""
import logging
import time
from typing import Any
from urllib.parse import quote

import jwt
import requests

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "asmbly-class-photo-upload"
JWT_BACKDATE_SECONDS = 60
JWT_LIFETIME_SECONDS = 540


class GitHubError(Exception):
    """A GitHub call failed. Message: operation and HTTP status only."""

    def __init__(self, operation: str, status: int | None) -> None:
        super().__init__(f"GitHub {operation} failed (status {status})")
        self.operation = operation
        self.status = status


class GitHubConflict(GitHubError):
    """422 or 409: a ref update that isn't a fast-forward, or a pull request that exists.

    Raised only by create_branch, update_branch and create_pull_request; any other
    operation's 409 or 422 is a plain GitHubError.
    """


CONFLICT_OPERATIONS = frozenset({"create_branch", "update_branch", "create_pull_request"})


def _fail(operation: str, status: int | None, reason: str) -> GitHubError:
    """Log a failed call by operation, status and a fixed reason, and build its error."""
    logger.error("GitHub %s failed: status %s (%s)", operation, status, reason)
    if status in (409, 422) and operation in CONFLICT_OPERATIONS:
        return GitHubConflict(operation, status)
    return GitHubError(operation, status)


def _headers(bearer: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": USER_AGENT,
    }


def _request(
    operation: str,
    method: str,
    url: str,
    bearer: str,
    timeout: float,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    missing_ok: bool = False,
) -> Any:
    """Send one request and return its parsed JSON; None for a 404 when missing_ok."""
    try:
        response = requests.request(
            method, url, headers=_headers(bearer), json=body, params=params, timeout=timeout
        )
    except requests.exceptions.RequestException as e:
        raise _fail(operation, None, type(e).__name__) from None

    status = response.status_code
    if missing_ok and status == 404:
        return None
    if not 200 <= status < 300:
        raise _fail(operation, status, "unexpected status")
    if status == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise _fail(operation, status, "response is not JSON") from None


def _field(data: Any, operation: str, *keys: str) -> Any:
    """Read data[k1][k2]...; a missing or malformed field is a GitHubError."""
    value = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise _fail(operation, None, "response is missing a field")
        value = value[key]
    return value


def app_jwt(app_id: str, private_key: str, now: int | None = None) -> str:
    """RS256 JWT: iat = now - 60, exp = now + 540, iss = app_id."""
    issued = int(time.time()) if now is None else now
    claims = {
        "iat": issued - JWT_BACKDATE_SECONDS,
        "exp": issued + JWT_LIFETIME_SECONDS,
        "iss": app_id,
    }
    try:
        return jwt.encode(claims, private_key, algorithm="RS256")
    except Exception as e:
        # The underlying error can describe the key; report its class only.
        raise _fail("app_jwt", None, type(e).__name__) from None


def installation_token(
    app_id: str,
    installation_id: str,
    private_key: str,
    repository: str,
    permissions: dict[str, str],
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """POST /app/installations/{installation_id}/access_tokens with
    {"repositories": [repository], "permissions": permissions}; returns `token`.

    An empty `permissions` would get every permission the App has, so it is refused.
    """
    if not repository or "/" in repository:
        raise ValueError("repository must be a repository name without its owner")
    if not permissions:
        raise ValueError("permissions must name at least one permission")

    token_jwt = app_jwt(app_id, private_key)
    url = f"{GITHUB_API_URL}/app/installations/{quote(str(installation_id), safe='')}/access_tokens"
    data = _request(
        "installation_token",
        "POST",
        url,
        token_jwt,
        timeout,
        body={"repositories": [repository], "permissions": dict(permissions)},
    )
    token = _field(data, "installation_token", "token")
    if not isinstance(token, str) or not token:
        raise _fail("installation_token", None, "response is missing a field")
    return token


class GitHubRepo:
    """The calls the class photo flow makes on one repository with an installation token."""

    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        writable_branch_prefix: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not writable_branch_prefix.endswith("/"):
            raise ValueError("writable_branch_prefix must end with '/'")
        self._token = token
        self.owner = owner
        self.repo = repo
        self.writable_branch_prefix = writable_branch_prefix
        self.timeout = timeout
        self._base_url = f"{GITHUB_API_URL}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"

    def _call(
        self,
        operation: str,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        missing_ok: bool = False,
    ) -> Any:
        return _request(
            operation,
            method,
            f"{self._base_url}/{path}",
            self._token,
            self.timeout,
            body=body,
            params=params,
            missing_ok=missing_ok,
        )

    def _check_writable(self, branch: str) -> None:
        prefix = self.writable_branch_prefix
        if not prefix or not branch.startswith(prefix) or len(branch) == len(prefix) or ".." in branch:
            raise ValueError("branch is outside the writable prefix")

    def get_branch_sha(self, branch: str) -> str | None:
        """GET git/ref/heads/{branch}; the commit SHA, or None when the branch doesn't exist."""
        data = self._call(
            "get_branch_sha", "GET", f"git/ref/heads/{quote(branch, safe='/')}", missing_ok=True
        )
        if data is None:
            return None
        return _field(data, "get_branch_sha", "object", "sha")

    def get_commit_tree_sha(self, commit_sha: str) -> str:
        """GET git/commits/{sha}; the commit's tree SHA."""
        data = self._call("get_commit_tree_sha", "GET", f"git/commits/{quote(commit_sha, safe='')}")
        return _field(data, "get_commit_tree_sha", "tree", "sha")

    def list_directory(self, path: str, ref: str) -> list[str]:
        """GET contents/{path}?ref=...; the names of the files in it ([] when it doesn't exist)."""
        data = self._call(
            "list_directory",
            "GET",
            f"contents/{quote(path.strip('/'), safe='/')}",
            params={"ref": ref},
            missing_ok=True,
        )
        if data is None:
            return []
        if not isinstance(data, list):
            raise _fail("list_directory", None, "path is not a directory")
        return [
            entry["name"]
            for entry in data
            if isinstance(entry, dict) and entry.get("type") == "file" and isinstance(entry.get("name"), str)
        ]

    def create_blob(self, content_base64: str) -> str:
        """POST git/blobs; the new blob's SHA."""
        data = self._call(
            "create_blob", "POST", "git/blobs", body={"content": content_base64, "encoding": "base64"}
        )
        return _field(data, "create_blob", "sha")

    def create_tree(self, base_tree: str, entries: list[dict[str, Any]]) -> str:
        """POST git/trees on top of base_tree; an entry with "sha": None deletes its path."""
        data = self._call(
            "create_tree", "POST", "git/trees", body={"base_tree": base_tree, "tree": entries}
        )
        return _field(data, "create_tree", "sha")

    def create_commit(
        self, message: str, tree_sha: str, parent_sha: str, extra_parent: str | None = None
    ) -> str:
        """POST git/commits; the new commit's SHA.

        One parent, or two (`[parent_sha, extra_parent]`, a merge commit) when
        extra_parent is given.
        """
        parents = [parent_sha] if extra_parent is None else [parent_sha, extra_parent]
        data = self._call(
            "create_commit",
            "POST",
            "git/commits",
            body={"message": message, "tree": tree_sha, "parents": parents},
        )
        return _field(data, "create_commit", "sha")

    def create_branch(self, branch: str, sha: str) -> None:
        """POST git/refs for refs/heads/{branch}. Only under the writable prefix."""
        self._check_writable(branch)
        self._call("create_branch", "POST", "git/refs", body={"ref": f"refs/heads/{branch}", "sha": sha})

    def update_branch(self, branch: str, sha: str, force: bool) -> None:
        """PATCH git/refs/heads/{branch}. Only under the writable prefix.

        Without force, a move that isn't a fast-forward raises GitHubConflict (422).
        """
        self._check_writable(branch)
        self._call(
            "update_branch",
            "PATCH",
            f"git/refs/heads/{quote(branch, safe='/')}",
            body={"sha": sha, "force": force},
        )

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        """GET compare/{ancestor}...{descendant}; True when ancestor_sha is in descendant_sha's
        history (status "ahead" or "identical"). Read-only."""
        data = self._call(
            "compare_commits",
            "GET",
            f"compare/{quote(ancestor_sha, safe='')}...{quote(descendant_sha, safe='')}",
            params={"per_page": "1"},
        )
        status = _field(data, "compare_commits", "status")
        if not isinstance(status, str):
            raise _fail("compare_commits", None, "response is missing a field")
        return status in ("ahead", "identical")

    def find_open_pull_request(self, branch: str, base: str) -> dict[str, Any] | None:
        """GET pulls?state=open&head={owner}:{branch}&base={base}; the first one's number and URL."""
        data = self._call(
            "find_open_pull_request",
            "GET",
            "pulls",
            params={"state": "open", "head": f"{self.owner}:{branch}", "base": base},
        )
        if not isinstance(data, list):
            raise _fail("find_open_pull_request", None, "response is not a list")
        if not data:
            return None
        return self._pull_request_summary(data[0], "find_open_pull_request")

    def create_pull_request(self, title: str, branch: str, base: str, body: str) -> dict[str, Any]:
        """POST pulls; its number and URL. An existing pull request raises GitHubConflict (422)."""
        data = self._call(
            "create_pull_request",
            "POST",
            "pulls",
            body={
                "title": title,
                "head": branch,
                "base": base,
                "body": body,
                "maintainer_can_modify": False,
            },
        )
        return self._pull_request_summary(data, "create_pull_request")

    def update_pull_request(self, number: int, title: str, body: str) -> dict[str, Any]:
        """PATCH pulls/{number} with a new title and description; its number and URL."""
        data = self._call(
            "update_pull_request", "PATCH", f"pulls/{int(number)}", body={"title": title, "body": body}
        )
        return self._pull_request_summary(data, "update_pull_request")

    @staticmethod
    def _pull_request_summary(data: Any, operation: str) -> dict[str, Any]:
        return {
            "number": _field(data, operation, "number"),
            "html_url": _field(data, operation, "html_url"),
        }
