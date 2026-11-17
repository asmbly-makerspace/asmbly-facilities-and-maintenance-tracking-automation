# Offshore briefing: pm-reminder-checkmark-complete

**Date:** 2026-11-16
**Branch:** `feature/pm-reminder-checkmark-complete`
**Pull request:** #170 to `stage`, **green, waiting for your review and merge**
**Epic:** #7 (stories #162, #163, #164, #165, all closed by #170)
**Phases completed:** 6 of 6

> **Next steps for you, in order:**
> 1. Do the admin actions below that say "before merge".
> 2. Review pull request #170 and merge it. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` steps 1–14 against the stage stack (stage is a dry run: check the logs).
> 4. Do the "before prod" admin actions, then run `/promote` to take `stage` to `main` (prod).
> 5. On the first real ✅ in prod, run `MANUAL_QA.md` steps 15–22.
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

| When | Action | Why |
| --- | --- | --- |
| Before merge | Redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` by hand from `template-cicd.yaml` (docs/Deploying.md, "How to Manage the Deployer Role"). It adds `PMReminderReactionFunction-{stage,prod}` and its log groups to the deploy policies, adds table `PMReminderCompletions-{stage,prod}` to the data policies, and renames Sid `AllowClassListCacheTableReads` to `AllowTableReadsAfterCreate`. | The stage deploy fails without it. |
| Before prod | Add the Slack channel IDs for 3d-printing, ceramics, electronics, lasers, metal-shop and textiles to `configs/router_config.json` → `pm_channels`. Only woodshop-maintenance (`C0CJAK1D725`) is there. | A ✅ in an unlisted channel does nothing. IDs weren't guessed: no Slack tool was available. |
| Before prod | Confirm the Maintenance Bot is a member of all 7 PM channels and has `channels:history` (plus `groups:history` for private channels), `reactions:read`, `chat:write`, `chat:write.customize` and `users:read`. | Without `channels:history` every ✅ fails (`not_in_channel`); without `chat:write.customize` replies can't use the PM Bot name; without `users:read` the ClickUp comment shows a user ID. |
| Before prod | Turn on ClickUp recurrence for Clean Metal Shop Sink (`86a8be2bc`): recurs on complete, skip missed dates. | It's the only one of 46 PM tasks without recurrence (ClickUp check posted on #7). |
| First prod ✅ | Run `MANUAL_QA.md` steps 15–22: a second ✅ on the same reminder gives one completed and one duplicate; the due date moves one cycle; the reply's "Next due" matches ClickUp; the ClickUp comment names the person; note whether watchers get notified. | The write paths can only be seen in prod (stage is `DRY_RUN=true`). This also confirms that the API v2 status change triggers recurrence, which the epic only tested through the MCP. |
| Optional | One read-only `GET https://api.clickup.com/api/v2/task/86a8eb482` with the Lambda's token: does `date_done` survive a recurrence reopen? | It decides whether the extra "stale" check can ever fire. The DynamoDB claim guards against double completion either way. |
| Optional | Test the router path on stage (invoke `facilities-slack-event-router-stage` with an API Gateway-shaped event; steps in `functions/facilities/pm_reminder_reaction/README.md`). | It invokes functions, so offshore didn't run it. |
| Emergency stop | Set prod `DRY_RUN` to `"true"` on `PMReminderReactionFunction` in `templates/facilities.yaml`. | It turns off all writes without reverting the router. |

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 3h (2h52m of subagent time) |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | No ClickUp or Slack tool in the session. You added the ClickUp MCP mid-run; a separate session answered the ClickUp questions on #7, and those facts went into phase 3. Slack channel IDs remain an admin action. |

## Phases

| Phase | Title | Status | Commit | Review rounds |
| --- | --- | --- | --- | --- |
| — | Implementation plan | Done | `21b199c` | — |
| 1 | PM channel config and Slack message helpers | Done | `f18453e` | 1 |
| 2 | PM reminder reaction handler | Done | `2921957` | 3 |
| 3 | Complete once per cycle | Done | `b372f13` | 3 |
| 4 | Route PM channel reactions to the handler | Done | `06603bb` | 2 |
| 5 | Thread replies in Slack | Done | `b86ceee` | 3 |
| 6 | ClickUp comment naming who ticked it | Done | `0f7997b` | 1 |
| — | Docs | Done | `b566b4a` | — |
| — | Manual QA steps | Done | `d5bd81e` | — |

Each phase also had /build's mandatory independent review before its rounds.

## Decisions made

