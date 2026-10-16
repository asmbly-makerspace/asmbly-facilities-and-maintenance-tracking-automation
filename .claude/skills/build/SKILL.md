---
name: build
description: Build one phase of an implementation plan (or a set of written instructions) with the build team - architect, coder and critic, validator, self-review, fixer - followed by a mandatory independent review from a fresh review-lead subagent, then mark the phase complete. Use when asked to build or implement a plan phase, or when /offshore or /bug-fix calls it.
argument-hint: "<plan> [phase N] | instructions: <path or text>  [base <sha>]"
model: opus
effort: high
---

You run the build team. You turn a plan phase (or instructions) into working, tested,
reviewed code that follows `CLAUDE.md`. You delegate each part of the job to the right
specialist at the right time and pass context between them.

The request:

$ARGUMENTS

---

## Your team

| Agent | File | Role | When |
| --- | --- | --- | --- |
| Architect | `.claude/agents/build/architect.md` | Maps deliverables to files, build order, risks | Before coding |
| Coder | `.claude/agents/build/coder.md` | Writes the code and its tests | Each build step |
| Critic | `.claude/agents/build/critic.md` | Catches misses between steps | After each build step |
| Validator | `.claude/agents/build/validator.md` | Runs the checks and the standards scan | After coding, after fixing |
| Reviewer | `.claude/agents/review/lead.md` + specialists | Senior review | After validation |
| Fixer | `.claude/agents/build/fixer.md` | Fixes review findings | After review |
| Independent reviewer | subagent `review-lead` | Reviews the branch cold | Last |

All but the independent reviewer are perspectives you adopt. **Read each agent file
before you adopt it, every time you switch.** Don't work from memory.

## Step 1: Identify the work

- **A plan phase** ("phase 2 of class-photo-upload"): find the plan in
  `.implementation_plans/`, read the phase document in full and the README, and check
  that `depends_on` phases are complete in the tracker and in the code. If `/prep` ran,
  use its report.
- **`instructions: <path or text>`** (from `/bug-fix`, or a user with no plan): the
  instructions are the specification. There is no phase document to update at the end.
- **Empty or vague:** look at the branch name and the active plans for the next
  incomplete phase. If it's still unclear, ask (inside `/offshore`, never ask: pick and
  record why).

## Step 2: Load context

Not optional. Read `CLAUDE.md` and `.implementation_plans/readme.md`, then by scope:

| Scope | Also read |
| --- | --- |
| A function | Its `README.md`, `lambda_function.py`, and tests; `functions/networking/dynamic_dns_update/` |
| The shared layer | The modules in `layers/common/python/common/` it touches, and their tests |
| Templates | `template.yaml`, the nested template, `template-cicd.yaml`, `docs/Deploying.md` |
| CI | `.github/workflows/`, `docs/Deploying.md` |

If the phase document contradicts these, the documents win. Say so in the build report.

## Step 3: Branch

If you're on `stage`, `main`, or someone else's branch, create one:
`git fetch origin stage && git switch -c feature/<plan> origin/stage` (`fix/<name>` for a
bug). If you're already on a `feature/`, `fix/`, or `chore/` branch for this work, use
it. Never commit to `stage` or `main`.

Record the base now. If the request says `base <sha>` (`/offshore` and `/bug-fix` pass
the commit the phase started from), use that SHA. Otherwise use
`git merge-base HEAD origin/stage`. Every "base" and `$BASE` below means this SHA; shell
variables don't carry over between Bash calls, so write the SHA itself into each command.

For a plan phase, set its row in the README's phase tracker to `[~] In progress`. It goes
into the first step's commit.

## Step 4: Architect

Adopt the Architect. Input: the phase document (or instructions), the context you
loaded, the code. Output: a build manifest (reference patterns, build sequence, risk
register, scope check).

Show a 5–10 line summary of the manifest and carry on. Don't wait for approval.

## Step 5: Coder and critic loop

For each step in the manifest:

1. **Coder writes.** Adopt the Coder. Follow the manifest's order and reference
   patterns. Tests go in the same step as the code. When the instructions ask for a
   regression test (`/bug-fix` does), write it first, run it, and confirm it fails for the
   reported reason before writing the fix; commit it on its own (`test: reproduce ...`)
   and note the failing output for the report. The template, the deploy role, and
   the code that reads an environment variable change in the same step, so they never
   disagree.
2. **Critic checks.** Adopt the Critic. Check what was just written, and how it fits
   with the earlier steps. Output: CATCH and QUESTION findings, or nothing.
3. **Coder fixes.** Fix every CATCH. Check every QUESTION and fix it if it's real.
4. **Commit the step.** Conventional Commits; reference the story in the body with
   `Refs #N`. Use `Closes #N` only on the last commit of the phase, and only for a story
   whose row in the README's Stories table lists this phase as its last. Don't push
   unless the caller told you to.

Then move to the next step.

## Step 6: Validator

Adopt the Validator. It runs, in order: `.venv/bin/python -m pytest`; for template changes,
`cfn-lint` and `sam validate`; for template, layer, or requirements changes,
`sam build`; then the standards scan over the diff. Output: a validation report.

On failures, switch to the Coder, fix, and re-run the failed checks until it reports
ALL CLEAR. Commit the fixes.

## Step 7: Self-review

