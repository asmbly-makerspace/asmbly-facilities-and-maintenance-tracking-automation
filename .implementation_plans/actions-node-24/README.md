---
plan: actions-node-24
epic: 126
---

# Actions on Node 24: implementation plan

**Created:** 2026-10-17

## Overview

Every workflow run warns that some of its actions target Node.js 20, which GitHub has
deprecated and is forcing onto Node.js 24
([GitHub changelog](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/)).
They still work, but they will stop when GitHub removes Node 20 from its runners.

Current state on `stage` (`76f94c3`):

| Workflow | Job | Action | Now | Target |
| --- | --- | --- | --- | --- |
| `python-tests.yml` | `test` | `actions/checkout` | `v3` | `v7` |
| `python-tests.yml` | `test` | `actions/setup-python` | `v3` | `v7` |
| `deploy-staging.yml`, `deploy.yml` | `deploy` | `actions/checkout` | `v4` | `v7` |
| `deploy-staging.yml`, `deploy.yml` | `deploy` | `aws-actions/configure-aws-credentials` | `v4` | `v6` |
| `deploy-staging.yml`, `deploy.yml` | `deploy` | `aws-actions/setup-sam` | `v2` | `v3` |
| `deploy-staging.yml`, `deploy.yml` | `list-routes` | `actions/checkout`, `actions/setup-python` | `v7` | already current |

This plan bumps the five stale references (eight `uses:` lines in three files), adds a
pytest guard that fails if a workflow uses an action older than the first Node 24 major,
and keeps every deploy job's OIDC sign-in exactly as it is. One phase.

The spec is #124's body. Where this plan adds detail, it is under **Decisions**.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #124 | ci: update GitHub Actions that still run on Node.js 20 | 1 |

The pull request that lands phase 1 says `Refs #124`, not `Closes #124`: two of #124's
criteria (the post-merge stage deploy and the next prod deploy) can only be checked after
the merge, so the issue is closed by hand once they pass (Decision 5).

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Bump the workflow actions to their Node 24 majors](phase-1-bump-actions.md) | ci | S | [x] Complete |

## Dependencies

**Outside this plan**

- None to build it. The target majors are already proven in this repository: the
  `list-routes` jobs (added in #123 and #125) run `actions/checkout@v7` and
  `actions/setup-python@v7` on every deploy.
- Verification after the merge depends on the next push to `stage` (the Deploy Staging
  Pipeline) and the next `/promote` (the Deploy Production Pipeline).

**Between phases**

| Phase | depends_on | Why |
| --- | --- | --- |
| 1 | — | |

## Parallelism

One phase; nothing to run in parallel.

Outside the plan: branch `chore/dependabot` adds `.github/dependabot.yml`,
`tests/test_dependabot.py` and a note in `docs/CONTRIBUTING.md`. This plan touches none
of those files, so the two can be built and merged in either order. PR #68 edits
`python-tests.yml` (see Related work).

## Admin actions

None. The deploy role (`template-cicd.yaml`, `GitHub-OIDC-facilities-automation-deploy`)
trusts the subjects `repo:asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation:environment:stage`
and `...:environment:prod` with audience `sts.amazonaws.com`. The action version doesn't
change either: the job's `environment:` name sets the subject, and
`configure-aws-credentials@v6` still requests the `sts.amazonaws.com` audience by
default. No named AWS resource is added, so nothing goes into the deploy-role policies.

## Related work

- **#124** (story): the spec, with the version table and acceptance criteria.
- **PR #68** (`epowell/lint-templates`, base `main`, conflicting): adds a `lint-templates`
  job to `python-tests.yml` with `actions/checkout@v3`, `actions/setup-python@v3` and
  `aws-actions/setup-sam@v2`. If it merges after this plan, it brings Node 20 actions
  back, and this plan's new test (`tests/test_workflows.py`) fails on it. It must be
  rebased onto the new majors first. This plan does not edit #68's job.
- **Branch `chore/dependabot`**: once Dependabot watches the `github-actions` ecosystem
  it opens these bumps itself. The test here checks a minimum major, so later Dependabot
  bumps keep passing.
- **Ubuntu 26**: GitHub moves `ubuntu-latest` to Ubuntu 26 from 2026-10-19. Not in scope,
  but the first runs after that date are the first test of `setup-python` (Python 3.12)
  and `sam build --use-container` on it; the post-merge checks in phase 1 note it.

## Out of scope

- Pinning actions by commit SHA. They stay pinned by major tag, as the `list-routes` jobs
  are (Decision 3).
- Pinning the SAM CLI version that `setup-sam` installs (neither v2 nor v3 pins one today).
- Moving off `ubuntu-latest`.
- Adding `persist-credentials: false` to the `test` and `deploy` jobs' checkouts (the
  `list-routes` jobs have it; adding it elsewhere is a separate hardening change).
