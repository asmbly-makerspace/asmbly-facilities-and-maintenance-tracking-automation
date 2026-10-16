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

> **Status:** [x] Complete — 2026-10-16 on branch claude/inspiring-bell-o4i5t9

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

- `layers/common/python/common/github_app.py`: `create_commit` takes an optional
  keyword `extra_parent: str | None = None`; when given, the commit's `parents` are
  `[parent_sha, extra_parent]` (a merge commit). Callers that don't pass it are unchanged.
- `layers/common/tests/test_github_app.py`: one test for the two-parent body.

## Implementation details

### Which commit the new commit sits on (prep amendment)

The tree is always built from the **current base** (`main`), and the description is
always computed from the base's images directory, so the pull request's diff and its
description say the same thing (#108 AC2), even after `main` has moved:

- **No open pull request** (new class, or the last one was merged or closed): one commit
  whose only parent is the base head. A new branch is created at it; a leftover branch is
  force-moved to it. A stale branch's old commits are never built on.
- **Open pull request**: one commit with **two parents**, `[branch head, base head]`, and
  the tree `base tree + photo − superseded images`. The branch moves to it without force
  (a fast-forward: the branch head is its first parent), so a second submission adds a
  commit and the pull request stays. Its second parent makes the pull request's merge
  base the current `main`, so the diff is exactly the photo and the removals, and images
  that reached `main` after the branch was made are removed too. When `main` hasn't
  moved (the two heads are equal, or the base head is already in the branch's history
  per `GitHubRepo.is_ancestor`, a read-only compare call made in `apply_submission`
  only), the commit has one parent: a plain fast-forward, no redundant merge.
- Consequence: a commit someone pushed by hand to a `class-photo/` branch is not carried
  into the next submission's tree (the pull request describes the latest submission).

Before this amendment the plan built on the branch head and listed images there, which
made the second submission's description say "Removed: none" and "replaced" while the
pull request removes files from and adds the photo to `main`.

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
        naming a missing or mistyped key (never the values): strings must be non-empty,
        image_extensions a non-empty list of strings."""

@dataclass(frozen=True)
class SubmissionPlan:
    class_name: str
    file_path: str                 # f"{images_dir}/{exact_file_name(class_name)}"
    replaces_existing: bool        # the file is in the base's images directory
    removed_paths: list[str]       # superseded images in the base's images directory
    branch: str
    branch_sha: str | None         # None when the branch doesn't exist
    base_sha: str
    open_pull_request: dict | None  # {"number", "html_url"}; None unless the branch exists
    title: str
    body: str
    warnings: list[str]            # plain text, for the page (collision_warning)

    branch_exists -> bool (property)

@dataclass(frozen=True)
class SubmissionResult:
    action: str                    # "opened" | "updated" | "would_open" | "would_update"
    pull_request: dict | None      # {"number", "html_url"}; None for "would_open"
    plan: SubmissionPlan

class SubmissionConflict(Exception):
    """Another submission for the same class moved the branch first."""

def pr_title(class_name: str) -> str                       # "Class photo: <class name>"
def pr_body(class_name, file_path, replaces_existing, removed_paths, collisions,
            requested_by: str) -> str
def commit_message(class_name: str, requested_by: str) -> str
def plan_submission(repo: GitHubRepo, config: RepoConfig, class_name: str,
                    all_classes: list[str], requested_by: str) -> SubmissionPlan
def apply_submission(repo: GitHubRepo, config: RepoConfig, plan: SubmissionPlan,
                     photo_base64: str, requested_by: str) -> SubmissionResult
def dry_run_result(plan: SubmissionPlan) -> SubmissionResult
```

`plan_submission` (read calls only):

1. `branch = branch_name(class_name, config.branch_prefix)`;
   `file_name = exact_file_name(class_name)`.
2. `base_sha = repo.get_branch_sha(config.base_branch)`; missing →
   `GitHubError("get_branch_sha", 404)`.
3. `branch_sha = repo.get_branch_sha(branch)`;
   `open_pr = repo.find_open_pull_request(branch, config.base_branch)` when `branch_sha`,
   else `None` (GitHub closes a pull request whose branch is deleted).
4. `names = repo.list_directory(config.images_dir, base_sha)`.
5. `replaces_existing = file_name in names`; `removed_paths` from
   `superseded_images(class_name, names, config.image_extensions)`, prefixed with
   `images_dir + "/"`.
6. `collisions = fuzzy_collisions(class_name, all_classes)`; `warnings`:
   `[collision_warning(class_name, collisions)]` when not `None`.
7. Title and body.

`pr_body` (Markdown). Every outside value (class name, file paths, username, the other
classes' names) goes in a code span, so nothing renders as markup, a link or an
`@mention`. A code span is fenced with one backtick more than the longest run of
backticks in the text (padded with a space when the text starts or ends with one), so a
backtick in a class name shows as itself and the path shown is the real path. Control
characters (newlines included) become spaces first, so text can't end the list item.
The collision warning is rebuilt here with the other classes in code spans; the plain
`collision_warning` text is for the page only.

```markdown
Class photo for `<class name>`, submitted from the class photo upload page.

- **File:** `app/src/lib/images/<file>.jpg` (added | replaced)
- **Removed:** `<path>`, `<path>` (other images the class list would match for this class) | none
- **Requested by** `<username>`

> **Warning:** Another class, `<other>`, matches the same photo on the class list. Both classes will show this photo there.   (only when there is one; the plural form for several)

The photo was checked before upload: JPEG, 3:2 landscape, 4 MB or less, no location data.
Merge to use it on classes.asmbly.org, or close this pull request to discard it.
Opened by the Asmbly class photo upload page; a new photo for this class updates this pull request.
```

`commit_message`: `"Class photo: <class name>\n\nRequested by <username>."` with control
characters in either value replaced by spaces.

`apply_submission` (prod):

1. `blob = repo.create_blob(photo_base64)`.
2. `tree = repo.create_tree(repo.get_commit_tree_sha(plan.base_sha), entries)` with the
   photo `{"path": plan.file_path, "mode": "100644", "type": "blob", "sha": blob}` and,
   for each removed path, `{"path": p, "mode": "100644", "type": "blob", "sha": None}`.
3. `commit = repo.create_commit(commit_message(...), tree, parent, extra_parent=...)`:
   open pull request → `parent = plan.branch_sha`, `extra_parent = plan.base_sha` (left
   out when equal or when `repo.is_ancestor(base_sha, branch_sha)`); otherwise `parent = plan.base_sha` and no extra parent.
4. Move the branch:
   - open pull request → `update_branch(branch, commit, force=False)`;
   - branch exists, no open pull request → `update_branch(branch, commit, force=True)`
     (the branch is reset onto the current base; an old merged or closed pull request is
     left alone, never reopened);
   - no branch → `create_branch(branch, commit)`.
   A `GitHubConflict` here → `SubmissionConflict` (a concurrent submission, or the branch
   was deleted or moved since the plan; in both cases trying again re-plans and works).
5. Pull request:
   - open → `update_pull_request(number, title, body)` → action `"updated"`;
   - none → `create_pull_request(title, branch, base, body)` → `"opened"`; on
     `GitHubConflict`, look again with `find_open_pull_request`; found → update it and
     answer `"updated"`; not found → re-raise.
6. Log `logger.info("Class photo %s: pull request %s on branch %s", action, number, branch)`
   (the class name may be logged too; never the username or the body).

Retrying after a failure part-way (for example after step 4, before step 5) is safe: the
next submission finds the branch without an open pull request, resets it, and opens one.

`dry_run_result`: `"would_update"` with the open pull request when there is one, else
`"would_open"` with `pull_request=None`. Makes no call.

## Tests

`tests/test_submission.py`, with `MagicMock(spec=GitHubRepo)` (from `common.github_app`)
and `class_names` real:

- `test_repo_config_from_dict_missing_key_names_it` (and a mistyped key).
- `test_plan_new_class_branch_from_base`: no PR, no branch → `list_directory` called
  with `images_dir` and the base SHA; `replaces_existing` false; `find_open_pull_request`
  not called.
- `test_plan_missing_base_branch_raises`.
- `test_plan_open_pr_lists_base_not_branch`: with an open PR, the listing is still the
  base's, and the description counts files relative to the base.
- `test_plan_removes_fuzzy_matches_only`: with names `["Tormach_Part_2__CNC_Milling.jpg",
  "Tormach_Part_2_CNC Milling.jpg", "Tormach_Part_2__CNC Milling.jpg", "NeonLogo.jpg"]`,
  "Tormach Part 2: CNC Milling" replaces the first and removes the next two.
- `test_plan_collision_warning_in_body_and_warnings`: other class names in code spans.
- `test_pr_body_contents`: has the class, file path, "added"/"replaced", each removed
  path, "Requested by `alice`"; no email-like or name field exists in the input.
- `test_pr_body_escapes_markup`: a class name with `` ` ``, `*`, `@team`, `<b>` and a
  newline is inside a code span whose fence is longer than any backtick run; the text
  outside code spans has no `@` and no `<`.
- `test_apply_new_class_creates_branch_and_pr`: call order blob → tree on the base tree
  (entries exact, deletes with `sha: None`) → commit (single parent = base SHA) →
  `create_branch` → `create_pull_request(title, branch, "main", body)`; action `"opened"`.
- `test_apply_repeat_updates_branch_and_pr`: open PR #12 → commit with parents branch
  head and base, `update_branch(force=False)`, `update_pull_request(12, …)`, no
  `create_pull_request`; action `"updated"`, number 12.
- `test_apply_repeat_when_heads_equal_has_one_parent`.
- `test_apply_after_closed_pr_resets_branch_and_opens_new_pr`: branch exists, no PR →
  `update_branch(force=True)` with a commit whose only parent is the base SHA,
  `create_pull_request` called.
- `test_apply_non_fast_forward_raises_submission_conflict` (and `create_branch`'s).
- `test_apply_pr_create_race_updates_existing`: `create_pull_request` raises
  `GitHubConflict`, the second lookup finds #13 → updated.
- `test_apply_pr_create_conflict_without_pr_reraises`.
- `test_apply_github_error_propagates`: `create_blob` raising `GitHubError` propagates
  and nothing after it is called.
- `test_dry_run_makes_no_write_calls`: `plan_submission` + `dry_run_result` call none of
  `create_blob`, `create_tree`, `create_commit`, `create_branch`, `update_branch`,
  `create_pull_request`, `update_pull_request`; action `"would_open"`, and
  `"would_update"` with #12 when a PR is open.
- `test_two_classes_two_branches`: different classes give different branches and
  separate `create_pull_request` calls.
- `layers/common/tests/test_github_app.py`: `test_create_commit_with_extra_parent`.

## Acceptance criteria

1. A new class's submission makes one commit, adding or replacing
   `app/src/lib/images/<exact name>.jpg` and deleting every superseded image, on its own
   branch from `main`, and opens one pull request against `main`. (#107 AC2, AC3, AC6)
2. The description has the class, the file and whether it is added or replaced, each
   removed file, "Requested by `<username>`" and any collision warning; nothing renders
   as a mention or markup. (#107 AC4, AC5)
3. A second submission with an open pull request adds a non-force commit to the same
   branch and updates that pull request; after a merged or closed one, the branch is
   reset onto `main` and a new pull request opens. The description always matches the
   pull request's diff against the current `main`. (#108 AC1, AC2, AC4, AC5)
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
- `common.github_app.GitHubRepo.create_commit(..., extra_parent=None)` and
  `GitHubRepo.is_ancestor(ancestor_sha, descendant_sha) -> bool` (GET `compare`,
  operation `compare_commits`, status `ahead` or `identical`; needs `contents: read`).
- `RepoConfig.from_dict` refuses a `base_branch` under `branch_prefix`.
- The read calls a dry run needs: `find_open_pull_request`, `get_branch_sha`,
  `list_directory` (so a token with `contents: read, pull_requests: read` is enough).
- `SubmissionPlan` fields phase 5 returns: `file_path`, `replaces_existing`,
  `removed_paths`, `title`, `body`, `warnings` (plain text, for `textContent`), plus
  `branch`, `branch_sha`, `base_sha`, `open_pull_request` and the `branch_exists`
  property. `SubmissionResult.pull_request` is `{"number", "html_url"}` (None for
  `would_open`).
- `plan_submission` raises `ValueError` for a class not in `all_classes` or one that
  `file_name_problem` refuses (phase 5 checks both first and answers 400, so this is a
  backstop), and `GitHubError("get_branch_sha", 404)` when the base branch is missing.
- `apply_submission` raises `SubmissionConflict` (→ 409) when `create_branch` or
  `update_branch` conflicts, and lets `GitHubError` (→ 502) through, including a
  `GitHubConflict` from `create_pull_request` when no open pull request is found on the
  second look. Phase 5 catches `SubmissionConflict` before `GitHubError` (they are
  unrelated classes, so the order only matters for readability).
- `submission.py` imports `class_names` relatively with a top-level fallback, so it
  loads both under pytest and as a top-level module beside `lambda_function.py`
  (`test_module_imports_as_top_level_module`). Phase 5's handler can use the same
  pattern.
- `pr_title` and `commit_message` put the class name and username in plain text (control
  characters as spaces); only the description renders Markdown.
- Known limits, not handled: when two submissions for a class whose branch exists
  without an open pull request run at the same moment, both force-move the branch; the
  last move wins, and in one interleaving the pull request's description is the other
  submission's. A commit pushed by hand to a `class-photo/` branch is not carried into
  the next submission (README Decision 27). In the title and commit message (plain
  text), `#` and `@` before a word character get a space after them (`Fixes # 3`,
  `@ user`), so GitHub links, mentions or closes nothing; the description keeps the
  exact name in a code span.
