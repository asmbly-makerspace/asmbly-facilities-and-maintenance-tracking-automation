---
name: write-docs
description: Write or update the documentation for a change - function READMEs, the service catalogue in docs/README.md, docs/Deploying.md, and CLAUDE.md's map - by handing it to the scribe agent. Use when asked to write or update docs for a change, a plan, or a phase, or when /offshore or /bug-fix calls it.
argument-hint: [plan <name> | phase <id> | description of what changed] [base <branch>]
model: sonnet
effort: medium
---

# /write-docs

Write the documentation for:

```
$ARGUMENTS
```

## Step 1: Gather the inputs

- **Branch and base.** The current branch, and the base: the one named in the arguments,
  else the open pull request's base (`gh pr view --json baseRefName -q .baseRefName`),
  else `stage`. A bare branch name means its remote copy: `git fetch origin <branch>` and
  use `origin/<branch>`, because a local `stage` can be out of date. A ref that already
  starts with `origin/` (fetch the branch after it) and a SHA are used as they are.
- **What changed.** `git diff <base>...HEAD --stat`. If the arguments name a plan, the
  plan's README and the phase documents marked complete.
- **Who is asking.** If this runs inside `/offshore` or `/bug-fix`, or the arguments say
  "non-interactive", the scribe doesn't wait for approval.

If nothing outside `.implementation_plans/` and `.claude/` changed, report
`DOCS_CREATED: none` and stop.

## Step 2: Run the scribe

Spawn the `scribe` agent with the Agent tool (`subagent_type: "scribe"`). Its file,
`.claude/agents/scribe.md`, is its system prompt and sets its model and tools, so pass
only the inputs:

- the branch and the base;
- the changed files, and one or two sentences on what shipped;
- the plan and phase documents, if any, by path;
- whether to wait for approval of its list of documents;
- whether to push (only when the caller asked).

If the Agent tool isn't available to you, read `.claude/agents/scribe.md` and do its
work inline, and say so in the report.

## Step 3: Check the result

- Every file in `DOCS_UPDATED` that had more than 100 lines and now has less than half
  as many is a regression: restore it from the base and tell the scribe once what to
  change instead. A second regression goes into `NOTES`.
- Every route, environment variable, secret and schedule the new text names exists in
  the templates or the code (`git grep` each one).

## Report

Return the scribe's block, with your checks added to `NOTES`:

```
DOCS_CREATED: ...
DOCS_UPDATED: ...
COMMIT_SHAS: ...
BRANCH: ...
NOTES: ...
```

`/offshore` reads this block, and its briefing's action items come from `NOTES`.
