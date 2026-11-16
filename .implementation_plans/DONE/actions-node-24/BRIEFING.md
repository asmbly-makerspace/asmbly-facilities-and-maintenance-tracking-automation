# Offshore briefing: actions-node-24

**Date:** 2026-10-17
**Branch:** `feature/actions-node-24`
**Pull request:** #128 to `stage`, **green, waiting for your review and merge**
**Epic:** #126 (wraps story #124)
**Phases completed:** 1 of 1

> **Next steps for you, in order:**
> 1. Do the admin actions below that say "before merge". (There are none.)
> 2. Review pull request #128 and merge it. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` against the stage stack.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod).
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

None. The deploy role trusts the GitHub environment subject (`environment:stage`, `environment:prod`) and the `sts.amazonaws.com` audience; neither changes, and no named AWS resource is added.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 30 minutes (11:58 to 12:28 Central) |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. `sam` 1.166.2, Python 3.12 and `gh` were all available. |

The run paused its own guardrail once, on your instruction: you told the session twice to merge PR #127 (the Dependabot config, a separate request), which the guardrail blocks during a run. The sentinel was moved aside for that one `gh pr merge`, with no subagent running, and restored straight after. #127 merged as `05f2a8a`, and this branch was rebased onto it. This run's own pull request, #128, was not merged.

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| 1 | Bump the workflow actions to their Node 24 majors | Done | `a576726` | 1 (clean) | 9 min |

## Decisions made

- **#124 is the story, epic #126 wraps it:** chose to reuse #124 (now labeled `story`, with two added criteria) over a new story that copies it, because two issues saying the same thing drift apart. See `.implementation_plans/actions-node-24/README.md:130`.
- **One phase:** eight `uses:` lines in three files and one test file; two phases would each be under 30 lines. See `README.md:138`.
- **Pin by major tag (`@v7`), not SHA:** matches the rest of the repository; SHA pinning is left for you to decide (Out of scope). See `README.md:140`.
- **Add `tests/test_workflows.py`:** without it, "no workflow uses a Node 20 action" and "sign-in unchanged" are checked only by reading; `actionlint` isn't in CI and flags only the `v3` actions. The test checks a *minimum* major per action, so Dependabot's later bumps still pass. See `README.md:143`.
- **`Refs #124`, not `Closes #124`:** two criteria are about the stage run after the merge and the prod run after `/promote`, so close #124 by hand once those pass. See `README.md:151`.
- **No `with:` changes:** no input these workflows use was renamed or removed. configure-aws-credentials v6.2.0's extra session tags don't apply to OIDC, so the trust policy needs no `sts:TagSession`. See `README.md:158`.
- **The test also checks a scratch workflow:** an old major, a dotted tag, a SHA pin, an unknown action and a reusable workflow, so the guard can't pass vacuously.

## Plan changes

- **Decision 6 (docs/Deploying.md unchanged):** superseded by the docs step, which added one paragraph to "The Deployment Pipeline" explaining `tests/test_workflows.py` and what to do when adding an action (279 to 281 lines). No doc names action versions, so nothing else changed.

## Deferrals and blockers

- **PR #68 will fail the new test:** #68 (`epowell/lint-templates`, still open) adds a job whose actions predate Node 24, so `tests/test_workflows.py` fails on it until it is rebased onto `stage` and its actions bumped. Options: (a) tell #68's author when #128 merges; (b) bump #68's actions yourself. Recommendation: a.
- **`tests/test_workflows.py:111` raises `TypeError`, not an assertion message,** if a deploy job's `environment:` is ever rewritten to the string form. It still fails the test. Options: (a) add an `isinstance` assert (about 2 lines); (b) leave it. Recommendation: b.
- **Post-merge criteria:** #124's criteria for the stage deploy, the next prod deploy, and "no promote after a failed stage deploy" can only be checked after the merge. They are steps in `MANUAL_QA.md`.

## Skipped because of the environment

None.

## Integration gate

- pytest: 1721 passed at the gate; 1724 after the rebase onto `stage` with #127 (its 3 Dependabot tests)
- cfn-lint: 4 W3005 warnings in `template.yaml` (lines 582, 592, 605), the same on `stage`; this branch changes no template
- sam validate: pass
- sam build: pass
- actionlint: clean on all three workflows (on `stage` it flags the two `v3` actions)
- Cross-checks (environment variables, deploy role names, nested parameters, routes): clean; nothing to check, as no template, function or route changed. Only `@vN` suffixes change in the workflows; environment names, `role-to-assume`, `aws-region` and permissions are identical to `stage`.

## Review

- Review rounds inside phases: 1 (clean); findings fixed: 0; deferred: 1 (the `TypeError` note). The independent review-lead returned APPROVED with 0 BLOCK, 0 WARN, 5 NOTE.
- Pull request rounds: 0; comments answered: 0 (none yet). #124 criterion 2 is met on this PR: neither `test` run (push and pull_request) has a Node.js 20 annotation, only the Ubuntu 26 migration notice.

## Rollback

Each phase is one commit, and so is each review round:

```bash
git log --oneline origin/stage..feature/actions-node-24
git revert <sha>   # undoes one phase or one review round
```

## Action items

- [ ] Review pull request #128, especially the deploy jobs' `aws-actions/configure-aws-credentials@v6` line in `.github/workflows/deploy-staging.yml` and `.github/workflows/deploy.yml` (the only change that touches the AWS sign-in), and `tests/test_workflows.py`'s `MIN_NODE24_MAJOR` table
- [ ] Merge #128, then run `MANUAL_QA.md` on the stage stack
- [ ] After `/promote`, run the prod steps in `MANUAL_QA.md` and close #124 and epic #126 by hand
- [ ] Decide on PR #68, see above

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
