"""What a class photo submission does on asmbly-classes, and doing it.

``plan_submission`` makes read calls only, so a dry run (stage) needs a token with
``contents: read, pull_requests: read``. ``apply_submission`` makes one commit on the
class's own branch and opens or updates that branch's pull request. Nothing here
merges, touches the base branch, or force-moves a branch that has an open pull request.

The commit's tree is always the current base's tree plus the photo minus the superseded
images, and the description is computed from the base's images directory, so the pull
request's diff and description agree even after the base has moved. With an open pull
request the commit's first parent is the branch head, so the branch moves forward without
force; when the base has moved since the branch last took it, the base head is a second
parent, so the pull request's merge base becomes the current base.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from common.github_app import GitHubConflict, GitHubError, GitHubRepo

try:
    from . import class_names
except ImportError:  # Under Lambda this module is top-level, beside class_names.py.
    import class_names  # type: ignore[no-redef]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ACTION_OPENED = "opened"
ACTION_UPDATED = "updated"
ACTION_WOULD_OPEN = "would_open"
ACTION_WOULD_UPDATE = "would_update"

FILE_MODE = "100644"

_CONTROL_CHARACTERS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_BACKTICK_RUN_PATTERN = re.compile(r"`+")
_REFERENCE_PATTERN = re.compile(r"([#@])(?=\w)")

_STRING_KEYS = {
    "repo_owner": "owner",
    "repo_name": "repo",
    "base_branch": "base_branch",
    "images_dir": "images_dir",
    "branch_prefix": "branch_prefix",
}


@dataclass(frozen=True)
class RepoConfig:
    """Where the photos go: the JSON of configs/class_photo_upload.json."""

    owner: str
    repo: str
    base_branch: str
    images_dir: str
    branch_prefix: str
    image_extensions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoConfig":
        """Reads repo_owner, repo_name, base_branch, images_dir, branch_prefix and
        image_extensions. Raises ValueError naming a missing or mistyped key, never a value.
        """
        if not isinstance(data, dict):
            raise ValueError("class photo configuration must be a JSON object")
        values: dict[str, Any] = {}
        for key, field_name in _STRING_KEYS.items():
            value = data.get(key)
            if not isinstance(value, str) or not value.strip("/ "):
                raise ValueError(f"class photo configuration key {key} is missing or not a string")
            values[field_name] = value
        if not values["branch_prefix"].endswith("/"):
            raise ValueError("class photo configuration key branch_prefix must end with '/'")
        if values["base_branch"].startswith(values["branch_prefix"]):
            raise ValueError("class photo configuration key base_branch must not be under branch_prefix")
        values["images_dir"] = values["images_dir"].strip("/")
        extensions = data.get("image_extensions")
        if (
            not isinstance(extensions, list)
            or not extensions
            or not all(isinstance(e, str) and e for e in extensions)
        ):
            raise ValueError(
                "class photo configuration key image_extensions is missing or not a list of strings"
            )
        values["image_extensions"] = list(extensions)
        return cls(**values)


@dataclass(frozen=True)
class SubmissionPlan:
    """What a submission adds, removes and opens, relative to the current base."""

    class_name: str
    file_path: str
    replaces_existing: bool
    removed_paths: list[str]
    branch: str
    branch_sha: str | None
    base_sha: str
    open_pull_request: dict[str, Any] | None
    title: str
    body: str
    warnings: list[str]

    @property
    def branch_exists(self) -> bool:
        return self.branch_sha is not None


@dataclass(frozen=True)
class SubmissionResult:
    """``action`` is opened, updated, would_open or would_update."""

    action: str
    pull_request: dict[str, Any] | None
    plan: SubmissionPlan


class SubmissionConflict(Exception):
    """Another submission for the same class moved the branch first."""


def _single_line(text: str) -> str:
    """Control characters (line breaks included) as spaces."""
    return _CONTROL_CHARACTERS_PATTERN.sub(" ", text)


def _no_references(text: str) -> str:
    """Plain text that GitHub won't turn into a link: ``#3`` and ``@user`` gain a space.

    For the title and the commit message, which aren't Markdown; a commit message such
    as "Fixes #3" would otherwise close issue 3 once merged.
    """
    return _REFERENCE_PATTERN.sub(r"\1 ", _single_line(text))


def code_span(text: str) -> str:
    """``text`` as a Markdown code span that shows it literally.

    The fence is one backtick longer than the longest run of backticks in the text, and
    the text is padded with a space where CommonMark would otherwise misread or strip it.
    Inside a code span GitHub renders no markup, link, ``@mention`` or ``#reference``.
    """
    text = _single_line(text)
    if not text:
        return "` `"
    longest = max((len(run) for run in _BACKTICK_RUN_PATTERN.findall(text)), default=0)
    fence = "`" * (longest + 1)
    if (
        text.startswith("`")
        or text.endswith("`")
        or (text.startswith(" ") and text.endswith(" ") and text.strip(" "))
    ):
        text = f" {text} "
    return f"{fence}{text}{fence}"


def pr_title(class_name: str) -> str:
    """The pull request's title."""
    return f"Class photo: {_no_references(class_name)}"


