---
phase_id: 1
title: Bump the workflow actions to their Node 24 majors
epic: 126
implements: [124]
depends_on: []
domain: [ci]
estimated_size: S
---

# Phase 1: Bump the workflow actions to their Node 24 majors

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`, and this plan's README (Decisions 3, 4, 5, 7; Security).
- #124's body: the version table and its six acceptance criteria.
- `.github/workflows/python-tests.yml` (the `test` job, the required check on `stage`
  and `main`; don't rename it).
- `.github/workflows/deploy-staging.yml` and `.github/workflows/deploy.yml`: the `deploy`
  job and the `list-routes` job, which already uses
  `actions/checkout@v7` and `actions/setup-python@v7`. The `list-routes` job is the
  closest example of the target form.
- `template-cicd.yaml`, `GitHubOidcDeployRole` (lines 55–71): the trust policy allows
  `sts:AssumeRoleWithWebIdentity` only, for audience `sts.amazonaws.com` and the subjects
  `repo:<org>/<repo>:environment:stage` and `:environment:prod`.
- `docs/Deploying.md`, "CI/CD Infrastructure" and "The Deployment Pipeline": to confirm
  nothing in them changes (they name no action or version today).
- `tests/test_api_routes.py`: the style for a repository-level test in `tests/` (a
  `REPO` path constant, typed test functions, PyYAML already in `requirements-dev.txt`).

## Goal

No workflow in `.github/workflows/` uses an action that targets Node.js 20. The `test`
check runs on `actions/checkout@v7` and `actions/setup-python@v7` and shows no Node.js 20
annotation. Both deploy jobs run `actions/checkout@v7`,
`aws-actions/configure-aws-credentials@v6` and `aws-actions/setup-sam@v3`, with their
environments, permissions, role and inputs unchanged. A new pytest file fails if any of
that regresses.

## Files to create

| Path | What |
| --- | --- |
| `tests/test_workflows.py` | The guard: every `uses:` in every workflow meets a minimum Node 24 major; the deploy jobs keep their OIDC sign-in (see Tests). |

## Files to modify

| Path | Line(s) on `stage` `76f94c3` | Change |
| --- | --- | --- |
| `.github/workflows/python-tests.yml` | 17 | `actions/checkout@v3` → `actions/checkout@v7` |
| `.github/workflows/python-tests.yml` | 20 | `actions/setup-python@v3` → `actions/setup-python@v7` |
| `.github/workflows/deploy-staging.yml` | 31 | `actions/checkout@v4` → `actions/checkout@v7` |
| `.github/workflows/deploy-staging.yml` | 34 | `aws-actions/configure-aws-credentials@v4` → `@v6` |
| `.github/workflows/deploy-staging.yml` | 40 | `aws-actions/setup-sam@v2` → `@v3` |
| `.github/workflows/deploy.yml` | 31 | `actions/checkout@v4` → `actions/checkout@v7` |
| `.github/workflows/deploy.yml` | 34 | `aws-actions/configure-aws-credentials@v4` → `@v6` |
| `.github/workflows/deploy.yml` | 40 | `aws-actions/setup-sam@v2` → `@v3` |

Only the `@vN` suffix changes on each line. No `with:` input, step name, job name,
`environment:`, `permissions:` or trigger changes. The `list-routes` jobs are not
touched.

Not modified: `docs/Deploying.md` (Decision 6; re-check it names no version before
finishing), `template-cicd.yaml`, any template, `.github/dependabot.yml`,
`tests/test_dependabot.py` and `docs/CONTRIBUTING.md` (those belong to branch
`chore/dependabot`).

## Implementation details

### ci

**Step 1: re-read the release notes.** Before editing, list the releases between the
current and target majors and look for breaking changes and input renames that affect
the inputs these workflows use (`role-to-assume`, `aws-region`, `python-version`; none
for checkout and setup-sam):

```bash
gh api "repos/actions/checkout/releases?per_page=50" --jq '.[] | .tag_name + " " + .published_at'
gh api "repos/actions/setup-python/releases?per_page=50" --jq '.[] | .tag_name + " " + .published_at'
gh api "repos/aws-actions/configure-aws-credentials/releases?per_page=60" --jq '.[] | .tag_name + " " + .published_at'
gh api "repos/aws-actions/setup-sam/releases" --jq '.[] | .tag_name + " " + .published_at'
gh api repos/<owner>/<repo>/releases/tags/<tag> --jq .body   # for each major and any release that mentions BREAKING
```

What the planner found on 2026-10-17 (confirm nothing newer contradicts it, and
record any difference in the hand-off):

| Action | Majors crossed | Breaking changes | Effect here |
| --- | --- | --- | --- |
| `actions/checkout` | v3 → v4 → v5 → v6 → v7 (v7.0.1 latest) | v4: Node 20. v5: Node 24, runner ≥ v2.327.1. v6: persisted credentials move to a separate file. v7: ESM build; refuses to check out a fork's pull request under `pull_request_target` / `workflow_run`. | None. GitHub-hosted runners are newer than v2.327.1; no workflow runs git commands with the persisted token or uses `pull_request_target` / `workflow_run`. |
| `actions/setup-python` | v3 → v7 (v7.0.0) | v4: `python-version` (or a version file) required. v5: Node 20. v6: Node 24. v7: ESM build, removed the `pip-install` input. | None. `python-version: '3.12'` is set; `pip-install` is not used. |
| `aws-actions/configure-aws-credentials` | v4 → v5 → v6 (v6.3.0 latest) | v5: stricter input handling (an invalid boolean input now fails). v6: Node 24, runner ≥ v2.327.1. v6.2.0 (feature): more default session tags, `role-session-name` regex validation, more retries. | None. Only `role-to-assume` and `aws-region` are passed (no boolean inputs). The default `audience` is still `sts.amazonaws.com` (`action.yml`). On the OIDC path `assumeRoleWithOIDC()` drops all session tags before `AssumeRoleWithWebIdentity` (`src/assumeRole.ts` at v6.3.0, line 10), so the trust policy needs no `sts:TagSession`. The default session name (`GitHubActions`) passes the new regex. |
| `aws-actions/setup-sam` | v2 → v3 | v3: Node 24 only. | None. No inputs are passed; both majors install the latest SAM CLI. |

If a newer release adds a breaking change that does affect these inputs, stop and record
it as a finding rather than adding inputs: Decision 7 says no `with:` changes.

**Step 2: edit the eight lines** in the table above, nothing else.

**Step 3: write `tests/test_workflows.py`** (see Tests).

Permissions after the change, unchanged from `stage`:

| Workflow | Job | `permissions` | `environment` |
| --- | --- | --- | --- |
| `python-tests.yml` | `test` | (repository default) | none |
| `deploy-staging.yml` | `deploy` | `id-token: write`, `contents: read` | `stage` |
| `deploy-staging.yml` | `list-routes` | `contents: read` | none |
| `deploy.yml` | `deploy` | `id-token: write`, `contents: read` | `prod` |
| `deploy.yml` | `list-routes` | `contents: read` | none |

Required checks: `test` keeps its job name, so the branch protection on `stage` and
`main` still matches it.

## Tests

`tests/test_workflows.py`, reading every `*.yml` under `.github/workflows/` with
`yaml.safe_load`. Type hints on every function; no network.

A module constant maps each action to the first major that runs on Node 24:

```python
MIN_NODE24_MAJOR: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "aws-actions/configure-aws-credentials": 6,
    "aws-actions/setup-sam": 3,
}
```

(Minimum, not exact: a later Dependabot bump to `@v8` still passes. The workflows pin
the current majors, which are above these minimums.)

| Test | Proves |
| --- | --- |
| `test_every_action_runs_on_node_24` | Every step's `uses:` in every workflow (parametrized by workflow file) names an action in `MIN_NODE24_MAJOR`, is pinned as `@v<N>` (or `@v<N>.<x>...`), and has a major ≥ its minimum. An action missing from the map fails with a message saying to check its runtime and add it. #124 criterion 1. |
| `test_workflows_are_found` | The glob finds `python-tests.yml`, `deploy-staging.yml` and `deploy.yml`, so the parametrized test can't pass by finding nothing. |
| `test_deploy_jobs_keep_their_oidc_sign_in` | Parametrized over (`deploy-staging.yml`, `stage`) and (`deploy.yml`, `prod`): the `deploy` job's `environment.name` is the stage name; its `permissions` are exactly `{"id-token": "write", "contents": "read"}`; it has exactly one `aws-actions/configure-aws-credentials` step, whose `with:` keys are exactly `{"role-to-assume", "aws-region"}` and whose `role-to-assume` ends in `:role/GitHub-OIDC-facilities-automation-deploy`. #124 criterion 3. |
| `test_list_routes_jobs_have_no_oidc_token` | Each `list-routes` job's `permissions` are exactly `{"contents": "read"}` and it has no `environment`. Keeps #125's split from regressing while these files are edited. |

Sanity check while building: the test fails on `stage`'s workflows (before the edits)
with the five stale references named in its messages, and passes after them.

## Acceptance criteria

- [ ] `grep -rn "uses:" .github/workflows/` shows only `actions/checkout@v7`,
      `actions/setup-python@v7`, `aws-actions/configure-aws-credentials@v6` and
      `aws-actions/setup-sam@v3`. (#124 AC 1)
- [ ] `tests/test_workflows.py` fails against `stage`'s workflows and passes against the
      branch's; `.venv/bin/python -m pytest` passes in full. (#124 AC 1, 3)
- [ ] The `deploy` jobs' `environment:` names (`stage`, `prod`), `permissions`,
      `role-to-assume` and `aws-region` are byte-for-byte unchanged from `stage`
      (`git diff stage -- .github/workflows/` shows only `@vN` changes). (#124 AC 3)
- [ ] `actionlint` reports nothing for the three workflows (on `stage` it reports the two
      `v3` actions in `python-tests.yml`).
- [ ] The pull request's `test` check passes, and its run's annotations contain no
      "Node.js 20" warning. (#124 AC 2)
- [ ] `docs/Deploying.md` still says nothing that the change makes untrue.

#124 AC 4, 5 and 6 (the stage deploy after the merge, the next prod deploy, no promote
after a failed stage deploy) are checked after the merge; see Verification and
`MANUAL_QA.md`.

## Verification

Before the pull request:

```bash
.venv/bin/python -m pytest
/private/tmp/claude-501/-Users-robertszabo-Git-asmbly-facilities-and-maintenance-tracking-automation/6d786a3a-4aba-431a-80f8-3295a7ac6811/scratchpad/lintenv/bin/actionlint
git diff stage -- .github/workflows/      # only @vN changes
```

`actionlint` is a single binary in the session's scratchpad, not in `.venv`. If it is
gone, install it into the scratchpad (download the release binary) and say which version
ran; it is not a repository dependency. `cfn-lint`, `sam validate` and `sam build` don't
apply: no template, layer or requirements change.

On the pull request (it is exercised by the PR's `test` check):

```bash
gh pr checks <pr> --watch
JOB=$(gh pr checks <pr> --json name,link --jq '.[] | select(.name=="test") | .link' | sed 's#.*/job/##')
gh api repos/{owner}/{repo}/check-runs/$JOB/annotations --jq '.[] | .annotation_level + ": " + .message'
```

Pass: the check is green and no annotation mentions `Node.js 20`. (Before this change it
lists `actions/checkout@v3, actions/setup-python@v3`.)

After the merge to `stage` (the deploy workflows can't run on a pull request):

1. Watch the **Deploy Staging Pipeline** run for the merge commit
   (`gh run list --workflow deploy-staging.yml --branch stage --limit 1`, then
   `gh run watch <id>`). Pass: both jobs succeed; the **Configure AWS Credentials** step
   logs the assumed role; `sam build --use-container` and `sam deploy` complete.
2. Its annotations (`gh api repos/{owner}/{repo}/check-runs/<deploy job id>/annotations`)
   contain no `Node.js 20` warning.
3. The repository's **Deployments** page shows the stage `execute-api` URL for the
   `stage` environment, and the run summary has the **List API routes** table.
4. If the run fails, don't `/promote`: open a `fix/` pull request (or revert) first.
   GitHub moves `ubuntu-latest` to Ubuntu 26 from 2026-10-19, so a failure in
   `setup-python` or `sam build --use-container` on a run after that date may be the
   runner image, not this change; compare with a re-run of the previous successful run.

After the next `/promote`: the **Deploy Production Pipeline** run succeeds with no
`Node.js 20` annotation, the Deployments page shows `https://facilities.asmbly.org` for
`prod`, and the summary lists the routes. Then close #124 by hand (README Decision 5).

## Admin actions

None. The deploy role's trust is by GitHub environment subject and audience, neither of
which changes, and no named AWS resource is added.

## Hand-off

(Filled in when the phase is done.)
