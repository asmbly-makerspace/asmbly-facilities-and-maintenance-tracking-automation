import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from common.github_app import GitHubConflict, GitHubError, GitHubRepo

from functions.classes.class_photo_upload_api import submission
from functions.classes.class_photo_upload_api.class_names import branch_name
from functions.classes.class_photo_upload_api.submission import (
    RepoConfig,
    SubmissionConflict,
    SubmissionPlan,
    apply_submission,
    code_span,
    commit_message,
    dry_run_result,
    plan_submission,
    pr_body,
    pr_title,
)

CONFIG_DICT: dict[str, Any] = {
    "repo_owner": "asmbly-makerspace",
    "repo_name": "asmbly-classes",
    "base_branch": "main",
    "images_dir": "app/src/lib/images",
    "branch_prefix": "class-photo/",
    "image_extensions": ["avif", "gif", "heif", "jpeg", "jpg", "png", "tiff", "webp"],
}
CONFIG = RepoConfig.from_dict(CONFIG_DICT)
IMAGES = "app/src/lib/images"
BASE_SHA = "base0"
BRANCH_SHA = "branch0"
TORMACH = "Tormach Part 2: CNC Milling"
TORMACH_NAMES = [
    "Tormach_Part_2__CNC_Milling.jpg",
    "Tormach_Part_2_CNC Milling.jpg",
    "Tormach_Part_2__CNC Milling.jpg",
    "NeonLogo.jpg",
]
WRITE_METHODS = [
    "create_blob",
    "create_tree",
    "create_commit",
    "create_branch",
    "update_branch",
    "create_pull_request",
    "update_pull_request",
]
PHOTO = "aGVsbG8="


def pr(number: int) -> dict[str, Any]:
    return {"number": number, "html_url": f"https://github.com/asmbly-makerspace/asmbly-classes/pull/{number}"}


def make_repo(
    *,
    base_sha: str | None = BASE_SHA,
    branch_sha: str | None = None,
    open_pr: dict[str, Any] | None = None,
    names: list[str] | None = None,
) -> MagicMock:
    repo = create_autospec(GitHubRepo, instance=True)
    repo.get_branch_sha.side_effect = lambda branch: base_sha if branch == "main" else branch_sha
    repo.find_open_pull_request.return_value = open_pr
    repo.list_directory.return_value = list(TORMACH_NAMES if names is None else names)
    repo.create_blob.return_value = "blob1"
    repo.get_commit_tree_sha.return_value = "basetree"
    repo.create_tree.return_value = "tree1"
    repo.create_commit.return_value = "commit1"
    repo.is_ancestor.return_value = False  # main moved since the branch last took it
    repo.create_pull_request.return_value = pr(7)
    repo.update_pull_request.side_effect = lambda number, title, body: pr(number)
    return repo


def make_plan(repo: MagicMock, class_name: str = TORMACH, classes: list[str] | None = None) -> SubmissionPlan:
    return plan_submission(repo, CONFIG, class_name, classes or [class_name], "alice")


def call_names(repo: MagicMock) -> list[str]:
    return [c[0] for c in repo.mock_calls]


def outside_code_spans(markdown: str) -> str:
    """The text of each line with its code spans removed."""
    return "\n".join(
        re.sub(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", "", line) for line in markdown.split("\n")
    )


# --- RepoConfig ---


def test_repo_config_from_dict_reads_every_key() -> None:
    assert CONFIG == RepoConfig(
        owner="asmbly-makerspace",
        repo="asmbly-classes",
        base_branch="main",
        images_dir="app/src/lib/images",
        branch_prefix="class-photo/",
        image_extensions=CONFIG_DICT["image_extensions"],
    )


def test_repo_config_from_dict_trims_slashes_from_images_dir() -> None:
    config = RepoConfig.from_dict({**CONFIG_DICT, "images_dir": "/app/src/lib/images/"})
    assert config.images_dir == "app/src/lib/images"


@pytest.mark.parametrize("key", list(CONFIG_DICT))
def test_repo_config_from_dict_missing_key_names_it(key: str) -> None:
    data = {k: v for k, v in CONFIG_DICT.items() if k != key}
    with pytest.raises(ValueError, match=key):
        RepoConfig.from_dict(data)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("repo_owner", 5),
        ("repo_name", ""),
        ("images_dir", "/"),
        ("image_extensions", "jpg"),
        ("image_extensions", []),
        ("image_extensions", ["jpg", 3]),
    ],
)
def test_repo_config_from_dict_mistyped_key_names_it_not_the_value(key: str, value: Any) -> None:
    with pytest.raises(ValueError, match=key) as error:
        RepoConfig.from_dict({**CONFIG_DICT, key: value})
    assert repr(value) not in str(error.value)


