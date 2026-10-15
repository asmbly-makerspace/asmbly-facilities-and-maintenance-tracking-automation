---
name: promote
description: Take what is on stage to production - check the stage deploy and manual QA, open the pull request from stage to main, wait for the checks, merge only on the person's word, watch the prod deploy, and confirm the live site. Use when asked to promote, release, or ship stage to main or prod.
argument-hint: [short description of what is being released]
model: sonnet
effort: medium
---

# /promote: stage to main

Merging to `main` deploys to prod (`Deploy Production Pipeline`, `.github/workflows/deploy.yml`).
Merge only when the person you're working for says so, for this pull request.

```
$ARGUMENTS
```

## 1. What is on stage and not on main

```bash
git fetch origin
git log --oneline --first-parent origin/main..origin/stage
gh pr list --base stage --state merged --limit 30 --json number,title,mergedAt,mergeCommit \
  --jq '.[] | "\(.number) \(.mergedAt[:10]) \(.title)"'
```

Keep the pull requests whose merge commit is in `origin/main..origin/stage`. If there is
nothing, say so and stop.

## 1b. Is stage up to date with main?

```bash
git log --oneline origin/stage..origin/main
```

`main`'s ruleset requires a pull request's branch to be up to date with `main` before it
can merge. Every promotion leaves a merge commit on `main` that `stage` doesn't have, so
this usually lists the previous promotion's merge commit (and any change that went
straight to `main`). If it lists anything, `stage` must take it first:

```bash
gh pr create --base stage --head main --title "Sync main into stage" \
  --body "Brings the commits on main that stage lacks, so the promotion can merge. No new changes."
gh pr checks <sync N> --watch --interval 30
```

Ask the person to merge it with a merge commit (it changes no files when `main` only has
merge commits). Don't use "Update branch" on the promotion pull request: that would push
to `stage` directly, which its ruleset forbids. When the sync has merged, fetch and go on.

## 2. Is stage healthy?

```bash
gh run list --workflow deploy-staging.yml --branch stage --limit 1 \
  --json headSha,conclusion,url --jq '.[0]'
git rev-parse origin/stage
```

- The latest stage deploy must have succeeded **on the current `origin/stage` commit**.
  If it failed, or it ran on an older commit, stop and report it: prod would get
  something stage never ran.
- For each plan whose work is in this release, find `.implementation_plans/<plan>/MANUAL_QA.md`.
  Ask whether those steps passed on stage, unless the person already said so. Don't
  promote a plan whose QA failed.

## 3. Admin actions for prod

Read the **Risk** section of each pull request in the release and the `## Admin actions`
of their plans. List what must happen before or after the prod deploy, for example:

- the deploy role: `template-cicd.yaml` holds both the stage and the prod names in one
  stack, so if the stage deploy passed, the role already allows prod;
- secrets the prod functions read;
- third-party settings that point at prod (`https://facilities.asmbly.org/<path>`): the
  Slack app's commands and event URL, ClickUp webhooks, the Smartwaiver webhook, the
  Google Apps Script.

## 4. Open the pull request

```bash
gh pr create --base main --head stage \
  --title "Promote <what> from stage to main" --body-file <file>
```

Fill the template: **Summary** lists each pull request included (`#N title`), **Risk**
lists the admin actions from step 3 and says which must happen before the merge, and
**Test plan** links the stage deploy run and the QA results. Issues were already closed
when their pull requests merged to `stage`; write `Refs #N` here, not `Closes`.

## 5. Wait for the checks

```bash
gh pr checks <N> --watch --interval 30
```

`test` is required on `main`. If it fails, read it (`gh run view <id> --log-failed`).
The fix goes to `stage` through its own pull request, never into this one.

## 6. Merge, on the person's word

Report that the checks are green and the admin actions are listed, and stop. When the
person says to merge this pull request:

```bash
SHA=$(gh pr view <N> --json headRefOid --jq .headRefOid)
gh pr merge <N> --merge --match-head-commit "$SHA"
```

Use `--merge`, as every earlier promotion did: `main` keeps each commit from `stage`, so
the next sync from `main` to `stage` (step 1b) brings back only this merge commit and no
changes. A squash would put the same changes on `main` as a different commit, and every
later sync would have to reconcile the two. Never delete the `stage` branch.

## 7. Watch the prod deploy

```bash
gh run list --workflow deploy.yml --branch main --limit 1
gh run watch <run-id> --exit-status
curl -s -o /dev/null -w '%{http_code}\n' https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer
```

The Kiln Drop-Off page is a public read-only page, so a `200` means the custom domain,
the API and a function all answer. If the deploy fails, read the failed step
(`gh run view <run-id> --log-failed`). CloudFormation rolls back and the previous version
keeps serving. Don't re-run blindly: fix forward on `stage`, or revert with a pull
request. A permissions error from the deploy role means a name is missing from
`template-cicd.yaml` (docs/Deploying.md, "How to Manage the Deployer Role").

## 8. Report

Say what was released (the pull requests), the prod deploy's result and run link, the
smoke check's status code, the admin actions still to do, and which plans now have every
phase on `main` (their folders can move to `.implementation_plans/DONE/` in a `chore:`
pull request). If a step was skipped or failed, say which.
