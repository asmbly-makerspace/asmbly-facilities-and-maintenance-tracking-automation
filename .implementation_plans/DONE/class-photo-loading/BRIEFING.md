# Offshore briefing: class-photo-loading

**Date:** 2026-10-17
**Branch:** `feature/class-photo-loading`
**Pull request:** [#119](https://github.com/asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation/pull/119) to `stage`, **green**. The owner approved merging it once it is ready.
**Epic:** #114 (stories #116, #117, #118)
**Phases completed:** 3 of 3

> **Next steps, in order:**
> 1. Redeploy the deploy role (below). The owner asked Claude to do this just before the merge.
> 2. Merge #119. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` steps 1–20 on stage.
> 4. `/promote`, then run steps 21–24 on prod. After that, close #114 by hand.

---

## Admin actions

| When | Action | Why |
| --- | --- | --- |
| Before merge | Redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` (docs/Deploying.md). The first attempt failed and rolled back cleanly: IAM caps a managed policy at 6,144 characters, and the new names pushed both per-stage policies over that cap. Commit `3cdb4dd` splits each stage's policy into `GitHubDeployPolicy{stage,prod}` and a new `GitHubDeployPolicy{stage,prod}Data`. The `…Data` policies take the table (both stages) and the refresh rule (prod only); the granted permissions are identical before and after, and a test now checks every policy's size. | The stage deploy fails without it. |
| After the prod deploy | Check that `class-photo-class-list-refresh-prod` is ENABLED with `cron(0 10 * * ? *)`. The next day, `/asmbly/lambda/ClassPhotoUploadApiFunction-prod` should show `Scheduled class list refresh: done`. | Confirms the daily refresh. |
| After the prod deploy | Make one real submission and record the `Time left before the GitHub writes` figure from the prod log on #114, then close #114. | This is #114's last Done-when item. |

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 4 h |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. Node 20 (the default on ubuntu-latest) wasn't tested locally; CI ran the 27 page tests and they passed. |

## Phases

| Phase | Title | Status | Commit | Review rounds |
| --- | --- | --- | --- | --- |
| Plan | Implementation plan | Done | `571d05d` | — |
| 1 | Class-list cache, daily refresh and Neon timing | Done | `80d9a7f` | Build review + 3 cold rounds (1 BLOCK fixed) |
| 2 | Submit against the cache, time left and what was written | Done | `3922b18` | Build review + 2 cold rounds |
| 3 | Page busy state, refresh, progress and timeout messages | Done | `cc08f9e` | Build review + 3 cold rounds |
| Docs | Docs for class-photo-loading | Done | `74ed157` | — |
| QA | Manual QA steps | Done | `3a306d6` | — |

`f29ffd2` is #111's briefing. It wasn't written in time because #115 was merged before that run's briefing step.

## Decisions made

- **Owner: refresh once a day, on prod only.** It runs at `cron(0 10 * * ? *)`. The rule and its Lambda permission carry `Condition: IsProd`, and stage has no schedule.
- **Owner: a Refresh class list button.** It sends `GET /class-photo-upload/classes?refresh=1` on the existing Cognito-protected route. A 60 s guard returns the cached copy with `too_soon`. If Neon fails during a refresh, the old copy is served, marked stale.
- **Owner: a clean, decoupled design.** The design has a `ClassListCache` protocol with a frozen `ClassListRecord`, one DynamoDB implementation, a pure `FreshnessPolicy`, and a `ClassListService` that both the route and the schedule use. `lambda_function` is the composition root. Only `dynamodb_class_list_cache.py` imports boto3, and it creates its client lazily; a test enforces that.
- **Freshness.** A copy older than 26 h makes the next request read Neon live. When Neon is down, a copy of any age is served and the page marks it as possibly out of date.
- **Submit uses the cache.** With a warm cache, submit never waits on Neon. It still refuses an unknown class or a bad file name.
- **Two GitHub messages.** "Nothing was changed on GitHub" covers a failure before the writes and every failure on a dry run. "Submit the same class again" covers a failure during the writes.
- **Page.**
  - The busy indicator is a native `<progress>` element, because the token rule forbids animation values.
  - Busy controls use `aria-disabled`, because Chrome moves focus to `<body>` when a focused button is disabled.
  - Submit's 35 s limit starts when the upload ends.
- **DynamoDB client.** It uses 2 s timeouts and a single attempt (`total_max_attempts=1`), so an outage costs a request about 8 s at most.

## Plan changes

- **Owner changes after planning:** the refresh went from every 15 or 60 min to daily on prod only, the maximum age from 3 h to 26 h, and the Refresh button and the decoupled design were added. They are recorded as Decisions 19–22 and on #114, #116, #117 and #118.

## Deferrals and blockers

- **Retried refresh.** A scheduled refresh that times out is retried twice by Lambda. Stopping that needs `lambda:PutFunctionEventInvokeConfig` in the deploy role. Accepted.
- **Overwrite race.** The cache write is unconditional, so a slow live read can overwrite a newer manual refresh, by at most one read. Accepted.
- **Empty class list.** When Neon is empty and nothing is cached, the page shows an empty list with no message (existing behavior). Recommend a small follow-up issue.
- **Throttling wording.** A 429 on the class list shows the submit wording (existing behavior).
- **Sign out.** It stays usable during a submission (existing behavior).

## Skipped because of the environment

- None.

## Integration gate

- pytest: 1701 passed, including 27 Node page-script tests that run in CI and fail rather than skip when node is missing
- cfn-lint: 4 × W3005 warnings, the same as on `stage`
- sam validate: pass
- sam build: pass
- Cross-checks: environment variables match both ways. The table is in both deploy policies and the rule in prod only, with no new wildcards. The function gets GetItem and PutItem on that table only. `IsProd` covers both the rule and its permission. The authorizer covers `?refresh=1`. The page's tokens and CSP are intact, and the page is 70 KB.

## Review

- Review rounds inside phases: 11, all cold and independent. Findings fixed: 1 BLOCK (botocore retries) and every WARN.
- Pull request rounds: 1. The deploy-role redeploy exceeded IAM's policy size limit, so `3cdb4dd` split the policies and added a size test, and the rules and agent checklists were updated to match. No reviewer comments came in.

## Rollback

```bash
git log --oneline origin/stage..feature/class-photo-loading
git revert <sha>   # undoes one phase
```

To clear a bad cache copy, use `aws dynamodb delete-item` (see the API README). The next request reads Neon live.

## Action items

- [ ] The admin actions above
- [ ] Review #119, especially `functions/classes/class_photo_upload_api/class_list_service.py`, `dynamodb_class_list_cache.py`, `templates/classes.yaml` (the table and the IsProd rule) and `template-cicd.yaml`
- [ ] Run `MANUAL_QA.md` on stage, then on prod after `/promote`
- [ ] Decide on a follow-up issue for the empty-class-list message

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