def test_repo_config_branch_prefix_must_end_with_slash() -> None:
    with pytest.raises(ValueError, match="branch_prefix"):
        RepoConfig.from_dict({**CONFIG_DICT, "branch_prefix": "class-photo"})


def test_repo_config_base_branch_under_branch_prefix_is_refused() -> None:
    with pytest.raises(ValueError, match="base_branch"):
        RepoConfig.from_dict({**CONFIG_DICT, "base_branch": "class-photo/main"})


def test_repo_config_not_an_object() -> None:
    with pytest.raises(ValueError):
        RepoConfig.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


# --- plan_submission ---


def test_plan_new_class_branch_from_base() -> None:
    repo = make_repo(names=["NeonLogo.jpg"])

    plan = make_plan(repo)

    repo.list_directory.assert_called_once_with(IMAGES, BASE_SHA)
    repo.find_open_pull_request.assert_not_called()
    assert plan.base_sha == BASE_SHA
    assert plan.branch_sha is None
    assert not plan.branch_exists
    assert plan.open_pull_request is None
    assert plan.branch == branch_name(TORMACH, "class-photo/")
    assert plan.file_path == f"{IMAGES}/Tormach_Part_2__CNC_Milling.jpg"
    assert plan.replaces_existing is False
    assert plan.removed_paths == []
    assert plan.title == "Class photo: Tormach Part 2: CNC Milling"
    assert plan.warnings == []
    for method in WRITE_METHODS:
        getattr(repo, method).assert_not_called()


def test_plan_missing_base_branch_raises() -> None:
    repo = make_repo(base_sha=None)

    with pytest.raises(GitHubError) as error:
        make_plan(repo)

    assert error.value.status == 404
    repo.list_directory.assert_not_called()


def test_plan_open_pr_lists_base_not_branch() -> None:
    # The branch's earlier commit already added the photo and removed the old images;
    # the description still counts them relative to main.
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=pr(12))

    plan = make_plan(repo)

    repo.find_open_pull_request.assert_called_once_with(plan.branch, "main")
    repo.list_directory.assert_called_once_with(IMAGES, BASE_SHA)
    assert plan.branch_sha == BRANCH_SHA
    assert plan.open_pull_request == pr(12)
    assert plan.replaces_existing is True
    assert plan.removed_paths == [
        f"{IMAGES}/Tormach_Part_2_CNC Milling.jpg",
        f"{IMAGES}/Tormach_Part_2__CNC Milling.jpg",
    ]
    assert "Tormach_Part_2_CNC Milling.jpg" in plan.body


def test_plan_branch_without_pr() -> None:
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=None)

    plan = make_plan(repo)

    assert plan.branch_exists
    assert plan.open_pull_request is None
    repo.list_directory.assert_called_once_with(IMAGES, BASE_SHA)


def test_plan_removes_fuzzy_matches_only() -> None:
    plan = make_plan(make_repo(names=TORMACH_NAMES))

    assert plan.replaces_existing is True
    assert plan.removed_paths == [
        f"{IMAGES}/Tormach_Part_2_CNC Milling.jpg",
        f"{IMAGES}/Tormach_Part_2__CNC Milling.jpg",
    ]
    assert "NeonLogo" not in plan.body


def test_plan_collision_warning_in_body_and_warnings() -> None:
    classes = [TORMACH, "Tormach Part 2 - CNC Milling", "Woodshop Safety"]

    plan = make_plan(make_repo(), TORMACH, classes)

    assert plan.warnings == [
        'Another class, "Tormach Part 2 - CNC Milling", matches the same photo on the class list. '
        "Both classes will show this photo there."
    ]
    assert (
        "> **Warning:** Another class, `Tormach Part 2 - CNC Milling`, matches the same photo"
        in plan.body
    )


def test_plan_several_collisions_use_plural_warning() -> None:
    classes = [TORMACH, "Tormach Part 2 - CNC Milling", "Tormach_Part_2 CNC Milling"]

    plan = make_plan(make_repo(), TORMACH, classes)

    assert "> **Warning:** Other classes, `Tormach Part 2 - CNC Milling`, `Tormach_Part_2 CNC Milling`, match" in plan.body


def test_plan_refuses_class_not_in_list() -> None:
    repo = make_repo()

    with pytest.raises(ValueError):
        plan_submission(repo, CONFIG, "Not A Class", [TORMACH], "alice")

    repo.get_branch_sha.assert_not_called()


