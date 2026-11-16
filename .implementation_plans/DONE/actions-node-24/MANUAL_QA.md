# Manual QA: GitHub Actions on Node.js 24

Acceptance steps for `feature/actions-node-24`, by story, so each check maps back to
#124.

Steps 1 and 2 run on the pull request before it merges. Steps 3 to 9 run on the **stage
stack**, after the pull request merges to `stage`, and before `/promote`. Steps 10 to 16
run after the next `/promote`, on the prod stack.

> Automated checks already passed on the branch: pytest 1721 passed, cfn-lint 4 W3005
> warnings (the same 4 are on `origin/stage`, so none is new), sam validate pass, sam
> build pass, actionlint pass. Nothing was skipped. `tests/test_workflows.py` checks the
> first and third criteria of #124 on every `test` run: no workflow uses an action older
> than its first Node.js 24 major, and each deploy job keeps its environment name, its
> `id-token: write` permission, its role and its two credentials inputs. The steps below
> cover what only a real workflow run can show.

This change touches only `.github/workflows/`, `tests/test_workflows.py`,
`docs/Deploying.md` and the plan documents. No Lambda function, route, webhook, template
or configuration changes, so there are no webhook steps and no `curl` with a payload:
nothing in Slack, ClickUp, Neon or CloudWatch behaves differently. What a person can see
is the workflow runs themselves (their result, their annotations, their summary) and
the Deployments page. One `curl` to an existing route checks that the stack still
answers after each deploy.

## Prerequisites

- Admin actions: none. The checkpoint lists none, and the deploy role
  (`template-cicd.yaml`) doesn't change.
- `gh` signed in with read access to the repository, and a browser for the Actions and
  Deployments pages. No access to Slack, ClickUp, Neon or AWS is needed.
- These shell variables, used by the commands below:

  ```bash
  REPO=asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation
  PR=$(gh pr list --repo "$REPO" --head feature/actions-node-24 --state all \
    --json number --jq '.[0].number')
  STAGE_API_URL=https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage
  PROD_API_URL=https://facilities.asmbly.org
  ```

---

## #124: ci: update GitHub Actions that still run on Node.js 20 (phase 1)

### On the pull request

1. Check that the `test` check passed on both runs for the pull request's latest
   commit (the push run and the pull_request run), and note each run's job ID:

   ```bash
   gh pr checks "$PR" --repo "$REPO"
   gh pr checks "$PR" --repo "$REPO" --json name,event,state,link \
     --jq '.[] | "\(.event) \(.name) \(.state) job=\(.link | split("/") | last)"'
   ```

   If you'd rather start from the runs:

   ```bash
   gh run list --repo "$REPO" --workflow python-tests.yml --branch feature/actions-node-24 --limit 4 \
     --json databaseId,event,headSha,conclusion \
     --jq '.[] | "\(.databaseId) \(.event) \(.headSha[0:7]) \(.conclusion)"'
   gh run view <run id> --repo "$REPO" --json jobs \
     --jq '.jobs[] | "\(.databaseId) \(.name) \(.conclusion)"'
   ```

   **Expect:** `test` passes, once for the `push` event and once for `pull_request`.
2. Read the annotations of each `test` job from step 1:

   ```bash
   gh api repos/$REPO/check-runs/<job id>/annotations \
     --jq '.[] | .annotation_level + ": " + .message'
   ```

   **Expect:** no line containing `Node.js 20 is deprecated`. Empty output is a pass.
   Before this change the line read `warning: Node.js 20 is deprecated. The following
   actions target Node.js 20 but are being forced to run on Node.js 24:
   actions/checkout@v3, actions/setup-python@v3.`

### After the merge to `stage`

3. Find the Deploy Staging Pipeline run for the merge commit and watch it finish:

   ```bash
   MERGE_SHA=$(gh pr view "$PR" --repo "$REPO" --json mergeCommit --jq .mergeCommit.oid)
   RUN=$(gh run list --repo "$REPO" --workflow deploy-staging.yml --branch stage \
     --commit "$MERGE_SHA" --json databaseId --jq '.[0].databaseId')
   gh run watch "$RUN" --repo "$REPO" --exit-status
   ```

   **Expect:** the run finishes with `success`.