Adopt the Lead Reviewer (`.claude/agents/review/lead.md`) and the specialists that match
the changed files (`git diff --name-only $BASE..HEAD`):

| Changed files | Specialist |
| --- | --- |
| `functions/**`, `layers/**`, `scripts/**`, `requirements*.txt`, `pytest.ini` | `.claude/agents/review/lambda.md` |
| `template.yaml`, `templates/**`, `template-cicd.yaml`, `samconfig.toml`, `configs/**`, `.github/**` | `.claude/agents/review/infra.md` |
| `docs/**`, `**/README.md`, `CLAUDE.md`, `AGENTS.md` | `.claude/agents/review/docs.md` |

Read each file fresh before applying it. Produce BLOCK / WARN / NOTE findings. For a plan
phase, also mark each deliverable DONE / PARTIAL / MISSING.

## Step 8: Fixer

Adopt the Fixer. Fix every BLOCK, fix the straightforward WARNs, and defer the rest with
a reason. Commit the fixes.

## Step 9: Validator again

Re-run Step 6 in full. Fixes break things too.

## Step 10: Independent review

**This step is mandatory.** The self-review in Step 7 was done by the agent that wrote
the code: the same assumptions, the same blind spots. A reviewer that never saw the
build catches the wiring bugs self-review misses, such as an environment variable the
template sets under one name and the code reads under another, or an IAM statement on
the wrong parameter ARN.

Spawn the `review-lead` subagent with the Agent tool (`subagent_type: review-lead`). Its
prompt carries only:

- the repository path, the branch, and the base (`$BASE`, branched from `stage`);
- the changed files (`git diff --name-only $BASE..HEAD`) and `git diff --stat $BASE..HEAD`;
- the specialist files from the Step 7 table that match those files (it reads them
  itself; its own file is already its system prompt);
- the phase document's path, if there is one;
- the validation status ("pytest PASS, N passed; cfn-lint PASS; don't re-run the
  mechanical checks");
- "Review the branch cold and return BLOCK / WARN / NOTE findings, one line each, with
  file:line, at most 20."

Never include your reasoning, your build decisions, or the Step 7 findings: that would
contaminate the cold read. If the Agent tool isn't available to you, run the review
inline from `.claude/agents/review/lead.md` and the specialist files, and say in the
final report that the independent review was not independent.

If it returns BLOCKs: adopt the Fixer, fix them, re-run the Validator (Step 9), commit.
Treat its WARNs as in Step 8.

## Step 11: Mark the phase complete

Skip this for instruction-only builds.

1. **The phase document's Status line**:
   `> **Status:** [ ] Pending` → `> **Status:** [x] Complete — YYYY-MM-DD on branch <branch>`.
   Fill in its `## Hand-off` section: what the next phase can rely on (resource names,
   outputs, helper signatures, config keys), and anything deferred.
2. **The README tracker row** for this phase: Status → `[x] Complete`. Touch no other
   row and no other section.
3. **Commit separately**: `docs(<plan>): mark phase <N> complete`.

A merged phase whose document still says Pending is a defect.

## Step 12: Final report

```markdown
## Build complete: <description>

**Phase:** <plan> — Phase <N>: <title> · **Branch:** <branch> · **Files changed:** <N>

### Deliverables
| # | Deliverable | Status |
| --- | --- | --- |
| 1 | ... | DONE / PARTIAL |

### Verification
- pytest: PASS / FAIL (<N> passed, <M> failed)
- cfn-lint: PASS / FAIL / SKIP (no template change) — <pre-existing findings on stage, if any>
- sam validate: PASS / FAIL / SKIP
- sam build: PASS / FAIL / SKIP

### Review
- Self-review: <B> BLOCKs fixed, <W> WARNs fixed, <D> deferred
- Independent review: <B> BLOCKs fixed, <W> WARNs fixed, <D> deferred <or: "run inline, not independent">

### Deferred
- <finding> — <reason, with a reference>

### Admin actions
- <secrets to create, the CI/CD stack to redeploy, webhooks to set>, or "None"

### Regression test (when one was asked for)
- <test name>: failed before the fix (<one-line failure>), passes after

### Next
- `/review` for a formal review, then open a pull request to `stage`.
```

## Errors

- **Plan not found:** list the active plans and ask (inside `/offshore`, return blocked).
- **Prerequisite phase not done:** say what's missing and ask whether to proceed.
- **A check the coder can't fix:** report it with the file, line, and error. Never skip
  or delete the test, and never use `--no-verify`.
- **Scope over ~800 lines:** warn and suggest a split; continue only if the user agrees.
- **Standards conflict:** `CLAUDE.md` wins over the phase document.

Inside `/offshore`, never ask: a missing prerequisite or a phase too large to build makes
you return blocked (or needs-split) with the reason; anything smaller you decide and
record in the report.

## Order of work

Build in dependency order, so nothing references what doesn't exist yet:

1. Configuration (`configs/*.json`) and shared helpers in `common/`, with tests.
2. The function's code and tests.
3. Its template resources, IAM, and the deploy-role entries, together with the code that
   reads them.
4. The wiring: API route, invoke permission, router entry, outputs, parameters passed
   from `template.yaml`.
5. Docs.

Independent pieces (two helpers with no shared file) can be written in parallel.
