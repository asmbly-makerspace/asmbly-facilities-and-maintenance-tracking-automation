---
phase_id: 4
title: Pull request flow and dry run
epic: 73
implements: [107, 108, 109]
depends_on: [1, 3]
domain: [lambda]
estimated_size: M
---

# Phase 4: Pull request flow and dry run

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; #73 sections "The file name" and "The pull request"; README Decisions
  14–17.
- Phase 1's hand-off (`class_names`) and phase 3's (`common.github_app`).
- `functions/classes/class_photo_upload_api/class_names.py` and
  `layers/common/python/common/github_app.py` as built.

## Goal

Given a chosen class, the photo, the requester's username and a `GitHubRepo`, the
server can (a) work out exactly what it would do: the file it adds or replaces, the
images it removes, the branch, whether a pull request is open for it, and the pull
request's title and description; and (b) do it: one commit on the class's branch and
an opened or updated pull request. In dry-run mode only (a) runs, and only read calls
are made. Pure orchestration over a mocked client; no route yet.

## Files to create

- `functions/classes/class_photo_upload_api/submission.py`.
- `functions/classes/class_photo_upload_api/tests/test_submission.py`.

## Files to modify

None.

## Implementation details

### lambda: `submission.py`

```python
@dataclass(frozen=True)
class RepoConfig:
    owner: str
    repo: str
    base_branch: str
    images_dir: str               # "app/src/lib/images"
    branch_prefix: str            # "class-photo/"
    image_extensions: list[str]   # ["avif", "gif", "heif", "jpeg", "jpg", "png", "tiff", "webp"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoConfig":
        """Reads the JSON keys of configs/class_photo_upload.json: repo_owner, repo_name,
        base_branch, images_dir, branch_prefix, image_extensions. Raises ValueError
        naming a missing key (never the values)."""

@dataclass(frozen=True)
class SubmissionPlan:
    class_name: str
    file_path: str                 # f"{images_dir}/{exact_file_name(class_name)}"
    replaces_existing: bool
    removed_paths: list[str]
    branch: str
    branch_exists: bool
    open_pull_request: dict | None  # {"number", "html_url"}
    parent_sha: str
    title: str
    body: str
    warnings: list[str]

@dataclass(frozen=True)
class SubmissionResult:
    action: str                    # "opened" | "updated" | "would_open" | "would_update"
    pull_request: dict | None      # {"number", "html_url"}; None for "would_open"
    plan: SubmissionPlan

class SubmissionConflict(Exception):
    """Another submission for the same class moved the branch first."""

def pr_title(class_name: str) -> str                       # "Class photo: <class name>"
def pr_body(plan_fields..., requested_by: str) -> str
def commit_message(class_name: str, file_path: str, requested_by: str) -> str
def plan_submission(repo: GitHubRepo, config: RepoConfig, class_name: str,
                    all_classes: list[str], requested_by: str) -> SubmissionPlan
def apply_submission(repo: GitHubRepo, config: RepoConfig, plan: SubmissionPlan,
                     photo_base64: str, requested_by: str) -> SubmissionResult
def dry_run_result(plan: SubmissionPlan) -> SubmissionResult
```

`plan_submission` (read calls only):

1. `branch = branch_name(class_name, config.branch_prefix)`;
   `file_name = exact_file_name(class_name)`.
2. `open_pr = repo.find_open_pull_request(branch, config.base_branch)`;
   `branch_sha = repo.get_branch_sha(branch)`.
3. `parent_sha = branch_sha` when `open_pr` and `branch_sha`; otherwise
   `repo.get_branch_sha(config.base_branch)` (missing → `GitHubError("base_branch", 404)`).
4. `names = repo.list_directory(config.images_dir, parent_sha)`.
5. `replaces_existing = file_name in names`; `removed_paths` from
   `superseded_images(class_name, names, config.image_extensions)`, prefixed with
   `images_dir + "/"`.
6. `warnings`: `collision_warning(class_name, fuzzy_collisions(class_name, all_classes))`
   when not `None`.
7. Title and body.

`pr_body` (Markdown). Class name and username go inside code spans with any backtick
replaced by `'`, so nothing renders as markup or `@mention`:

```markdown
Class photo for `<class name>`, submitted from the class photo upload page.

- **File:** `app/src/lib/images/<file>.jpg` (added | replaced)
- **Removed:** `<path>`, `<path>` (other images the class list would match for this class) | none
- **Requested by** `<username>`

> **Warning:** <collision warning>            (only when there is one)

The photo was checked before upload: JPEG, 3:2 landscape, 4 MB or less, no location data.
Merge to use it on classes.asmbly.org, or close this pull request to discard it.
Opened by the Asmbly class photo upload page; a new photo for this class updates this pull request.
```

`commit_message`: `"Class photo: <class name>\n\nRequested by <username>."`.

`apply_submission` (prod):

1. `blob = repo.create_blob(photo_base64)`.
2. `tree = repo.create_tree(repo.get_commit_tree_sha(plan.parent_sha), entries)` with the
   photo `{"path": plan.file_path, "mode": "100644", "type": "blob", "sha": blob}` and,
   for each removed path, `{"path": p, "mode": "100644", "type": "blob", "sha": None}`.
