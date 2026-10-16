---
name: bug-fix
description: Plan, fix, review, document and open a pull request for a bug in one run. A cold planner traces the root cause, /prep checks the plan, /build writes the regression test and the fix, independent reviewers check it, and the pull request to stage is driven to green and left open. Use when asked to fix a bug, or given a bug report or a bug issue number.
argument-hint: "<bug report or #issue> [--plan-only] [--no-pr] [--issue]"
model: opus
effort: high
---

# /bug-fix: plan, fix, review, document and open a pull request for a bug

The bug report: a description, log lines, screenshots, repro steps, and optionally a
GitHub issue (`#74` or its URL) and flags:

```
$ARGUMENTS
```

You are a **thin orchestrator**. The work happens in agents and skills: a planning agent,
then `/prep`, `/build`, the reviewers, and `/write-docs`. Keep your own context small:
read their structured returns, show the person what matters, and keep the run moving. You
don't write the fix yourself.

## The sequence

```
parse → branch → plan (bug-planner) → plan checkpoint
      → prep → build → review (independent review-lead + /review, ≤3 cycles)
      → write-docs (if needed) → pull request to stage → drive to green → report
```

**Done means:** the reporter's exact scenario is fixed, the checks in `CLAUDE.md` pass,
and the pull request to `stage` is green and left open for the person to merge. A pushed
branch or an opened pull request is not done. See `CLAUDE.md`, "Don't stop short".

### Flags

| Flag | Effect |
| --- | --- |
| `--plan-only` | Stop after the plan checkpoint (Step 3). |
| `--no-pr` | Stop after the review (Step 6): branch pushed, no pull request. |
| `--issue` | Open a GitHub issue for the bug after the person approves the plan, and close it from the pull request. |

## Hard rules

- **Follow `CLAUDE.md`.** Pass "Follow CLAUDE.md" into every agent prompt.
- **No `--no-verify`, no bare `--force`, no skipped or deleted tests, no merging.** The
  person merges.
- **No pushing to `stage` or `main`.**
- **No `sam deploy` and no AWS command that changes anything.** Read-only AWS commands
  (CloudWatch Logs, `describe-stacks`) are fine for diagnosis.
- **Two rounds on style** (`CLAUDE.md`, "Review discipline"). Real bugs, security gaps
  and failing tests always reopen the loop.
- **Retry transient failures** 4 times (2, 4, 8, 16 seconds) in the same turn before
  escalating.
- **Ask only for decisions that are the person's:** a product behavior the docs don't
  settle, an accepted risk, a scope split, an admin action. Decide everything else, note
  it, and keep going.

### Agents and nesting

Spawn each registered agent with the Agent tool (`subagent_type: <name>`). Subagents can
spawn their own (up to three levels), so `/prep` and `/build` run inside their agents can
spawn theirs. If the Agent tool isn't available to you, read the agent's file and apply it
inline, and say so in your report: the review was then not independent. Run `/bug-fix` in
a top-level session when you can.

---

## Step 0: Parse the request

1. **The report.** Pull out the symptom, expected vs. actual, the entry point (route,
   schedule, Slack command or reaction), and the repro steps.
   - **Screenshots on disk:** pass the paths to the planner.
   - **Screenshots pasted into the chat** reach only you. Transcribe every value, message,
     status code and URL you can see into the report. That transcription is evidence, not
     a theory of the cause.
   - **Log lines:** include them, with any token or personal detail removed.
2. **Issue mode.**

   | Input | Mode | What changes |
   | --- | --- | --- |
   | `#N` or an issue URL | **Linked** | `gh issue view <N> --json title,body,labels,comments`; add its body and its "Done when" list to the report. The pull request says `Closes #N`. |
   | `--issue` | **Created** | After the plan checkpoint, open one issue (`gh issue create --label bug`) with the title, expected vs. actual, and repro steps. Then as Linked. |
   | neither | **Unlinked** | No issue. The pull request's Closes section says `n/a: no issue for this bug`. Don't open one on your own. |

## Step 1: Branch

`fix/<short-slug>`, from `stage`:

```bash
git fetch origin stage
git switch -c fix/<short-slug> origin/stage
git branch --unset-upstream 2>/dev/null || true   # a bare `git push` must never target stage
```

Run this whatever branch you're on, including a `claude/...` branch the harness gave you:
`-c` from `origin/stage` starts clean and keeps earlier work out. If the harness forbids
pushing any branch but its own, stay on the harness branch instead (reset it to
`origin/stage` only if it has no commits of yours) and say so in the report. Never work on
`stage`, `main`, or someone else's branch.

