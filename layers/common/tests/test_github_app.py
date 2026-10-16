import logging
import os
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import requests
import requests_mock as requests_mock_module
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Add the python directory to the path to allow common module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'python')))

from common import github_app
from common.github_app import GitHubConflict, GitHubError, GitHubRepo

API = "https://api.github.com"
REPO_API = f"{API}/repos/asmbly-makerspace/asmbly-classes"
TOKEN = "ghs_installationTokenValue123"
BODY_MARKER = "SECRET-BODY-MARKER-7f3a"
APP_ID = "1234567"
INSTALLATION_ID = "87654321"
PREFIX = "class-photo/"
BRANCH = "class-photo/x-1234abcd"


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, str]:
    """A 2048-bit RSA key generated once for this module: (private PEM, public PEM)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


@pytest.fixture
def repo() -> GitHubRepo:
    return GitHubRepo(TOKEN, "asmbly-makerspace", "asmbly-classes", PREFIX)


def _module_log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(
        r.getMessage() for r in caplog.records if r.name == "common.github_app"
    )


def _key_lines(private_pem: str) -> list[str]:
    return [line for line in private_pem.splitlines() if line and not line.startswith("-----")]


def _assert_secret_free(text: str, secrets: list[str]) -> None:
    for secret in secrets:
        assert secret not in text


# --- app_jwt and installation_token ---


def test_app_jwt_claims_and_signature(key_pair: tuple[str, str]) -> None:
    private_pem, public_pem = key_pair
    now = 1_760_000_000

    token = github_app.app_jwt(APP_ID, private_pem, now=now)

    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(
        token, public_pem, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
    )
    assert claims == {"iss": APP_ID, "iat": now - 60, "exp": now + 540}


def test_app_jwt_bad_key_raises_without_key_text(caplog: pytest.LogCaptureFixture) -> None:
    bad_key = "-----BEGIN RSA PRIVATE KEY-----\nNOTAKEYLINE0123456789\n-----END RSA PRIVATE KEY-----\n"
    caplog.set_level(logging.DEBUG)

    with pytest.raises(GitHubError) as excinfo:
        github_app.app_jwt(APP_ID, bad_key)

    assert excinfo.value.operation == "app_jwt"
    assert excinfo.value.status is None
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    _assert_secret_free(str(excinfo.value), ["NOTAKEYLINE0123456789"])
    _assert_secret_free(caplog.text, ["NOTAKEYLINE0123456789"])


def test_installation_token_narrows_repository_and_permissions(
    requests_mock: requests_mock_module.Mocker, key_pair: tuple[str, str]
) -> None:
    private_pem, public_pem = key_pair
    adapter = requests_mock.post(
        f"{API}/app/installations/{INSTALLATION_ID}/access_tokens",
        status_code=201,
        json={"token": TOKEN, "expires_at": "2026-10-16T12:00:00Z"},
    )

    token = github_app.installation_token(
        APP_ID,
        INSTALLATION_ID,
        private_pem,
        "asmbly-classes",
        {"contents": "read", "pull_requests": "read"},
    )

    assert token == TOKEN
    assert adapter.call_count == 1
    request = adapter.last_request
    assert request.json() == {
        "repositories": ["asmbly-classes"],
        "permissions": {"contents": "read", "pull_requests": "read"},
    }
    scheme, bearer = request.headers["Authorization"].split(" ", 1)
    assert scheme == "Bearer"
    claims = jwt.decode(bearer, public_pem, algorithms=["RS256"])
    assert claims["iss"] == APP_ID


@pytest.mark.parametrize(
    "repository, permissions",
    [
        ("asmbly-classes", {}),
        ("", {"contents": "read"}),
        ("asmbly-makerspace/asmbly-classes", {"contents": "read"}),
    ],
)
def test_installation_token_refuses_unscoped_requests(
    requests_mock: requests_mock_module.Mocker,
    key_pair: tuple[str, str],
    repository: str,
    permissions: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        github_app.installation_token(APP_ID, INSTALLATION_ID, key_pair[0], repository, permissions)
    assert requests_mock.call_count == 0


def test_installation_token_error_hides_body_and_key(
    requests_mock: requests_mock_module.Mocker,
    key_pair: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_pem, _ = key_pair
    caplog.set_level(logging.DEBUG)
    adapter = requests_mock.post(
        f"{API}/app/installations/{INSTALLATION_ID}/access_tokens",
        status_code=401,
        json={"message": BODY_MARKER},
    )

    with pytest.raises(GitHubError) as excinfo:
        github_app.installation_token(
            APP_ID, INSTALLATION_ID, private_pem, "asmbly-classes", {"contents": "read"}
        )

    assert not isinstance(excinfo.value, GitHubConflict)
    assert excinfo.value.status == 401
    assert excinfo.value.operation == "installation_token"
    sent_jwt = adapter.last_request.headers["Authorization"].split(" ", 1)[1]
    secrets = [BODY_MARKER, sent_jwt, "Bearer"] + _key_lines(private_pem)
    _assert_secret_free(str(excinfo.value), secrets)
    _assert_secret_free(caplog.text, secrets)
    assert "GitHub installation_token failed: status 401" in _module_log_text(caplog)


def test_installation_token_without_token_raises(
    requests_mock: requests_mock_module.Mocker, key_pair: tuple[str, str]
) -> None:
    requests_mock.post(
        f"{API}/app/installations/{INSTALLATION_ID}/access_tokens",
        status_code=201,
        json={"expires_at": "2026-10-16T12:00:00Z"},
    )

    with pytest.raises(GitHubError) as excinfo:
        github_app.installation_token(
            APP_ID, INSTALLATION_ID, key_pair[0], "asmbly-classes", {"contents": "read"}
        )
    assert excinfo.value.operation == "installation_token"


# --- request basics ---


def test_requests_carry_headers_and_timeout(
    requests_mock: requests_mock_module.Mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_mock.get(f"{REPO_API}/git/ref/heads/main", json={"object": {"sha": "abc"}})
    seen: dict[str, Any] = {}
    real_request = requests.request

    def spy(method: str, url: str, **kwargs: Any) -> requests.Response:
        seen.update(kwargs)
        return real_request(method, url, **kwargs)

    monkeypatch.setattr(github_app.requests, "request", spy)
    repo = GitHubRepo(TOKEN, "asmbly-makerspace", "asmbly-classes", PREFIX, timeout=7.5)

    repo.get_branch_sha("main")

    assert seen["timeout"] == 7.5
    headers = requests_mock.last_request.headers
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["User-Agent"] == "asmbly-class-photo-upload"
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_timeout_raises_github_error(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    requests_mock.get(f"{REPO_API}/git/ref/heads/main", exc=requests.exceptions.ConnectTimeout)

    with pytest.raises(GitHubError) as excinfo:
        repo.get_branch_sha("main")

    assert excinfo.value.status is None
    assert excinfo.value.operation == "get_branch_sha"
    assert excinfo.value.__cause__ is None
    assert "GitHub get_branch_sha failed: status None (ConnectTimeout)" in _module_log_text(caplog)
    _assert_secret_free(caplog.text, [TOKEN])


def test_server_error_hides_body_and_token(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    requests_mock.post(f"{REPO_API}/git/blobs", status_code=500, text=BODY_MARKER)

    with pytest.raises(GitHubError) as excinfo:
        repo.create_blob("aGVsbG8=")

    assert excinfo.value.status == 500
    _assert_secret_free(str(excinfo.value), [BODY_MARKER, TOKEN])
    _assert_secret_free(caplog.text, [BODY_MARKER, TOKEN])


def test_non_json_success_raises_github_error(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.post(f"{REPO_API}/git/blobs", status_code=201, text="<html>" + BODY_MARKER)

    with pytest.raises(GitHubError) as excinfo:
        repo.create_blob("aGVsbG8=")
    assert excinfo.value.status == 201
    assert BODY_MARKER not in str(excinfo.value)


# --- reads ---


def test_get_branch_sha_found(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    requests_mock.get(
        f"{REPO_API}/git/ref/heads/main",
        json={"ref": "refs/heads/main", "object": {"sha": "abc123", "type": "commit"}},
    )
    assert repo.get_branch_sha("main") == "abc123"


def test_get_branch_sha_missing_returns_none(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.get(f"{REPO_API}/git/ref/heads/{BRANCH}", status_code=404, json={"message": "Not Found"})
    assert repo.get_branch_sha(BRANCH) is None


def test_get_commit_tree_sha(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    requests_mock.get(f"{REPO_API}/git/commits/abc123", json={"sha": "abc123", "tree": {"sha": "tree456"}})
    assert repo.get_commit_tree_sha("abc123") == "tree456"


def test_get_commit_tree_sha_missing_field_raises(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.get(f"{REPO_API}/git/commits/abc123", json={"sha": "abc123"})
    with pytest.raises(GitHubError):
        repo.get_commit_tree_sha("abc123")


def test_list_directory_returns_file_names_only(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    adapter = requests_mock.get(
        f"{REPO_API}/contents/app/src/lib/images",
        json=[
            {"type": "file", "name": "Woodshop Safety.jpg"},
            {"type": "dir", "name": "icons"},
            {"type": "file", "name": "Laser Cutting.png"},
        ],
    )

    names = repo.list_directory("app/src/lib/images", "abc123")

    assert names == ["Woodshop Safety.jpg", "Laser Cutting.png"]
    assert parse_qs(urlparse(adapter.last_request.url).query) == {"ref": ["abc123"]}


def test_list_directory_missing_returns_empty(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.get(f"{REPO_API}/contents/app/src/lib/images", status_code=404)
    assert repo.list_directory("app/src/lib/images", "abc123") == []


def test_list_directory_on_a_file_raises(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.get(f"{REPO_API}/contents/README.md", json={"type": "file", "name": "README.md"})
    with pytest.raises(GitHubError):
        repo.list_directory("README.md", "abc123")


def test_branch_names_are_quoted(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    adapter = requests_mock.get(requests_mock_module.ANY, json={"object": {"sha": "abc"}})

    repo.get_branch_sha("class-photo/my class #2")

    assert urlparse(adapter.last_request.url).path == (
        "/repos/asmbly-makerspace/asmbly-classes/git/ref/heads/class-photo/my%20class%20%232"
    )


# --- writes ---


def test_create_blob_tree_commit_shapes(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    blobs = requests_mock.post(f"{REPO_API}/git/blobs", status_code=201, json={"sha": "blob1"})
    trees = requests_mock.post(f"{REPO_API}/git/trees", status_code=201, json={"sha": "tree1"})
    commits = requests_mock.post(f"{REPO_API}/git/commits", status_code=201, json={"sha": "commit1"})
    entries = [
        {"path": "app/src/lib/images/Woodshop Safety.jpg", "mode": "100644", "type": "blob", "sha": "blob1"},
        {"path": "app/src/lib/images/woodshop-safety.png", "mode": "100644", "type": "blob", "sha": None},
    ]

    assert repo.create_blob("aGVsbG8=") == "blob1"
    assert repo.create_tree("base0", entries) == "tree1"
    assert repo.create_commit("Update photo", "tree1", "parent0") == "commit1"

    assert blobs.last_request.json() == {"content": "aGVsbG8=", "encoding": "base64"}
    assert trees.last_request.json() == {"base_tree": "base0", "tree": entries}
    assert '"sha": null' in trees.last_request.text
    assert commits.last_request.json() == {"message": "Update photo", "tree": "tree1", "parents": ["parent0"]}


def test_create_and_update_branch_shapes(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    create = requests_mock.post(f"{REPO_API}/git/refs", status_code=201, json={"ref": f"refs/heads/{BRANCH}"})
    update = requests_mock.patch(f"{REPO_API}/git/refs/heads/{BRANCH}", json={"ref": f"refs/heads/{BRANCH}"})

    repo.create_branch(BRANCH, "commit1")
    repo.update_branch(BRANCH, "commit2", force=True)

    assert create.last_request.json() == {"ref": f"refs/heads/{BRANCH}", "sha": "commit1"}
    assert update.last_request.json() == {"sha": "commit2", "force": True}


def test_update_branch_non_fast_forward_raises_conflict(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.patch(
        f"{REPO_API}/git/refs/heads/{BRANCH}", status_code=422, json={"message": "Update is not a fast forward"}
    )

    with pytest.raises(GitHubConflict) as excinfo:
        repo.update_branch(BRANCH, "commit2", force=False)
    assert excinfo.value.status == 422
    assert excinfo.value.operation == "update_branch"


@pytest.mark.parametrize(
    "branch",
    ["main", "class-photo/", "class-photo/../main", "refs/heads/class-photo/x", "class-phot"],
)
def test_write_outside_prefix_is_refused(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo, branch: str
) -> None:
    with pytest.raises(ValueError):
        repo.create_branch(branch, "commit1")
    with pytest.raises(ValueError):
        repo.update_branch(branch, "commit1", force=True)
    assert requests_mock.call_count == 0


@pytest.mark.parametrize("prefix", ["", "m", "class-photo"])
def test_prefix_without_trailing_slash_is_refused(prefix: str) -> None:
    with pytest.raises(ValueError):
        GitHubRepo(TOKEN, "asmbly-makerspace", "asmbly-classes", prefix)


@pytest.mark.parametrize(
    "operation, method, path",
    [
        ("create_blob", "post", "git/blobs"),
        ("create_tree", "post", "git/trees"),
        ("create_commit", "post", "git/commits"),
        ("update_pull_request", "patch", "pulls/12"),
    ],
)
@pytest.mark.parametrize("status", [409, 422])
def test_other_operations_conflict_status_is_plain_error(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo, operation: str, method: str, path: str, status: int
) -> None:
    getattr(requests_mock, method)(f"{REPO_API}/{path}", status_code=status, json={"message": "Invalid"})
    calls = {
        "create_blob": lambda: repo.create_blob("aGVsbG8="),
        "create_tree": lambda: repo.create_tree("base0", []),
        "create_commit": lambda: repo.create_commit("m", "tree1", "parent0"),
        "update_pull_request": lambda: repo.update_pull_request(12, "t", "b"),
    }

    with pytest.raises(GitHubError) as excinfo:
        calls[operation]()
    assert type(excinfo.value) is GitHubError
    assert excinfo.value.status == status
    assert excinfo.value.operation == operation


def test_client_has_no_merge_or_delete_method() -> None:
    names = [name.lower() for name in dir(GitHubRepo) if not name.startswith("_")]
    assert not [name for name in names if "merge" in name or "delete" in name]


# --- pull requests ---


def test_find_open_pull_request_uses_head_and_base(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    adapter = requests_mock.get(
        f"{REPO_API}/pulls",
        json=[{"number": 12, "html_url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/12", "x": 1}],
    )

    found = repo.find_open_pull_request(BRANCH, "main")

    assert found == {"number": 12, "html_url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/12"}
    assert parse_qs(urlparse(adapter.last_request.url).query) == {
        "state": ["open"],
        "head": ["asmbly-makerspace:class-photo/x-1234abcd"],
        "base": ["main"],
    }


def test_find_open_pull_request_none(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    requests_mock.get(f"{REPO_API}/pulls", json=[])
    assert repo.find_open_pull_request(BRANCH, "main") is None


def test_create_pull_request_shape(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    adapter = requests_mock.post(
        f"{REPO_API}/pulls",
        status_code=201,
        json={"number": 13, "html_url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/13"},
    )

    created = repo.create_pull_request("Photo: Woodshop Safety", BRANCH, "main", "Requested by someone")

    assert created == {"number": 13, "html_url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/13"}
    assert adapter.last_request.json() == {
        "title": "Photo: Woodshop Safety",
        "head": BRANCH,
        "base": "main",
        "body": "Requested by someone",
        "maintainer_can_modify": False,
    }


def test_create_pull_request_existing_raises_conflict(
    requests_mock: requests_mock_module.Mocker, repo: GitHubRepo
) -> None:
    requests_mock.post(
        f"{REPO_API}/pulls", status_code=422, json={"message": "A pull request already exists", "x": BODY_MARKER}
    )

    with pytest.raises(GitHubConflict) as excinfo:
        repo.create_pull_request("t", BRANCH, "main", "b")
    assert excinfo.value.status == 422
    assert BODY_MARKER not in str(excinfo.value)


def test_update_pull_request_shape(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    adapter = requests_mock.patch(
        f"{REPO_API}/pulls/12",
        json={"number": 12, "html_url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/12"},
    )

    updated = repo.update_pull_request(12, "New title", "New body")

    assert updated["number"] == 12
    assert adapter.last_request.json() == {"title": "New title", "body": "New body"}


def test_conflict_status_409_is_conflict(requests_mock: requests_mock_module.Mocker, repo: GitHubRepo) -> None:
    requests_mock.post(f"{REPO_API}/git/refs", status_code=409, json={"message": "Git Repository is empty."})
    with pytest.raises(GitHubConflict):
        repo.create_branch(BRANCH, "commit1")


def test_no_log_line_carries_the_token_on_success(
    requests_mock: requests_mock_module.Mocker,
    key_pair: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    requests_mock.post(
        f"{API}/app/installations/{INSTALLATION_ID}/access_tokens", status_code=201, json={"token": TOKEN}
    )
    requests_mock.get(f"{REPO_API}/pulls", json=[])

    token = github_app.installation_token(APP_ID, INSTALLATION_ID, key_pair[0], "asmbly-classes", {"contents": "read"})
    GitHubRepo(token, "asmbly-makerspace", "asmbly-classes", PREFIX).find_open_pull_request(BRANCH, "main")

    sent_jwt = requests_mock.request_history[0].headers["Authorization"].split(" ", 1)[1]
    _assert_secret_free(caplog.text, [TOKEN, sent_jwt] + _key_lines(key_pair[0]))