def collision_markdown(others: list[str]) -> str | None:
    """The collision warning for the description, with the other classes in code spans."""
    if not others:
        return None
    names = ", ".join(code_span(other) for other in others)
    if len(others) == 1:
        return (
            f"Another class, {names}, matches the same photo on the class list. "
            "Both classes will show this photo there."
        )
    return (
        f"Other classes, {names}, match the same photo on the class list. "
        "All of these classes will show this photo there."
    )


def pr_body(
    class_name: str,
    file_path: str,
    replaces_existing: bool,
    removed_paths: list[str],
    collisions: list[str],
    requested_by: str,
) -> str:
    """The pull request's description. Every outside value is in a code span."""
    change = "replaced" if replaces_existing else "added"
    if removed_paths:
        removed = (
            ", ".join(code_span(path) for path in removed_paths)
            + " (other images the class list would match for this class)"
        )
    else:
        removed = "none"
    lines = [
        f"Class photo for {code_span(class_name)}, submitted from the class photo upload page.",
        "",
        f"- **File:** {code_span(file_path)} ({change})",
        f"- **Removed:** {removed}",
        f"- **Requested by** {code_span(requested_by)}",
        "",
    ]
    warning = collision_markdown(collisions)
    if warning is not None:
        lines += [f"> **Warning:** {warning}", ""]
    lines += [
        "The photo was checked before upload: JPEG, 3:2 landscape, 4 MB or less, no location data.",
        "Merge to use it on classes.asmbly.org, or close this pull request to discard it.",
        "Opened by the Asmbly class photo upload page; "
        "a new photo for this class updates this pull request.",
    ]
    return "\n".join(lines) + "\n"


def commit_message(class_name: str, requested_by: str) -> str:
    """The commit's message; each commit names its requester."""
    return f"Class photo: {_no_references(class_name)}\n\nRequested by {_no_references(requested_by)}."


def plan_submission(
    repo: GitHubRepo,
    config: RepoConfig,
    class_name: str,
    all_classes: list[str],
    requested_by: str,
) -> SubmissionPlan:
    """Works out the submission with read calls only.

    Raises ValueError for a class that isn't in ``all_classes`` or can't be a file name
    (the caller checks both first; this keeps a bad name out of any path), and
    GitHubError when a read fails or the base branch doesn't exist.
    """
    if class_name not in all_classes:
        raise ValueError("class is not in the class list")
    if class_names.file_name_problem(class_name) is not None:
        raise ValueError("class name can't be a file name")

    branch = class_names.branch_name(class_name, config.branch_prefix)
    file_name = class_names.exact_file_name(class_name)

    base_sha = repo.get_branch_sha(config.base_branch)
    if base_sha is None:
        logger.error("Class photo base branch %s does not exist", config.base_branch)
        raise GitHubError("get_branch_sha", 404)
    branch_sha = repo.get_branch_sha(branch)
    # GitHub closes a pull request whose branch is deleted, so look only when it exists.
    open_pr = repo.find_open_pull_request(branch, config.base_branch) if branch_sha else None

    names = repo.list_directory(config.images_dir, base_sha)
    replaces_existing = file_name in names
    removed_paths = [
        f"{config.images_dir}/{name}"
        for name in class_names.superseded_images(class_name, names, config.image_extensions)
    ]
    file_path = f"{config.images_dir}/{file_name}"

    collisions = class_names.fuzzy_collisions(class_name, all_classes)
    warning = class_names.collision_warning(class_name, collisions)

    return SubmissionPlan(
        class_name=class_name,
        file_path=file_path,
        replaces_existing=replaces_existing,
        removed_paths=removed_paths,
        branch=branch,
        branch_sha=branch_sha,
        base_sha=base_sha,
        open_pull_request=open_pr,
        title=pr_title(class_name),
        body=pr_body(class_name, file_path, replaces_existing, removed_paths, collisions, requested_by),
        warnings=[warning] if warning is not None else [],
    )


