# Offshore briefing: safe-exception-text

**Date:** 2026-10-17
**Branch:** `feature/safe-exception-text`
**Pull request:** #146 to `stage`, **green, waiting for your review and merge**
**Epic:** #141 (stories #142, #143, #144, #145; fixes bug #95 and #83)
**Phases completed:** 3 of 3

> **Next steps for you, in order:**
> 1. There are no admin actions. Nothing has to happen before the merge.
> 2. Review pull request #146 and merge it. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` against the stage stack.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod).
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

None. The branch changes no template, IAM policy, SSM parameter, secret, route, schedule or the deploy role (`template-cicd.yaml`). It also needs no Slack app or ClickUp webhook change. The common layer changes, so the normal stage deploy republishes it and redeploys every function that uses `CommonLayer`.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 1h45m, most of it in phase subagents |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. Python 3.12.11, SAM CLI 1.166.2 and `gh` were all present. |

The phase 1 subagent returned its result but left some background work running. I stopped it after squashing, so it couldn't add commits after the squash. The tree was clean afterwards.

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| — | Implementation plan (epic #141) | Done | `c434c0d` | — | 13m |
| 1 | ClickUp exception text and payload log lines | Done | `9832047` | 2 | 22m |
| 2 | Plain error replies and /reorder error modal | Done | `0338dea` | 2 | 22m |
| 3 | Logging cleanup and request timeouts | Done | `2635f0b` | 2 | 25m |
| — | Docs | Done | `a83bf42` | — | 1m |
| — | Manual QA steps | Done | `bd6ec83` | — | 10m |

## Decisions made

- **Safe endpoint text in ClickUp errors:** added `_endpoint_for_log` (`layers/common/python/common/clickup.py:41`). An endpoint that doesn't fully match `[A-Za-z0-9_/-]{1,256}` shows as `<invalid>`. The endpoint isn't trusted as is, because `new_purchase_request_received` builds it from an unauthenticated webhook body.
- **`raise ... from None` on ClickUp errors:** without it, `logger.exception` tracebacks would still print the chained `requests` error, with the URL and query string.
- **`update_task`** (`clickup.py:112`) checks the requested task ID. A non-dict or `None` response now raises the same `ValueError` ("no task ID") instead of a `TypeError`.
- **/reorder failure text:** kept "Your purchase request was not created" (`functions/purchase_request/slack_slash_reorder/lambda_function.py:20`) instead of "may not have been created". Story #143 AC2 asks for that wording, and a create slower than 8 s is rare. The /reorder README tells volunteers to check ClickUp before resubmitting after a slow failure. Only failures up to and including `create_task` show it. A failed success-view post is logged only, so users aren't invited to file a duplicate.
- **8-second timeout per request** on ClickUp (`clickup.py:11`), Slack and Neon (`neoncrm.py:43`, `:77`). It is per request, not per function. It is shorter than the shortest Lambda timeout of any caller (10 s). Discourse has no timeout yet (plan Decision 11).
- **Reaction functions** log the Slack `event_id` on unexpected errors (#143 AC7). Task IDs from unauthenticated bodies are logged with `%r`.
- **Neon root logger:** `neoncrm.py` no longer sets the root log level on import. Its callers (`new_waiver_completed`, `class_photo_upload_api`) set INFO themselves, so no logs are lost. A test checks this in a fresh interpreter, not with `importlib.reload`, because a reload breaks `pytest.raises(NeonCRMError)` in other tests.
- **Test placement:** the new Neon and Discourse tests went into the existing `layers/common/python/tests/` files. Without an `__init__.py`, a second file with the same name would fail collection.
- **Tests updated, not deleted:** four reaction missing-variable tests used to pin the variable name through the 500 body. They now assert the fixed body and find the name in the logged traceback.
- **Scope:** no caller check on any existing route (#79 owns that). The kiln viewer test file is untouched, to stay clear of #137. `docs/README.md` is unchanged, because no service, trigger, URL or caller changed.
- **Closes #83:** story #143 fixes the same `str(e)` return on `/purchase-request/new` (plan README Decision 2).

## Plan changes

- **Phase 1:** prep said READY. The auditor's notes for the build were still written into the phase doc (commit in `9832047`), so build and review worked from one spec.
- **Phase 2:** prep said NEEDS REVISION (0 HIGH, 2 MED, 4 LOW). The amendments were applied to the phase doc before the build.
- **Phase 3:** prep said NEEDS REVISION. Test file locations were corrected, the existing Neon `assert_called_once_with` calls gained `timeout=8.0`, the fresh-interpreter import check was added, and the Neon and Slack user-lookup failure lines were specified.

## Deferrals and blockers

No blockers. Every follow-up below is a pre-existing problem or one this work makes newly visible, and none is a regression the tests miss.

- **Waiver handler on a Neon timeout:** a Neon search that times out or fails now answers 404 "no account". A failed or timed-out update still answers 200 "success". Before this change, a hung Neon ran into the 30 s Lambda limit. Options: (a) add the search and timeout case to #99, (b) a separate issue. Recommendation: (a).
- **`/waiver/new` echoes the email:** its 404 and 200 replies include the submitted email, and a 404 versus a 200 tells any caller whether an email has a Neon account. The route is public and this work doesn't touch it. Options: (a) fold into #99, (b) a new issue. Recommendation: (b), because this is account enumeration, a separate problem from #99's silent failure.
- **Slow writes count as failures:** a ClickUp or Slack write that the vendor commits after 8 s now counts as a failure. `/reorder` says "not created". The new purchase request route answers 500 after Slack has posted, so ClickUp's webhook retry posts again. The new problem report's Slack message says "ClickUp Task: Error creating task". Options: (a) treat a `ReadTimeout` on a write separately, (b) accept it. Recommendation: (a), as a follow-up issue.
- **Timeouts are per request:** `/reorder`'s submission makes 3 calls inside a 10 s function. No async invoke sets `MaximumRetryAttempts`, so a Lambda timeout retry could run `create_task` twice. Options: (a) a deadline from `context.get_remaining_time_in_millis()`, (b) `MaximumRetryAttempts: 0` on `/reorder`. Recommendation: (b), the smaller change.
- **Calls with no timeout yet:** `/reorder`'s own `views.open` and `views.update` posts, and every Discourse request. Recommendation: one follow-up issue.
- **`create_task` doesn't check for an `id`** in ClickUp's 200 body, so `/reorder` could show "Success!" when no task was created (pre-existing). Recommendation: a follow-up issue.
- **Unchecked error-modal posts:** if `/reorder`'s error-modal post fails, the user stays on "Loading…" (pre-existing). Low priority.
- **Duplicate Slack post on a ClickUp retry:** in `new_purchase_request_received`, if the Slack post succeeds and `set_custom_field_value` then fails, the route answers 500. ClickUp's retry then posts to Slack a second time (pre-existing; the plan keeps status codes as they are).
- **Variable names in a 500 body:** `new_purchase_request_received`'s missing-variable 500 names the variables (lines 42-45). They are configuration names, not secrets. Recommendation: skip, or fix together with #83's follow-up.
- **Unguarded `.get('id')`:** `reply_response.get('id')` in `problem_report/slack_reaction_webhook/lambda_function.py:118` isn't guarded (pre-existing).
- **Doc drift:** `docs/README.md:117` names the reorder function `FacilitiesSlackPurchaseReorderFunction`, but the template uses `SlackSlashReorderFunction-${Stage}`. Recommendation: a one-line docs fix.
- **Style (not acted on):** `_log_received_event` is duplicated in both reaction handlers. `test_discourse.py` repeats the fresh-interpreter check from `test_neoncrm.py`, and a `conftest.py` could share it. "Network error during ClickUp API request" also labels a 2xx answer whose body isn't JSON (an existing label, now pinned by a test).
- **Unset `TEST_CHANNEL_OVERRIDE`:** `pm_bot_reminder` and `common/slack.py` read it, but no template sets it. It is an optional local-testing override, and stage has the same.

## Skipped because of the environment

None.

## Integration gate

- pytest: 1,831 passed, 8 subtests (1,779 on `stage` before the run)
- cfn-lint: exit 4, with only the 4 W3005 warnings in `template.yaml:582/592/605`. `origin/stage` has the same 4, and this branch changes no template.
- sam validate: pass
- sam build: pass
- Cross-checks: clean. Environment variables are unchanged. There are no new named resources, nested parameters or routes. All 183 test patch targets resolve. `ruff --select F` is clean on the 18 changed Python files. No caller reads the removed `error_message` key or parses the old ClickUp error text.

## Review

- Review rounds inside phases: 6 (2 per phase), plus `/build`'s independent review in each phase, which approved all three with 0 BLOCK. All findings that were bugs or in scope were fixed. The rest are listed above.
- Pull request rounds: 0. No comments or reviews yet, and the repository has no automated review workflow. Both `test` runs are green on `bd6ec83`, and the merge state is CLEAN.

## Rollback

Each phase is one commit:

```bash
git log --oneline origin/stage..feature/safe-exception-text
git revert <sha>   # undoes one phase
```

The phases depend on each other in order: phase 2 uses phase 1's message formats, and phase 3 builds on both. Revert from the newest phase back.

## Action items

- [ ] Review pull request #146, especially `layers/common/python/common/clickup.py:41-130` (`_endpoint_for_log`, `_make_clickup_request`, `update_task`) and `functions/purchase_request/slack_slash_reorder/lambda_function.py` (which failures show the error modal)
- [ ] Merge #146, then run `.implementation_plans/safe-exception-text/MANUAL_QA.md` on the stage stack. Stage shares prod's Slack bot, ClickUp token and Neon secret. Steps 1-10 use made-up IDs; steps 11-12 are optional because they touch real records. Delete step 3's test messages afterwards.
- [ ] Decide on the waiver follow-ups: the timeout case for #99, and the email echo and account enumeration on `/waiver/new`
- [ ] Decide whether to open issues for timeout-on-write handling, `MaximumRetryAttempts: 0` on `/reorder`, the remaining calls with no timeout, and `create_task`'s missing `id` check
- [ ] #137 can start after this merges: this work didn't touch the kiln viewer test file

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