4. Check both jobs and the steps whose actions changed:

   ```bash
   gh run view "$RUN" --repo "$REPO" --json jobs \
     --jq '.jobs[] | "\(.databaseId) \(.name) \(.conclusion)"'
   gh run view "$RUN" --repo "$REPO" --json jobs \
     --jq '.jobs[] | select(.name == "Deploy to AWS (staging)") | .steps[] | "\(.name): \(.conclusion)"'
   ```

   **Expect:** `Deploy to AWS (staging) success` and `List API routes success`. (A failed
   **List API routes** job doesn't fail the run, so check its own result here.) In the
   deploy job, `Checkout code`, `Configure AWS Credentials` and `Setup SAM CLI` are all
   `success`. `Configure AWS Credentials` passing means the OIDC sign-in still works with
   `configure-aws-credentials@v6` and the unchanged deploy role.
5. Read the annotations of both jobs, using the two job IDs from step 4:

   ```bash
   gh api repos/$REPO/check-runs/<job id>/annotations \
     --jq '.[] | .annotation_level + ": " + .message'
   ```

   **Expect:** no line containing `Node.js 20 is deprecated`. Before this change the
   deploy job's line ended `... actions/checkout@v4, aws-actions/configure-aws-credentials@v4,
   aws-actions/setup-sam@v2.`
6. Open `https://github.com/asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation/deployments`
   and choose the **stage** environment.

   **Expect:** the newest stage deployment is from the merge commit and shows
   `https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage`.
7. Open the run's page and look at its **Summary**:

   ```bash
   gh run view "$RUN" --repo "$REPO" --web
   ```

   **Expect:** the API routes table, with 12 rows, each a full URL.
8. Check that the stage stack still answers:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' "$STAGE_API_URL/KilnOpsDropoffRecentEntriesViewer"
   ```

   **Expect:** `200`.
9. **If step 3, 4 or 5 failed:** don't run `/promote`. CloudFormation rolls back a failed
   stack update, so the stage stack stays on the last good version. Revert the merge with
   a pull request to `stage` (a `fix/` branch from `stage` with
   `git revert -m 1 "$MERGE_SHA"`), or fix the cause in a follow-up pull request, and run
   steps 3 to 8 again on its deploy. If the failure is in `Set up Python` or
   `Build SAM Application` on a run after 2026-10-19, look at the runner first: #124's
   notes say `ubuntu-latest` moves to Ubuntu 26 from that date, and this change doesn't
   touch either step.

   **Expect:** `stage` isn't promoted to `main` until a stage deploy passes steps 3 to 8.

### After the next `/promote`

10. Find the Deploy Production Pipeline run for the promote pull request's merge commit
    and watch it finish:

    ```bash
    PROMOTE_PR=<the stage-to-main pull request number>
    PROD_SHA=$(gh pr view "$PROMOTE_PR" --repo "$REPO" --json mergeCommit --jq .mergeCommit.oid)
    PROD_RUN=$(gh run list --repo "$REPO" --workflow deploy.yml --branch main \
      --commit "$PROD_SHA" --json databaseId --jq '.[0].databaseId')
    gh run watch "$PROD_RUN" --repo "$REPO" --exit-status
    ```

    **Expect:** the run finishes with `success`.
11. Check both jobs and the deploy job's steps:

    ```bash
    gh run view "$PROD_RUN" --repo "$REPO" --json jobs \
      --jq '.jobs[] | "\(.databaseId) \(.name) \(.conclusion)"'
    gh run view "$PROD_RUN" --repo "$REPO" --json jobs \
      --jq '.jobs[] | select(.name == "Deploy to AWS") | .steps[] | "\(.name): \(.conclusion)"'
    ```

    **Expect:** `Deploy to AWS success` and `List API routes success`; in the deploy job,
    `Checkout code`, `Configure AWS Credentials` and `Setup SAM CLI` are `success`.
12. Read the annotations of both jobs from step 11, with the command from step 5.

    **Expect:** no line containing `Node.js 20 is deprecated`.
13. Open the Deployments page from step 6 and choose the **prod** environment.

    **Expect:** the newest prod deployment is from the promote merge commit and shows
    `https://facilities.asmbly.org`.
14. Open the run's **Summary** (`gh run view "$PROD_RUN" --repo "$REPO" --web`).

    **Expect:** the API routes table, with the same 12 routes as the stage run in step 7.
15. Check that prod still answers:

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' "$PROD_API_URL/KilnOpsDropoffRecentEntriesViewer"
    ```

    **Expect:** `200`.
16. When steps 10 to 15 pass, close #124 by hand. The pull request says `Refs #124`, not
    `Closes #124`, because these post-merge criteria can't be checked before the merge.

    ```bash
    gh issue close 124 --repo "$REPO" --comment "Stage and prod deploys pass with no Node.js 20 warning."
    ```

    **Expect:** #124 closed. If step 10, 11 or 12 failed instead, keep #124 open; a failed
    prod deploy rolls back the same way as in step 9.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