def _move_branch(repo: GitHubRepo, plan: SubmissionPlan, commit: str) -> None:
    """Points the class's branch at ``commit``; a lost race is a SubmissionConflict."""
    try:
        if plan.open_pull_request is not None:
            repo.update_branch(plan.branch, commit, force=False)
        elif plan.branch_exists:
            # No open pull request: reset the leftover branch onto the current base.
            repo.update_branch(plan.branch, commit, force=True)
        else:
            repo.create_branch(plan.branch, commit)
    except GitHubConflict:
        logger.warning("Class photo branch %s moved since the plan", plan.branch)
        raise SubmissionConflict("the class's branch changed during the submission") from None


def apply_submission(
    repo: GitHubRepo,
    config: RepoConfig,
    plan: SubmissionPlan,
    photo_base64: str,
    requested_by: str,
) -> SubmissionResult:
    """Commits the photo on the class's branch and opens or updates its pull request.

    Raises SubmissionConflict when another submission moved the branch first, and
    GitHubError when a call fails. Trying again after either re-plans and finishes
    without opening a second pull request.
    """
    blob = repo.create_blob(photo_base64)
    entries: list[dict[str, Any]] = [
        {"path": plan.file_path, "mode": FILE_MODE, "type": "blob", "sha": blob}
    ]
    entries += [
        {"path": path, "mode": FILE_MODE, "type": "blob", "sha": None} for path in plan.removed_paths
    ]
    tree = repo.create_tree(repo.get_commit_tree_sha(plan.base_sha), entries)

    message = commit_message(plan.class_name, requested_by)
    if plan.open_pull_request is not None and plan.branch_sha is not None:
        # Merge the base in only when it has moved since the branch last took it.
        base_merged = plan.base_sha == plan.branch_sha or repo.is_ancestor(plan.base_sha, plan.branch_sha)
        extra_parent = None if base_merged else plan.base_sha
        commit = repo.create_commit(message, tree, plan.branch_sha, extra_parent=extra_parent)
    else:
        commit = repo.create_commit(message, tree, plan.base_sha)

    _move_branch(repo, plan, commit)

    if plan.open_pull_request is not None:
        pull_request = repo.update_pull_request(plan.open_pull_request["number"], plan.title, plan.body)
        action = ACTION_UPDATED
    else:
        try:
            pull_request = repo.create_pull_request(plan.title, plan.branch, config.base_branch, plan.body)
            action = ACTION_OPENED
        except GitHubConflict:
            existing = repo.find_open_pull_request(plan.branch, config.base_branch)
            if existing is None:
                raise
            pull_request = repo.update_pull_request(existing["number"], plan.title, plan.body)
            action = ACTION_UPDATED

    logger.info(
        "Class photo %s: pull request %s on branch %s", action, pull_request["number"], plan.branch
    )
    return SubmissionResult(action=action, pull_request=pull_request, plan=plan)


def dry_run_result(plan: SubmissionPlan) -> SubmissionResult:
    """What apply_submission would answer, without any call."""
    if plan.open_pull_request is not None:
        return SubmissionResult(action=ACTION_WOULD_UPDATE, pull_request=plan.open_pull_request, plan=plan)
    return SubmissionResult(action=ACTION_WOULD_OPEN, pull_request=None, plan=plan)