Record the base SHA now: `git merge-base HEAD origin/stage`. Every later `<BASE>` means
this SHA, written out in full: shell variables don't carry over between Bash calls.

## Step 2: Plan

Spawn `bug-planner` (`subagent_type: bug-planner`) with:

- the report from Step 0, verbatim, with your screenshot transcriptions;
- the paths of any screenshots on disk;
- the issue body and comments in Linked mode.

Don't give it your own theory of the cause: it traces the code cold. It returns a
markdown plan and writes no files.

## Step 3: Plan checkpoint

Show the person the plan as returned. Then:

- **Open questions:** ask them (AskUserQuestion), with enough context to answer without
  scrolling back. Fold the answers into the plan.
- **None:** say you're starting the build and continue. Don't wait for an approval
  nobody asked to give.
- **`--issue`:** open the issue now (Step 0).
- **`--plan-only`:** stop here.

Save the final plan to a file outside the repository: the session scratchpad if there is
one, otherwise `mktemp -d`. The plan is never committed.

## Step 4: Prep

Spawn a `general-purpose` agent:

```
Run /prep on an inline bug-fix plan: invoke Skill(skill: "prep", args: "inline plan: <plan path>").
The file is the whole plan; there is no plan directory, README, or phase tracker.
Branch: <branch>. Follow CLAUDE.md. Don't write code.

Return only:
  { verdict: "READY" | "NEEDS_REVISION" | "BLOCKED",
    amendments: <plan edits the findings require, as replacement text, or "none">,
    findings: <top findings, one line each>,
    inline_roles: <agents you ran inline instead of spawning> }
```

- **READY:** continue.
- **NEEDS_REVISION:** apply the amendments to the plan file, tell the person in a line or
  two what changed, and continue. If an amendment changes behavior the person saw in
  Step 3, ask first.
- **BLOCKED:** tell the person what blocks it and stop.

## Step 5: Build

Spawn a `general-purpose` agent:

```
Implement the bug-fix plan at <plan path>: invoke Skill(skill: "build", args: "instructions: <plan path> base <BASE>").
Branch: <branch> (checked out). Base: <BASE>. Follow CLAUDE.md.
- Write the regression test that reproduces the reported scenario first. Run it and confirm it
  fails before the fix and passes after.
- Commit after each phase (Conventional Commits, no Closes lines). Don't push.
- Run the checks from CLAUDE.md "Done means verified" for everything you touched.
- If the fix adds a named AWS resource, add it to both deploy-role policies in template-cicd.yaml.

Return only:
  { result: "done" | "blocked", commits: <N>, files_changed: <N>,
    regression_test: "<path>::<name>", failed_before_fix: true | false,
    checks: { pytest: "<passed>/<total>", cfn_lint, sam_validate, sam_build },
    notes: <deviations from the plan, or "none"> }
```

- `failed_before_fix: false` means the test doesn't reproduce the bug. Send it back once
  to fix the test; then stop and tell the person.
- **blocked:** a fixable problem (a wrong path in the plan, a missing fixture) gets the
  plan fixed and this step re-run once. Anything else: tell the person and stop.

## Step 6: Review

Run review cycles until clean, at most three. Size them by
`git diff --shortstat <BASE>..HEAD`: up to 300 lines, 1 cycle; 301 to 600, 2; more, 3.
Stop early when a cycle finds nothing above NOTE.

Each cycle:

1. **Independent review: spawn it yourself.** Spawn `review-lead`
   (`subagent_type: review-lead`) with only the branch, `<BASE>`, the changed-file list,
   and the specialist files that match the diff (the table in `/review` Step 5). No
   reasoning, no plan, no build notes: it reviews cold.
2. **Review and fix agent.** Spawn a `general-purpose` agent:

   ```
   Invoke Skill(skill: "review", args: "against <BASE>"). Then fix every real finding from that
   review AND from these independent findings: <review-lead's findings, verbatim>.
   Read .claude/agents/build/fixer.md for how to fix. BLOCKs, bugs, security gaps and failing
   tests are always fixed; straightforward WARNs are fixed. No one is present to answer
   /review's Part B: for each candidate, fold it in if it is small and in scope, otherwise list
   it under `declined` with a real reason (a contract, test, design choice or tradeoff; "minor"
   is not a reason). Re-run the CLAUDE.md checks after fixing. Commit the fixes. Don't push.

   Return only:
     { verdict: "APPROVED" | "CHANGES_REQUESTED", fixed: [<one line each>],
       declined: [<finding: reason>], checks: { pytest, cfn_lint, sam_validate, sam_build },
       commits: <N> }
   ```