- **#165 built, as phase 6:** it's a Could in the epic, but it needed only one small ClickUp helper.
- **Router order with #79 and #92:** neither had a PR, so phase 4 went first; they rebase on it.
- **Stage is a dry run that fails closed:** only an exact `DRY_RUN=false` writes, because stage shares prod's ClickUp list. See `templates/facilities.yaml`.
- **Once per cycle:** a conditional DynamoDB claim is written *before* the ClickUp update. A retry, a Slack redelivery or a second ✅ gets "duplicate". ClickUp's `date_done` is only a best-effort extra check, because it may disappear when the task reopens.
- **After a failed ClickUp update:** the claim stays pending for 5 minutes (`CLAIM_EXPIRY_SECONDS=300`, more than 3× the 90 s timeout) instead of being removed, because a timed-out update may still land.
- **Failure reply differs from #164 criterion 3:** it adds "Wait 5 minutes, then remove and add the ✅ again" because of that lock. A test ties the minutes to the constant.
- **Truncated Slack reaction lists:** a ✅ counts if the user is listed, or if the count exceeds the listed users. In that second case the ClickUp comment names the Slack user ID, never a looked-up name, so a forged event (#79) can't put a real name in ClickUp.
- **ClickUp comment is a separate step after the Slack reply:** a comment failure can't change the outcome or skip the reply.
- **Timeout 90 s:** four outside calls with 8 s connect and 8 s read timeouts, plus SSM and Secrets Manager.
- **Least privilege:** the role gets GetItem, PutItem and UpdateItem on the table only, and only the two secrets and two parameters it reads.
- **New dependency:** `tzdata`, so replies show Austin dates (`functions/facilities/pm_reminder_reaction/requirements.txt`, with a dependabot entry). It's loaded lazily, so if it's missing only the date is lost.

## Plan changes

- **Phases 2–6:** /prep returned NEEDS REVISION for each one. The amendments were applied to the phase doc and committed before building. The biggest changes: the claim stays pending on failure instead of being reverted (phase 3); the comment step moved after the reply (phase 6).
- **Phase 2:** the timeout grew from 30 s to 90 s.
- **Phase 5:** the phase doc said no IAM change; it actually adds `dynamodb:PutItem`, which phase 3 had removed as unused.

## Deferrals and blockers

- **Rare double completion (#167):** if a ClickUp update lands but the `done` write fails, a later takeover can complete the task once more. The simple fix trades this for a missed completion. Recommendation: decide the design in #167.
- **A definite ClickUp error still locks the task for 5 minutes (#168):** `clickup.update_task` raises the same error for every failure. Recommendation: expose the HTTP status (#168).
- **Templates missing a transform (#169):** routers, administrative and networking lack `AWS::LanguageExtensions`. This predates the branch.
- **#79 is more urgent now:** `/slack/events` still has no signature check and now forwards PM reactions. Forged events could use up the Slack rate limit or trigger a failure reply, but can't complete an unticked task. Commented on #79.
- **Your call: dates have no year.** Replies say "Wed Nov 25", which is ambiguous for yearly tasks. #164 fixes the format. Options: (a) keep it, (b) add the year for intervals over 6 months. Recommendation: (b), as a small follow-up.
- **Your call: a failure reply under "Marked done".** If a second person ticks an already-completed reminder while ClickUp can't be read, the bot posts "Couldn't mark this done". Options: (a) accept, (b) skip the failure reply when the reminder already has a "Marked done" reply. Recommendation: (b).
- **Your call: possible duplicate ClickUp tasks:** "Update iPad" (`86acdg2cu`, `86acdg066`) and "Inspect Blades" (`86a88jye1`, `86a88jxn2`) have the same names and rules. This is ClickUp housekeeping, not code.
- **Accepted and documented:** a permanent ClickUp failure (404 or 401) still says "Try again later". An errored update that lands later leaves "Couldn't mark this done" as the last reply. A due date moved by hand during an expired failed claim reads as a landed update.

## Skipped because of the environment

- None of the automated checks were skipped.
- Slack channel IDs and bot scopes couldn't be checked (no Slack tool). They're admin actions above.

## Integration gate

- pytest: 2246 passed, 10 subtests (includes `tests/test_templates.py`, so every deploy policy is under 6,144 characters)
- cfn-lint: no new findings; the 4 W3005 warnings in `template.yaml` are also on `stage`
- sam validate: pass
- sam build: pass (`tzdata` bundled)
- Cross-checks (environment variables, deploy role names, nested parameters, routes, IAM): clean, no fixes needed

## Review

- Review rounds inside phases: 13, plus 6 independent build reviews. One BLOCK was found and fixed (phase 3: an older reminder could complete a task after a failed update; now covered by a regression test). Every WARN was fixed. 13 items were deferred: 3 opened as issues, the rest decided or documented above.
- Pull request rounds: 0. CI `test` was green on the first run; there were no review comments.

## Rollback

Each phase is one commit:

```bash
git log --oneline origin/stage..feature/pm-reminder-checkmark-complete
git revert <sha>   # undoes one phase
```

To switch the feature off in prod without a revert, set `DRY_RUN` to `"true"` (above). Don't revert phase 4 (routing) or empty `pm_channels` on its own: tests check both.

## Action items

- [ ] Redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` before merging #170
- [ ] Review #170, especially the claim logic in `functions/facilities/pm_reminder_reaction/lambda_function.py` (the conditional `UpdateItem` and its takeover clause) and the deploy-role changes in `template-cicd.yaml`
- [ ] Run `MANUAL_QA.md` steps 1–14 on the stage stack
- [ ] Add the six PM channel IDs to `configs/router_config.json` and confirm the bot's channels and scopes before `/promote`
- [ ] Turn on recurrence for Clean Metal Shop Sink (`86a8be2bc`)
- [ ] Decide on dates without a year, and on the failure reply under "Marked done" (above)
- [ ] Triage #167, #168, #169, and prioritize #79

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
