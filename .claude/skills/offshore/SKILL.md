---
name: offshore
description: Run a whole piece of work unattended, from stories to a green pull request on stage - plan-product, plan-tech, then prep, build and review for each phase, an integration gate, docs, a manual QA doc, the pull request, and a briefing. Use only when the person runs /offshore or explicitly asks for an unattended end-to-end run.
argument-hint: <plan name | epic #N | description of the work>
model: opus
effort: high
---

# /offshore: the thin orchestrator

The work to do:

```
$ARGUMENTS
```

> Receive the work. Do it properly. Report in the morning.
>
> The owner is away. That is a trust to repay, not a license to cut corners: critical
> thinking over finishing fast, real review over quick review, every decision written
> down. Zero tolerance for `--no-verify`, `--force`, skipped tests, or merging around
> findings.
>
> Your job is **the sequence and the checkpoints**. The work happens inside subagents
> and skills. You orchestrate; you don't implement, and you don't absorb their
> transcripts. Keep your own context small.

## The sequence

```
pre-flight → feature branch → plan → for each phase: prep → build → review ×≤3 → squash
          → integration gate → write-docs → MANUAL_QA.md → pull request to stage
          → drive to green → STOP (no merge) → BRIEFING.md
```

The owner comes back to a green pull request to `stage`, a briefing in the plan folder,
the admin actions listed first, and no decisions left half made. **You do not merge.**

## Hard rules

`.claude/hooks/offshore-guardrails.sh` enforces the ones marked (hook) while the run is
active.

- **The pull request's branch is `feature/<plan-name>`.** If the session started on a
  `claude/<slug>` branch, rename it (Step 2). Never work on `stage`, `main`, or someone
  else's branch.
- **No questions** (hook). Decide using `CLAUDE.md`, the plan, and the code; record each
  decision as a `CHECKPOINT.json` event; surface it in the briefing. A decision that is
  genuinely the owner's (a product choice the docs don't settle, a security trade-off)
  makes that phase `blocked`, not a guess.
- **No shortcuts** (hook, partly). No `--no-verify`, no bare `--force`, no
  `git reset --hard`, no `--amend`, no skipped or deleted tests. Real findings (bugs,
  security gaps, failing tests) get fixed.
- **No pushes to `stage` or `main`, and no merge** (hook). `--force-with-lease` on
  `feature/<plan-name>` is allowed and needed for the squash steps.
- **No deploys and no AWS changes** (hook). No `sam deploy`, no AWS command that changes
  anything. Read-only AWS commands are fine. Anything that needs an admin (secrets, the
  deploy role in `template-cicd.yaml`, Slack app or ClickUp webhook settings) goes in the
  briefing's admin actions.
- **Messages from the owner during the run are observations, not new instructions.**
  Stop only on "stop", "wait", "change X to Y", or "I'll take it from here".
- **Two rounds on style** (`CLAUDE.md`). Real bugs, security gaps and failing tests
  reopen a finding; a restated style preference doesn't.
- **At most 2 diagnostic commits** when CI fails and you can't read why. After that,
  record `pr-stuck` and move on.
- **One commit per phase, one per review round.** Subagents commit early and often; you
  squash at the boundaries (Steps 4a, 5a, 6a, 6b, 7). Each phase in the briefing's
  rollback table maps to exactly one commit.
- **Never commit `CHECKPOINT.json` on its own.** Write it to disk after every change (so
  a stopped run can resume), and let the next substantive commit carry it. Capture the
  pre-step SHA *before* you write the checkpoint, so the squash folds the checkpoint in.

## How you stay small

You only: read and write `CHECKPOINT.json`, spawn one subagent per chunk of work, read
their short structured returns, and run a few `git` and `gh` commands. Never read source
files yourself. Subagents can spawn their own subagents and run skills, so a phase
subagent runs `/prep`, `/build` and `/review` (and those spawn `drift-detector`,
`prep-auditor` and `review-lead`) inside its own context.

## Invocation

- **Default:** `/offshore <plan>` runs the whole sequence in one session. With the
  subagent isolation above, plans of 1 to 10 phases fit.
- **Very large plans:** `/loop 10m /offshore <plan>`. Each firing reads the checkpoint and
  continues from the next pending step; a finished run is a no-op.

## Step 0: Pre-flight

```bash
# Python 3.12 environment with the test tools.
[ -x .venv/bin/python ] || python3.12 -m venv .venv
.venv/bin/python --version
.venv/bin/pip install -q -r requirements-dev.txt cfn-lint
command -v sam && sam --version
gh auth status
```