3. `commit = repo.create_commit(commit_message(...), tree, plan.parent_sha)`.
4. Move the branch:
   - open pull request and branch exists → `update_branch(branch, commit, force=False)`;
   - branch exists, no open pull request → `update_branch(branch, commit, force=True)`
     (the branch is reset onto the current base; an old merged or closed pull request is
     left alone, never reopened);
   - no branch → `create_branch(branch, commit)`.
   A `GitHubConflict` here → `SubmissionConflict`.
5. Pull request:
   - open → `update_pull_request(number, title, body)` → action `"updated"`;
   - none → `create_pull_request(title, branch, base, body)` → `"opened"`; on
     `GitHubConflict`, look again with `find_open_pull_request`; found → update it and
     answer `"updated"`; not found → re-raise.
6. Log `logger.info("Class photo %s: %s pull request %s on branch %s", action, ..., number, branch)`
   (class name, number and branch only).

Retrying after a failure part-way (for example after step 4, before step 5) is safe: the
next submission finds the branch without an open pull request, resets it, and opens one.

`dry_run_result`: `"would_update"` with the open pull request when there is one, else
`"would_open"` with `pull_request=None`. Makes no call.

## Tests

`tests/test_submission.py`, with `MagicMock(spec=GitHubRepo)` (from `common.github_app`)
and `class_names` real:

- `test_repo_config_from_dict_missing_key_names_it`.
- `test_plan_new_class_branch_from_base`: no PR, no branch → parent is the base SHA;
  `list_directory` called with `images_dir` and that SHA; `replaces_existing` false.
- `test_plan_open_pr_uses_branch_head`: parent is the branch SHA.
- `test_plan_branch_without_pr_uses_base`: a leftover branch is ignored for the parent.
- `test_plan_removes_fuzzy_matches_only`: with names `["Tormach_Part_2__CNC_Milling.jpg",
  "Tormach_Part_2_CNC Milling.jpg", "Tormach_Part_2__CNC Milling.jpg", "NeonLogo.jpg"]`,
  "Tormach Part 2: CNC Milling" replaces the first and removes the next two.
- `test_plan_collision_warning_in_body`.
- `test_pr_body_contents`: has the class, file path, "added"/"replaced", each removed
  path, "Requested by `alice`"; a class name with `` ` ``, `*` and `@team` renders inside
  a code span (backtick replaced); no email-like or name field exists in the input.
- `test_apply_new_class_creates_branch_and_pr`: call order blob → tree (entries exact,
  deletes with `sha: None`) → commit (parent = base SHA) → `create_branch` →
  `create_pull_request(title, branch, "main", body)`; action `"opened"`.
- `test_apply_repeat_updates_branch_and_pr`: open PR #12 → `update_branch(force=False)`,
  `update_pull_request(12, …)`, no `create_pull_request`; action `"updated"`, number 12.
- `test_apply_after_closed_pr_resets_branch_and_opens_new_pr`: branch exists, no PR →
  `update_branch(force=True)` with a commit whose parent is the base SHA,
  `create_pull_request` called.
- `test_apply_non_fast_forward_raises_submission_conflict`.
- `test_apply_pr_create_race_updates_existing`: `create_pull_request` raises
  `GitHubConflict`, the second lookup finds #13 → updated.
- `test_apply_github_error_propagates`: `create_blob` raising `GitHubError` propagates
  and nothing after it is called.
- `test_dry_run_makes_no_write_calls`: `plan_submission` + `dry_run_result` call none of
  `create_blob`, `create_tree`, `create_commit`, `create_branch`, `update_branch`,
  `create_pull_request`, `update_pull_request`; action `"would_open"`, and
  `"would_update"` with #12 when a PR is open.
- `test_two_classes_two_branches`: different classes give different branches and
  separate `create_pull_request` calls.

## Acceptance criteria

1. A new class's submission makes one commit, adding or replacing
   `app/src/lib/images/<exact name>.jpg` and deleting every superseded image, on its own
   branch from `main`, and opens one pull request against `main`. (#107 AC2, AC3, AC6)
2. The description has the class, the file and whether it is added or replaced, each
   removed file, "Requested by `<username>`" and any collision warning; nothing renders
   as a mention or markup. (#107 AC4, AC5)
3. A second submission with an open pull request adds a non-force commit to the same
   branch and updates that pull request; after a merged or closed one, the branch is
   reset onto `main` and a new pull request opens. (#108 AC1, AC2, AC4, AC5)
4. A retry after a failure part-way finishes without a second pull request. (#107 AC7)
5. The dry run reports the same plan and makes only read calls. (#109 AC2, AC3)
6. `.venv/bin/python -m pytest` passes.

## Verification

```bash
.venv/bin/python -m pytest functions/classes
.venv/bin/python -m pytest
```

No template change. Nothing to see on stage yet.

## Admin actions

None.

## Hand-off

- `functions.classes.class_photo_upload_api.submission`: `RepoConfig.from_dict`,
  `plan_submission`, `apply_submission`, `dry_run_result`, `SubmissionPlan`,
  `SubmissionResult` (`action` in `opened | updated | would_open | would_update`),
  `SubmissionConflict`.
- The read calls a dry run needs: `find_open_pull_request`, `get_branch_sha`,
  `list_directory` (so a token with `contents: read, pull_requests: read` is enough).