@pytest.mark.parametrize("bad", ["../../.github/workflows/x", "A\\B", "Line\nbreak", "   "])
def test_plan_refuses_name_that_cannot_be_a_file_name(bad: str) -> None:
    repo = make_repo()

    with pytest.raises(ValueError):
        plan_submission(repo, CONFIG, bad, [bad], "alice")

    repo.get_branch_sha.assert_not_called()


# --- the description ---


def test_pr_body_contents() -> None:
    body = pr_body(
        TORMACH,
        f"{IMAGES}/Tormach_Part_2__CNC_Milling.jpg",
        True,
        [f"{IMAGES}/Tormach_Part_2_CNC Milling.jpg", f"{IMAGES}/Tormach_Part_2__CNC Milling.jpg"],
        [],
        "alice",
    )

    assert body.startswith("Class photo for `Tormach Part 2: CNC Milling`, submitted from")
    assert f"- **File:** `{IMAGES}/Tormach_Part_2__CNC_Milling.jpg` (replaced)" in body
    assert (
        f"- **Removed:** `{IMAGES}/Tormach_Part_2_CNC Milling.jpg`, "
        f"`{IMAGES}/Tormach_Part_2__CNC Milling.jpg` (other images" in body
    )
    assert "- **Requested by** `alice`" in body
    assert "Warning" not in body
    assert "Merge to use it on classes.asmbly.org" in body


def test_pr_body_added_and_nothing_removed() -> None:
    body = pr_body("Woodshop Safety", f"{IMAGES}/Woodshop_Safety.jpg", False, [], [], "bob")

    assert f"- **File:** `{IMAGES}/Woodshop_Safety.jpg` (added)" in body
    assert "- **Removed:** none" in body
    assert "- **Requested by** `bob`" in body


def test_pr_body_escapes_markup() -> None:
    nasty = "Weird `x` ``y`` *bold* @team <b>#12</b>\nnext"
    body = pr_body(nasty, f"{IMAGES}/Weird_`x`.jpg", False, [], ["@other *x*"], "@alice`")

    text = outside_code_spans(body)
    assert "@" not in text
    assert "<" not in text
    assert "*bold*" not in text
    assert "#12" not in text
    # The longest backtick run in the name is 2, so its fence is 3; the newline is a space.
    assert "```Weird `x` ``y`` *bold* @team <b>#12</b> next```" in body
    # The file path is shown as it is, backticks included.
    assert f"``{IMAGES}/Weird_`x`.jpg``" in body
    assert "`` @alice` ``" in body
    assert "\nnext" not in body


@pytest.mark.parametrize(
    ("text", "span"),
    [
        ("plain", "`plain`"),
        ("a`b", "``a`b``"),
        ("a``b`c", "```a``b`c```"),
        ("`x", "`` `x ``"),
        ("x`", "`` x` ``"),
        (" both ", "`  both  `"),
        ("", "` `"),
        ("tab\there", "`tab here`"),
    ],
)
def test_code_span(text: str, span: str) -> None:
    assert code_span(text) == span


def test_title_and_commit_message_neutralize_github_references() -> None:
    assert pr_title("Bike Fixes #3 with @user") == "Class photo: Bike Fixes # 3 with @ user"
    assert commit_message("Bike Fixes #3", "@alice") == "Class photo: Bike Fixes # 3\n\nRequested by @ alice."
    assert commit_message("C# & F#: Basics", "bob") == "Class photo: C# & F#: Basics\n\nRequested by bob."
    # The description keeps the exact name, inside a code span.
    body = pr_body("Bike Fixes #3", f"{IMAGES}/Bike_Fixes_#3.jpg", False, [], [], "alice")
    assert "`Bike Fixes #3`" in body
    assert "#3" not in outside_code_spans(body)


def test_title_and_commit_message_are_single_line() -> None:
    assert pr_title("A\nB") == "Class photo: A B"
    assert commit_message("Woodshop Safety", "alice") == "Class photo: Woodshop Safety\n\nRequested by alice."
    assert commit_message("A\rB", "al\nice") == "Class photo: A B\n\nRequested by al ice."


# --- apply_submission ---