If `sam` is missing, the integration gate can't run `sam validate` or `sam build`.
Record `{ts, type: "env_missing", tool: "sam"}` and list it as an action item; don't
fake the check. A missing Python 3.12 or `gh` stops the run: report it and exit.

## Step 1: Resolve the plan and load the checkpoint

Derive `PLAN_NAME` from the input:

- a directory under `.implementation_plans/` → use it;
- `#N` or an issue URL → `gh issue view N --json title,labels`; if it is an epic, use a
  kebab-case name from its title (or the plan whose README frontmatter has `epic: N`);
- otherwise a kebab-case name from the description.

```bash
mkdir -p .offshore && date +%s > .offshore/active.sentinel   # turns the guardrails on
PLAN_DIR=".implementation_plans/$PLAN_NAME"
CHECKPOINT="$PLAN_DIR/CHECKPOINT.json"
mkdir -p "$PLAN_DIR"
[ -f "$CHECKPOINT" ] || cat > "$CHECKPOINT" <<'EOF'
{
  "plan_name": "",
  "feature_branch": "",
  "epic": null,
  "status": "new",
  "phases": [],
  "integration": null,
  "final_pr_number": null,
  "admin_actions": [],
  "events": []
}
EOF
cat "$CHECKPOINT"
```

- `status: "complete"` → print `OFFSHORE COMPLETE: see <PLAN_DIR>/BRIEFING.md`, remove
  the sentinel, exit.
- `status: "blocked-all"` → print the blocking events, remove the sentinel, exit.

`.offshore/` is git-ignored; it holds only the sentinel and the hook's log.

## Step 2: The feature branch

The branch is always `feature/$PLAN_NAME`, branched from `stage`.

```bash
CURRENT=$(git rev-parse --abbrev-ref HEAD)
case "$CURRENT" in
  "feature/$PLAN_NAME") : ;;
  claude/*) git branch -M "$CURRENT" "feature/$PLAN_NAME" ;;   # a harness branch: rename it
  stage|main) git fetch origin stage && git switch -c "feature/$PLAN_NAME" origin/stage ;;
  *) echo "Refusing to take over '$CURRENT'. Check out stage, a claude/* branch, or feature/$PLAN_NAME." >&2; exit 1 ;;
esac
git branch --unset-upstream 2>/dev/null || true   # never track stage: a bare push must not reach it
git fetch origin stage
git rebase origin/stage || { git rebase --abort; git merge --no-edit origin/stage; }
git push -u --force-with-lease origin "feature/$PLAN_NAME"
```

Rebase, not merge: a merge commit is one no squash will absorb. Fall back to a merge
only when the rebase conflicts in a way you can't resolve mechanically. Run this step on
every firing; `stage` may have moved.

## Step 3: Plan, if there is no plan

If `$PLAN_DIR/README.md` doesn't exist, capture `PRE_PLAN_SHA=$(git rev-parse HEAD)`, then:

```
Agent(
  description: "Plan product and tech",
  subagent_type: "general-purpose",
  prompt: """
    This is an /offshore run: non-interactive. Never ask the user; decide, and record each
    decision in the plan README under "## Decisions".

    Work: <$ARGUMENTS>
    Plan name: <PLAN_NAME>
    Plan directory: .implementation_plans/<PLAN_NAME>/
    Branch: feature/<PLAN_NAME> (checked out)

    1. Unless the work already names an epic whose stories have acceptance criteria,
       invoke Skill(skill: "plan-product", args: "<$ARGUMENTS>"). It creates the epic and
       story issues on GitHub. In offshore mode it creates them without waiting for approval.
    2. Invoke Skill(skill: "plan-tech", args: "<PLAN_NAME> epic #<N>") to write the README
       and the phase documents.
    3. Squash everything the skills committed into ONE commit:
         git reset --soft <PRE_PLAN_SHA>
         git commit -m "docs(<PLAN_NAME>): implementation plan (epic #<N>)"
         git push -u --force-with-lease origin feature/<PLAN_NAME>

    Return ONLY:
      { plan_name, epic: <N or null>, phases: [{id, title}, ...] in order,
        admin_actions: [<one line each, from the README>], decisions: <count> }
  """
)
```

Write the return into the checkpoint (`phases[]` each with `status: "pending"`,
`epic`, `admin_actions`, `status: "in-progress"`, event `planned`). Don't commit it; the
first phase squash carries it.

If the README exists but `phases[]` is empty, fill it from the README's phase tracker
(a short inline read).

