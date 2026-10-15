# Offshore briefing: <plan name>

**Date:** <YYYY-MM-DD>
**Branch:** `feature/<plan-name>`
**Pull request:** #<N> to `stage`, **green, waiting for your review and merge**
**Epic:** #<N> (or "none")
**Phases completed:** <N> of <total>

> **Next steps for you, in order:**
> 1. Do the admin actions below that say "before merge".
> 2. Review pull request #<N> and merge it. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` against the stage stack.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod).
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

| When | Action | Why |
| --- | --- | --- |
| Before merge | <e.g. redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` with the new names in `template-cicd.yaml` (docs/Deploying.md, "How to Manage the Deployer Role")> | <the stage deploy fails without it> |
| Before merge | <e.g. create secret `<name>` in Secrets Manager with keys `<KEY>`> | <the function reads it at start> |
| After the stage deploy | <e.g. point the ClickUp webhook for <list> at the stage URL to test, then back> | <QA step N> |
| After the prod deploy | <e.g. set the Slack app's slash command URL to https://facilities.asmbly.org/<path>> | <go live> |

Write "None" if there are none.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | <Xh Ym> |
| Subagent retries | <N> |
| Transient errors retried | <N> |
| Environment problems | <e.g. "sam missing: sam validate and sam build not run", or "none"> |

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| 1 | <title> | Done | `<sha>` | 1 | <m> |
| 2 | <title> | Blocked: <one line> | — | — | <m> |

## Decisions made

- **<topic>:** chose <X> over <Y> because <reason>. See `<path>:<line>`.

## Plan changes

- **Phase <N>:** <what changed in the plan during the run, and why>. Write "None" if none.

## Deferrals and blockers

- **<item>:** <one or two sentences>. Options: (a) ... (b) ... Recommendation: <a|b>.

Write "None" if there are none.

## Skipped because of the environment

- <check>: <why>. Write "None" if nothing was skipped.

## Integration gate

- pytest: <N passed>
- cfn-lint: <clean | findings, and whether they were already on stage>
- sam validate: <pass | fail | skipped: reason>
- sam build: <pass | fail | skipped: reason>
- Cross-checks (environment variables, deploy role names, nested parameters, routes): <clean | what was fixed>

## Review

- Review rounds inside phases: <N>; findings fixed: <N>; deferred: <N>.
- Pull request rounds: <N>; comments answered: <N>.

## Rollback

Each phase is one commit, and so is each review round:

```bash
git log --oneline origin/stage..feature/<plan-name>
git revert <sha>   # undoes one phase or one review round
```

## Action items

- [ ] The admin actions above
- [ ] Review pull request #<N>, especially <the riskiest file and lines>
- [ ] Run `MANUAL_QA.md` on the stage stack
- [ ] Decide on <deferral>, see above

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