- Dependabot configuration, and PR #68's job.
- Any template, Lambda, layer or `configs/` change.

## Security

- **OIDC trust unchanged.** Each deploy job keeps `environment: name: stage` / `prod`,
  `permissions: id-token: write` and `contents: read`, the same `role-to-assume` ARN, and
  only the `role-to-assume` and `aws-region` inputs. Phase 1's test asserts the
  environment, the permissions, the inputs and the role name (the ARN's
  `:role/GitHub-OIDC-facilities-automation-deploy` suffix; the `git diff` acceptance check
  covers the full ARN), so a later edit that drops the environment or adds a credentials
  input fails `pytest`.
- **No new permissions.** No job gains a permission; `list-routes` keeps
  `contents: read` only and no OIDC token.
- **Third-party code.** The bumps move to newer releases of the same four actions
  (GitHub's `actions/*` and AWS's `aws-actions/*`); no new action is introduced. The
  release notes between the current and target majors were read while planning (see
  phase 1, "Release notes"); the builder re-reads them in case a release landed since.

## Decisions

Made without asking, in an unattended `/offshore` run.

1. **#124 is the story; epic #126 wraps it.** `/plan-product` wants an epic with stories
   that have acceptance criteria. #124 already had criteria and a version table, so it was
   labeled `story`, given a `## Story` sentence, a priority line, two new criteria (the
   deploy jobs' sign-in stays the same; no promote after a failed stage deploy) and
   sharper wording on three (the runs' annotations are checked; the prod Deployments page
   and route list), and attached to a new epic #126 that only
   wraps it. Alternative: a new story copying #124's content. Rejected: two issues saying
   the same thing drift apart.
2. **One phase.** Eight `uses:` lines in three files and one small test file. Splitting
   `python-tests.yml` from the deploy workflows would give two phases of under 30 lines.
3. **Pin by major tag (`@v7`), not SHA.** Matches the `list-routes` jobs and the rest of
   the repository. SHA pinning is a separate decision for the maintainer, listed in Out
   of scope.
4. **Add a pytest guard (`tests/test_workflows.py`).** No existing test reads
   `.github/workflows/`, so without one, criterion 1 of #124 ("no workflow uses a Node 20
   action") and the "sign-in unchanged" criterion are checked only by reading. The test
   checks a *minimum* major per action, so Dependabot's later bumps still pass, and it
   fails on an action it doesn't know, so a new action gets a deliberate look. Alternative:
   rely on `actionlint` alone. Rejected: `actionlint` isn't installed in CI or in
   `requirements-dev.txt`, and version 1.7.12 flags only the `v3` actions (Node 16), not
   the `v4`/`v2` ones that target Node 20.
5. **`Refs #124`, not `Closes #124`.** Two of #124's criteria are about runs that happen
   after the merge (stage) and after `/promote` (prod). Closing on merge would close the
   story before those are checked. The issue is closed by hand once the stage and prod
   runs pass; `MANUAL_QA.md` lists the steps.
6. **`docs/Deploying.md` is not changed.** It describes the pipeline's jobs and the OIDC
   role but names no action or version, and nothing it says changes. The phase still
   checks this before finishing.
7. **No `with:` changes.** The release notes show no renamed or removed input that these
   workflows use (`role-to-assume`, `aws-region`, `python-version`), so every step keeps
   its inputs exactly. The one v6 feature that touches the sign-in, more default
   session tags (v6.2.0), doesn't apply to OIDC: the action drops session tags before
   `AssumeRoleWithWebIdentity`, so the trust policy needs no `sts:TagSession`.