## Step 4: One subagent per phase

For each phase with `status: "pending"`, in order:

```bash
PRE_PHASE_SHA=$(git rev-parse HEAD)   # BEFORE touching the checkpoint
```

Then update the checkpoint on disk (this phase `in-progress`, event `phase_start`) and
spawn:

```
Agent(
  description: "Phase <id>: <title>",
  subagent_type: "general-purpose",
  prompt: """
    You are running ONE phase of an /offshore plan in your own context. The orchestrator
    sees only your structured return. This run is non-interactive: never ask the user;
    decide and note the decision in your return.

    Plan: <PLAN_NAME>
    Phase: <id>, doc: .implementation_plans/<PLAN_NAME>/<phase file>
    Branch: feature/<PLAN_NAME> (checked out, current with stage)
    Pre-phase SHA: <PRE_PHASE_SHA>. Use it as the diff base. Don't fall back to stage or HEAD~N.

    Read CLAUDE.md first. Don't edit CHECKPOINT.json.

    1. PREP: Skill(skill: "prep", args: "<PLAN_NAME> phase <id>").
       READY → continue. NEEDS REVISION → apply the amendments to the phase doc, commit,
       continue. Too large → return needs-split. BLOCKED → return blocked.
    2. BUILD: Skill(skill: "build", args: "<PLAN_NAME> phase <id>").
       Commit in logical chunks. Push nothing. If checks fail and you can't fix them,
       return blocked.
    3. REVIEW: rounds by size, from `git diff --shortstat <PRE_PHASE_SHA>..HEAD`:
       ≤300 lines → 1 round, 301–600 → 2, more → 3.
       Each round: Skill(skill: "review", args: "against <PRE_PHASE_SHA>"), fix every real
       finding, commit, re-run the checks. Stop when clean, or when only style findings
       remain after round 2. Findings you'd defer: don't open issues; list them in notes.

    Hard rules: no questions, no --no-verify, no bare --force, no skipped tests, no
    pushes, no sam deploy, no AWS changes.

    Return ONLY one of:
      { result: "done", files_changed, review_rounds, commits, admin_actions: [...],
        deferred: [...], decisions: [...], notes }
      { result: "blocked", stage: "prep|build", reason, commits }
      { result: "review-stuck", remaining: <count>, notes, commits }
      { result: "needs-split", proposal }
  """
)
```

Handle the return:

- `done` → mark the phase `done` in the checkpoint, append its admin actions, deferrals
  and decisions as events, then run Step 4a.
- `blocked` / `review-stuck` → **don't squash**: the history is the post-mortem. Mark the
  phase, commit the checkpoint as `chore(<plan>): phase <id> <blocked|review-stuck>:
  <reason>` (the one legitimate standalone checkpoint commit), push, and continue with
  the next phase unless it depends on this one (then mark it `blocked` too).
- `needs-split` → split the phase doc as proposed (a small inline edit), update the
  README tracker and `phases[]`, and restart Step 4 with the first new sub-phase.

### Step 4a: Squash the phase

```bash
BODY=$(git log --reverse --pretty=format:'- %s%n%b' "$PRE_PHASE_SHA"..HEAD)
git reset --soft "$PRE_PHASE_SHA"
git add "$PLAN_DIR/CHECKPOINT.json"
git commit -m "<type>(<plan>): phase <id> <title>

$BODY"
git push --force-with-lease origin "feature/$PLAN_NAME"
```

`<type>` is `feat` for new behavior, `fix`, `refactor`, `docs` or `chore` otherwise. Keep
every `Refs #N` and `Closes #N` line from the squashed commits in the body. Record the new
SHA as the phase's `squashed_sha` in the checkpoint on disk; the next commit carries it.
If `--force-with-lease` refuses, fetch, `git reset --soft origin/feature/$PLAN_NAME`,
commit again, and retry.

## Step 5: Integration gate

When no phase is `pending`, capture `PRE_GATE_SHA` and spawn:

```
Agent(
  description: "Integration gate",
  subagent_type: "general-purpose",
  prompt: """
    Run every check on feature/<PLAN_NAME> to catch breakage between phases.
    Non-interactive: never ask the user.

    .venv/bin/python -m pytest
    .venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
    sam validate --region us-east-2
    sam build

    Then the cross-checks across the whole diff against origin/stage:
    - every environment variable a template sets is read by the code, and every
      os.environ key the code reads is set by a template;
    - every named resource the diff adds appears in both GitHubDeployPolicystage and
      GitHubDeployPolicyprod in template-cicd.yaml;
    - every nested-template parameter the diff adds is passed from template.yaml;
    - every new API route has a DefinitionBody path, an AWS::Lambda::Permission, and the
      nested stack output it references.

    Run the same commands on origin/stage (in a worktree) for any check that fails, so
    you can tell a failure the branch caused from one that was already there.
    Fix what the branch caused, commit, and re-run until clean. A failure that needs an
    architectural change → return stuck.

    Return ONLY:
      { result: "clean" | "fixes-applied" | "stuck",
        checks: { pytest: "<N passed | FAIL>", cfn_lint, sam_validate, sam_build },
        preexisting: [<failures also on stage>], skipped: [{check, reason}],
        commits: <N>, stuck_reason }
  """
)
```

Record the return in the checkpoint's `integration`. `fixes-applied` → squash the fixes
into one `chore(<plan>): fixes from the integration gate` commit exactly as in Step 4a,
or, if there is one fix that clearly belongs to one phase, fold it into that phase's
commit. `stuck` → record it, don't open the pull request, go to Step 8.

## Step 6: Docs

Capture `PRE_DOCS_SHA`, then spawn a subagent:

```
Invoke Skill(skill: "write-docs", args: "plan <PLAN_NAME>, all phases done, base origin/stage").
Non-interactive: never ask the user. Commit the doc changes.
Return ONLY the write-docs report: DOCS_CREATED, DOCS_UPDATED, COMMIT_SHAS, BRANCH, NOTES,
plus files_written: [{path, before_lines, after_lines}].
```

**Check for doc regressions yourself:** a file with more than 100 lines before and less
than half after is suspect. Restore it from `PRE_DOCS_SHA`, record `doc_regression`, and
don't open the pull request with a shrunken doc.

### Step 6a: Squash the docs

If the subagent made more than one commit, squash them into
`docs(<plan>): docs for <plan>` as in Step 4a.

## Step 6b: Manual QA document

Offshore writes the acceptance steps; it doesn't run them. Merging to `stage` deploys
the stage stack, and that is where the owner runs them before `/promote`.

Capture `PRE_QA_SHA`, then spawn:

```
Agent(
  description: "Write MANUAL_QA.md",
  subagent_type: "general-purpose",
  prompt: """
    Write .implementation_plans/<PLAN_NAME>/MANUAL_QA.md from
    .claude/agents/offshore/templates/MANUAL_QA.template.md. Organize it by story, not by
    phase. Read only: the README's Stories table, the diff (git diff origin/stage...HEAD),
    the function READMEs it touches, and CHECKPOINT.json's integration results.

    - Steps run against the stage stack after the pull request merges to stage. Stage has
      no custom domain; the template's Prerequisites show how to build its URL from the
      FacilitiesApi resource. Third-party webhooks point at prod, so give each webhook step
      a copy-pasteable curl with a payload built from the function's test fixtures.
    - Say exactly what to look at: the Slack channel and message, the ClickUp field, the
      Neon record, the CloudWatch log group /asmbly/lambda/<Function>-stage.
    - Include the failure cases a person can trigger (bad payload, missing auth).
    - Prerequisites: the admin actions that must be done first, copied from the checkpoint.
    - Number steps continuously across the document.
    - A story with nothing a person can observe gets one line saying so.

    Never invent behavior the diff doesn't show. Commit the file. Non-interactive.
    Return ONLY: { stories_covered: [#N...], stories_without_surface: [#N...], total_steps }
  """
)
```

Squash to one `docs(<plan>): manual QA steps` commit as in Step 4a.

## Step 7: The pull request