List every `declined` item under "Flagged for you" in the report.

After the last cycle, if a BLOCK is still open, tell the person what remains and why, and
stop before the pull request.

**`--no-pr`:** push the branch (`git push -u origin fix/<short-slug>`), report, and stop.

## Step 7: Docs (only if needed)

| Run `/write-docs` when the fix... | Skip it when the fix... |
| --- | --- |
| changes what a caller sees, receives, or must configure | only touches tests, CI, or `.claude/` |
| changes a route, a trigger, a schedule, a secret or an environment variable | is a refactor with no behavior change |
| contradicts or fills a gap in a function's `README.md` or `docs/` | |

When it runs, spawn a `general-purpose` agent that invokes
`Skill(skill: "write-docs", args: "<bug summary: expected vs. actual, root cause, fix>; branch <branch>; base origin/stage")`.
It returns `DOCS_CREATED / DOCS_UPDATED / COMMIT_SHAS / BRANCH / NOTES`. Check that what
the docs now say matches the code. Record the decision either way ("docs: updated
`functions/.../README.md`" or "docs: skipped, <reason>").

## Step 8: Pull request

1. **Sync with `stage`:** `git fetch origin stage`; if it moved, merge it in and re-run
   the checks.
2. **Push:** `git push -u origin fix/<short-slug>`. Retry network errors 4 times.
3. **Open the pull request** to `stage`:

   ```bash
   gh pr create --base stage --head fix/<short-slug> --title "fix: <what changed>" --body-file <file>
   ```

   Fill every section of `.github/PULL_REQUEST_TEMPLATE.md`: the bug (expected vs.
   actual), the root cause, the fix, Closes (`Closes #N` in Linked or Created mode), Risk
   (including every admin action: a deploy-role redeploy before the change reaches
   `stage`, a secret, a Slack or ClickUp setting), the checks you ran with their results,
   and how to see the fix on the stage stack after it deploys.
4. Give the person the link.

## Step 9: Drive it to green

```bash
gh pr checks <n> --watch
```

- **Conflicts or behind** (`gh pr view <n> --json mergeStateStatus` shows `DIRTY` or
  `BEHIND`; `stage` only merges branches that are up to date): merge `origin/stage` in,
  re-run the checks, push.
- **A failing check:** fix it in a `general-purpose` agent that invokes
  `Skill(skill: "address-pr-comments", args: "<n>")`. It pushes its own fixes. A check
  that is red on `stage` too isn't this pull request's: say so once on the pull request
  and in the report.
- **Review comments** from people or bots: the same `address-pr-comments` agent; every
  comment gets a fix or a reply with a reason.
- Never push an empty commit to start a run again.

Repeat until `test` (the required check) is green on the head commit. **Don't merge.**

## Step 10: Report

```markdown
## Bug fixed: <title>

**Pull request:** <link>: <green | waiting on X>
**Root cause:** <one or two lines, with path:line>
**Fix:** <one line per phase>
**Verified:** <regression test>, failed before the fix and passes after; <checks and results>
**Review:** <cycles run>; <BLOCK/WARN fixed>; <declined, with reasons>
**Docs:** <what was written, or "skipped: reason">
**Issue:** <#N, closed by the pull request | none>
**Admin actions:** <what an admin must do before or after merge, or "none">
**Flagged for you:** <out-of-scope problems (suggested follow-up issues), declined findings with reasons, decisions made on your behalf>
```

---

## What this encodes

- **Regression test first.** It reproduces the reporter's scenario and fails before the
  fix. Without that, nothing proves the fix fixes the report.
- **Fix the pattern, not the instance,** within scope. When the same defect is in a
  sibling handler, the planner names it; the person decides whether it belongs here or
  in a follow-up issue.
- **State outlives the fix.** ClickUp tasks, Slack messages and DynamoDB items written
  while the bug was live may still be wrong. Fix them, or say why they can't matter.
- **The seams are where this repository breaks.** A fix in the code that needs a new
  environment variable, grant, configuration key or deploy-role name isn't done until
  the template has it too.

Example: `/bug-fix #74` plans escaping the kiln drop-off page's names and IDs with
`html.escape` and replacing the exception text on its error page with a plain message,
with one test for each.