def test_apply_new_class_creates_branch_and_pr(caplog: pytest.LogCaptureFixture) -> None:
    repo = make_repo(names=TORMACH_NAMES)
    plan = make_plan(repo)
    repo.reset_mock()

    with caplog.at_level(logging.INFO):
        result = apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    assert call_names(repo) == [
        "create_blob",
        "get_commit_tree_sha",
        "create_tree",
        "create_commit",
        "create_branch",
        "create_pull_request",
    ]
    repo.create_blob.assert_called_once_with(PHOTO)
    repo.get_commit_tree_sha.assert_called_once_with(BASE_SHA)
    repo.create_tree.assert_called_once_with(
        "basetree",
        [
            {"path": f"{IMAGES}/Tormach_Part_2__CNC_Milling.jpg", "mode": "100644", "type": "blob", "sha": "blob1"},
            {"path": f"{IMAGES}/Tormach_Part_2_CNC Milling.jpg", "mode": "100644", "type": "blob", "sha": None},
            {"path": f"{IMAGES}/Tormach_Part_2__CNC Milling.jpg", "mode": "100644", "type": "blob", "sha": None},
        ],
    )
    repo.create_commit.assert_called_once_with(
        "Class photo: Tormach Part 2: CNC Milling\n\nRequested by alice.", "tree1", BASE_SHA
    )
    repo.create_branch.assert_called_once_with(plan.branch, "commit1")
    repo.create_pull_request.assert_called_once_with(plan.title, plan.branch, "main", plan.body)
    assert result.action == "opened"
    assert result.pull_request == pr(7)
    repo.is_ancestor.assert_not_called()
    assert result.plan is plan
    assert "alice" not in caplog.text
    assert f"pull request 7 on branch {plan.branch}" in caplog.text


def test_apply_repeat_updates_branch_and_pr() -> None:
    # main moved since the branch was made: the commit merges it in.
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=pr(12))
    plan = make_plan(repo)

    result = apply_submission(repo, CONFIG, plan, PHOTO, "bob")

    repo.is_ancestor.assert_called_once_with(BASE_SHA, BRANCH_SHA)
    repo.get_commit_tree_sha.assert_called_once_with(BASE_SHA)
    repo.create_commit.assert_called_once_with(
        "Class photo: Tormach Part 2: CNC Milling\n\nRequested by bob.",
        "tree1",
        BRANCH_SHA,
        extra_parent=BASE_SHA,
    )
    repo.update_branch.assert_called_once_with(plan.branch, "commit1", force=False)
    repo.update_pull_request.assert_called_once_with(12, plan.title, plan.body)
    repo.create_branch.assert_not_called()
    repo.create_pull_request.assert_not_called()
    assert result.action == "updated"
    assert result.pull_request == pr(12)


def test_apply_repeat_when_main_unchanged_has_one_parent() -> None:
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=pr(12))
    repo.is_ancestor.return_value = True
    plan = make_plan(repo)

    result = apply_submission(repo, CONFIG, plan, PHOTO, "bob")

    repo.is_ancestor.assert_called_once_with(BASE_SHA, BRANCH_SHA)
    repo.create_commit.assert_called_once_with(
        "Class photo: Tormach Part 2: CNC Milling\n\nRequested by bob.", "tree1", BRANCH_SHA, extra_parent=None
    )
    repo.update_branch.assert_called_once_with(plan.branch, "commit1", force=False)
    assert result.action == "updated"


def test_apply_repeat_when_heads_equal_has_one_parent() -> None:
    repo = make_repo(branch_sha=BASE_SHA, open_pr=pr(12))
    plan = make_plan(repo)

    apply_submission(repo, CONFIG, plan, PHOTO, "bob")

    repo.create_commit.assert_called_once_with(
        "Class photo: Tormach Part 2: CNC Milling\n\nRequested by bob.", "tree1", BASE_SHA, extra_parent=None
    )
    repo.is_ancestor.assert_not_called()
    repo.update_branch.assert_called_once_with(plan.branch, "commit1", force=False)


def test_apply_after_closed_pr_resets_branch_and_opens_new_pr() -> None:
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=None)
    plan = make_plan(repo)

    result = apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    repo.create_commit.assert_called_once_with(
        "Class photo: Tormach Part 2: CNC Milling\n\nRequested by alice.", "tree1", BASE_SHA
    )
    repo.update_branch.assert_called_once_with(plan.branch, "commit1", force=True)
    repo.create_branch.assert_not_called()
    repo.create_pull_request.assert_called_once_with(plan.title, plan.branch, "main", plan.body)
    repo.update_pull_request.assert_not_called()
    assert result.action == "opened"


def test_apply_non_fast_forward_raises_submission_conflict() -> None:
    repo = make_repo(branch_sha=BRANCH_SHA, open_pr=pr(12))
    repo.update_branch.side_effect = GitHubConflict("update_branch", 422)
    plan = make_plan(repo)

    with pytest.raises(SubmissionConflict) as error:
        apply_submission(repo, CONFIG, plan, PHOTO, "bob")

    assert error.value.__cause__ is None
    repo.update_pull_request.assert_not_called()
    repo.create_pull_request.assert_not_called()