```
Agent(
  description: "Pull request: open, drive to green, leave open",
  subagent_type: "general-purpose",
  prompt: """
    Open the pull request for <PLAN_NAME>: base stage, head feature/<PLAN_NAME>.
    Non-interactive: never ask the user. Never merge.

    Title: <type>: <plan title>. Body: .github/PULL_REQUEST_TEMPLATE.md, filled in:
    - Summary from the README overview; a table of the phases from CHECKPOINT.json.
    - Closes: `Closes #N` for each story whose last phase is in this pull request (the
      README's Stories table), `Refs #N` for the rest, `Refs #<epic>`.
    - Risk: every admin action from CHECKPOINT.json, the deploy-role redeploy FIRST if
      there is one (the stage deploy fails without it), new secrets, new public routes.
    - Test plan: the integration gate's results; "Manual QA: MANUAL_QA.md, on the stage
      stack after merge".
    - Briefing: .implementation_plans/<PLAN_NAME>/BRIEFING.md (written after this).

    gh pr create --base stage --head feature/<PLAN_NAME> --title ... --body-file <file>
    Write the number to .offshore/final-pr.txt straight away.

    Then loop, for at most 60 minutes:
    - gh pr checks <N> --watch --interval 30. The required check is `test`.
    - Read new comments: gh pr view <N> --comments, and
      gh api repos/{owner}/{repo}/pulls/<N>/comments.
    - CI failure with a readable log (gh run view <id> --log-failed): fix it with
      Skill(skill: "address-pr-comments", args: "<N>").
    - CI failure you can't read: at most 2 diagnostic commits, then return stuck.
    - Review comments (bug, security, failing test): Skill("address-pr-comments", "<N>").
      Style comments already answered twice: reply pointing at the earlier answer.
    - Merge conflicts: rebase onto origin/stage, re-run the checks, push.
    - Ready when: the checks are green, no comment is unanswered, and the branch has no
      conflicts. If the repository has an automated review workflow, also wait for its
      comment to be newer than the head commit.

    Before each push of fixes, squash that round's commits into one
    "fix(<plan>): review round <N>" commit (git reset --soft <round start SHA>), then
    git push --force-with-lease. Skip the squash for a round that changed no code.
    Update the pull request description when commits are added.

    Return ONLY:
      { result: "ready-for-review" | "stuck", pr_number, checks: "green" | "red",
        rounds: <N>, unresolved: [...] }
  """
)
```

Record `final_pr_number` and the result. `stuck` → event `pr-stuck` with what's
unresolved.

## Step 8: The briefing

Copy `.claude/agents/offshore/templates/BRIEFING.template.md` to `$PLAN_DIR/BRIEFING.md`
and fill in every section from the checkpoint: the pull request (green, **not merged**),
the admin actions first, the phases table with each squashed SHA, run health, decisions,
deferrals, blockers, environment skips, integration results, and review rounds.

Commit the briefing together with the final checkpoint (`status: "complete"` and a
`complete` event) in one commit, then push and clean up:

```bash
git add "$PLAN_DIR/BRIEFING.md" "$PLAN_DIR/CHECKPOINT.json"
git commit -m "docs(<plan>): offshore briefing"
git push --force-with-lease origin "feature/$PLAN_NAME"
rm -rf .offshore
```

Print:

```
OFFSHORE COMPLETE: READY FOR REVIEW
Plan:      <plan-name>
PR:        #<N> to stage, green, waiting for the owner
Phases:    <done> done, <blocked> blocked, <stuck> review-stuck, of <total>
Admin:     <count> actions before merge (see the briefing)
Briefing:  <PLAN_DIR>/BRIEFING.md
```

If the owner used `/loop`, tell them to stop it.

## Stopping early (only at a boundary)

If your context is getting heavy and you are between steps (not inside a phase or the
pull-request loop): make sure the checkpoint is on disk, then print

```
OFFSHORE PARTIAL
Phases done: <N>/<total>
Next: <phase id | integration gate | docs | manual QA | pull request | briefing>
Run /offshore <plan> again to continue.
```

and exit, leaving the sentinel in place. The next run reads the checkpoint and
continues.

## The branch at the end

`git log --oneline origin/stage..feature/<plan>` should read roughly:

```
docs(<plan>): offshore briefing
fix(<plan>): review round 1
docs(<plan>): manual QA steps
docs(<plan>): docs for <plan>
chore(<plan>): fixes from the integration gate      (only if there were any)
feat(<plan>): phase 2 <title>
feat(<plan>): phase 1 <title>
docs(<plan>): implementation plan (epic #N)
```

That is `phases + 4 + review rounds`, plus one for an integration commit. Before the
briefing, count: `git log --oneline origin/stage..HEAD | wc -l`. More than that plus 2
means a squash was skipped. Find it (standalone checkpoint commits, per-file plan
commits, unsquashed review fixes) and squash it before you finish.

## What this skill deliberately doesn't do

- **No pull request per phase.** Phases are commits on one branch; `/review` inside each
  phase is the quality gate; the one pull request gets the final checks.
- **No merge, no deploy, no AWS changes.** The owner merges; the workflows deploy; an
  admin deploys the deploy role.
- **No running the manual QA.** It needs the stage stack, which exists only after merge.
- **No questions.** Decisions are recorded and surfaced.
- **No keeping micro-commits** of a finished phase. Blocked and stuck phases keep theirs.