def test_apply_branch_created_by_someone_else_raises_submission_conflict() -> None:
    repo = make_repo()
    repo.create_branch.side_effect = GitHubConflict("create_branch", 422)
    plan = make_plan(repo)

    with pytest.raises(SubmissionConflict):
        apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    repo.create_pull_request.assert_not_called()


def test_apply_pr_create_race_updates_existing() -> None:
    repo = make_repo()
    plan = make_plan(repo)
    repo.create_pull_request.side_effect = GitHubConflict("create_pull_request", 422)
    repo.find_open_pull_request.return_value = pr(13)

    result = apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    repo.find_open_pull_request.assert_called_once_with(plan.branch, "main")
    repo.update_pull_request.assert_called_once_with(13, plan.title, plan.body)
    assert result.action == "updated"
    assert result.pull_request == pr(13)


def test_apply_pr_create_conflict_without_pr_reraises() -> None:
    repo = make_repo()
    plan = make_plan(repo)
    repo.create_pull_request.side_effect = GitHubConflict("create_pull_request", 422)
    repo.find_open_pull_request.return_value = None

    with pytest.raises(GitHubConflict):
        apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    repo.update_pull_request.assert_not_called()


def test_apply_github_error_propagates() -> None:
    repo = make_repo()
    plan = make_plan(repo)
    repo.reset_mock()
    repo.create_blob.side_effect = GitHubError("create_blob", 502)

    with pytest.raises(GitHubError):
        apply_submission(repo, CONFIG, plan, PHOTO, "alice")

    assert call_names(repo) == ["create_blob"]


def test_retry_after_partial_failure_opens_one_pull_request() -> None:
    # First try: the branch is created, then opening the pull request fails.
    repo = make_repo()
    first = make_plan(repo)
    repo.create_pull_request.side_effect = GitHubError("create_pull_request", 502)
    with pytest.raises(GitHubError):
        apply_submission(repo, CONFIG, first, PHOTO, "alice")

    # Second try: the branch exists with no pull request, so it is reset and one opens.
    retry_repo = make_repo(branch_sha="commit1", open_pr=None)
    second = make_plan(retry_repo)
    result = apply_submission(retry_repo, CONFIG, second, PHOTO, "alice")

    retry_repo.update_branch.assert_called_once_with(second.branch, "commit1", force=True)
    retry_repo.create_pull_request.assert_called_once()
    assert result.action == "opened"


def test_two_classes_two_branches() -> None:
    repo = make_repo(names=[])
    classes = [TORMACH, "Woodshop Safety"]
    first = plan_submission(repo, CONFIG, TORMACH, classes, "alice")
    second = plan_submission(repo, CONFIG, "Woodshop Safety", classes, "alice")

    apply_submission(repo, CONFIG, first, PHOTO, "alice")
    apply_submission(repo, CONFIG, second, PHOTO, "alice")

    assert first.branch != second.branch
    assert [c.args[1] for c in repo.create_branch.call_args_list] == ["commit1", "commit1"]
    assert [c.args[0] for c in repo.create_branch.call_args_list] == [first.branch, second.branch]
    assert [c.args[1] for c in repo.create_pull_request.call_args_list] == [first.branch, second.branch]


# --- dry run ---


@pytest.mark.parametrize(
    ("branch_sha", "open_pr", "action", "pull_request"),
    [
        (None, None, "would_open", None),
        (BRANCH_SHA, None, "would_open", None),
        (BRANCH_SHA, pr(12), "would_update", pr(12)),
    ],
)
def test_dry_run_makes_no_write_calls(
    branch_sha: str | None, open_pr: dict[str, Any] | None, action: str, pull_request: dict[str, Any] | None
) -> None:
    repo = make_repo(branch_sha=branch_sha, open_pr=open_pr)

    plan = make_plan(repo)
    result = dry_run_result(plan)

    for method in WRITE_METHODS + ["get_commit_tree_sha"]:
        getattr(repo, method).assert_not_called()
    assert set(call_names(repo)) <= {"get_branch_sha", "find_open_pull_request", "list_directory"}
    assert result.action == action
    assert result.pull_request == pull_request
    assert result.plan is plan


# --- loading the way Lambda does ---


def test_module_imports_as_top_level_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under Lambda the function's folder is on the path and there is no parent package."""
    folder = Path(submission.__file__).parent
    monkeypatch.syspath_prepend(str(folder))
    names = ("submission", "class_names")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        module = importlib.import_module("submission")

        assert module.__name__ == "submission"
        assert module.class_names.__name__ == "class_names"
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
