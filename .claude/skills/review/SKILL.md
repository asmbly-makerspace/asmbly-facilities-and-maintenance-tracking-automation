---
name: review
description: Run a structured code review of the current branch with the specialist reviewers (infra, Lambda, docs) and the lead's cross-cutting checks, and return BLOCK / WARN / NOTE findings with a merge verdict. Also checks a plan phase's deliverables, and can run several independent review cycles with fixes between them. Use when asked to review a branch, a phase, or a pull request's changes.
argument-hint: "[phase | N cycles | just infra|lambda|docs | against <branch>]"
model: sonnet
effort: high
---

You run a structured code review for the Facilities Automation Hub: you pick the
specialist reviewers that match the changed files, apply each one's checklist, add the
lead's cross-cutting review, and give one report with a verdict.

The request (may be empty):

```
$ARGUMENTS
```

---

## Step 1: Parse the request

**Mode:**

- **Multi-cycle:** "three cycles", "2 cycles", "two passes", "independent reviews",
  "thorough review", "deep review". Separate reviewers look at the branch cold, one after
  another, with fixes applied between them. Default count 3 unless a number is given.
- **Phase:** "phase", "current phase", "plan", "deliverables". Also checks the phase
  doc's deliverables. Multi-cycle and phase mode combine; the deliverables check runs in
  cycle 1 only.
- **On-demand:** everything else, including empty input.

**Base:** "against main", "vs stage", or a commit: "against <sha>" (`/offshore` passes the
SHA a phase started from, so only that phase is reviewed). If none, detect it in Step 2.

**Scope:** "just infra", "lambda only", "docs only". If none, Step 5 decides from the
changed files.

**Plan and phase hint** (phase mode): "phase 2 of class-photo-upload", "current phase".

---

## Step 2: Detect the base branch

1. An open pull request for this branch: `gh pr view --json baseRefName -q .baseRefName`.
2. Otherwise `stage`.

If the current branch is `stage` or `main` and there is no pull request, stop:

> You're on `<branch>` with no open pull request. I need a feature branch to review, or a
> base: `/review against stage`.

Then set the diff base, `BASE`, once, and use it everywhere below:

- a branch name: `git fetch origin <branch>`, then `BASE=origin/<branch>`;
- a commit SHA (`git cat-file -e <sha>^{commit}` succeeds): `BASE=<sha>`, no fetch.

Shell variables don't carry over between your Bash calls: write the value itself into each
command.

---

## Step 3: Get the diff

```bash
git diff --name-only <BASE>...HEAD
git diff --stat <BASE>...HEAD
```

- No files changed: "No changes between HEAD and `<BASE>`. Nothing to review." Stop.
- More than 100 files: warn and suggest a scope (`/review just lambda`), then continue.

---

## Step 4: Phase context (phase mode only)

1. **Find the plan:** match the hint against `ls -d .implementation_plans/*/ | grep -v DONE`,
   or parse the branch name (`feature/<plan>`). If it's ambiguous, ask one question with
   the list.
2. **Find the phase:** the number given, or the first row of the README's
   `## Phase tracker` that isn't `[x] Complete`.
3. **Read the phase doc:** its `## Files to create`, `## Files to modify`,
   `## Tests`, and `## Acceptance criteria` are the deliverables. For each one, decide
   **DONE**, **PARTIAL**, or **MISSING** from the diff.

---

## Step 5: Map changed files to specialists

| Changed files | Specialist | File |
| --- | --- | --- |
| `template.yaml`, `templates/**`, `template-cicd.yaml`, `samconfig.toml`, `configs/**`, `.github/**` | Infra reviewer | `.claude/agents/review/infra.md` |
| `functions/**`, `layers/common/**`, `scripts/**`, `requirements*.txt`, `pytest.ini` | Lambda reviewer | `.claude/agents/review/lambda.md` |
| `docs/**`, any `README.md`, `CLAUDE.md`, `AGENTS.md` | Docs reviewer | `.claude/agents/review/docs.md` |
| `.implementation_plans/**`, `.claude/**` | none: skip | |

If two or more specialists are needed, also run the lead's cross-cutting review
(`.claude/agents/review/lead.md`). A change to `functions/` almost always needs a look
at its template too: when a function changes and its template doesn't, the lead still
checks that the two agree.

With a scope restriction, run only the named specialists and say in the report which
changed areas were not reviewed.

---

## Step 6: Run the specialist reviews

For each specialist:

1. **Read its file fresh.** Take on its checklist and its output format. Don't review
   from memory.
2. **Read the changed files in its area,** and the files around them that the checklist
   points to (the template for a function, the callers of a helper).
3. **Report only real findings,** BLOCK / WARN / NOTE, with `path:line`. Don't list
   what passed.
4. **Phase mode:** mark each deliverable in its area DONE / PARTIAL / MISSING.

Then move to the next specialist and read its file fresh.

---

## Step 7: Lead cross-cutting review

When two or more specialists ran (or "full" was asked for), read
`.claude/agents/review/lead.md` and do its cross-cutting checks: environment variables
between template and code, IAM against the calls the code makes, configuration keys,
template wiring, the deploy role, shared helpers and their callers, and test patches.

In phase mode, also check that deliverables spanning areas are wired end to end (the
route exists, has its permission, and reaches the function that was built).

---

## Step 7b: Sequential independent cycles (only when asked)

Skip this step unless the request asked for multi-cycle review.

Steps 5 to 7 are **cycle 1**. Then run `N - 1` more cycles, **one after another**, with
fixes between them, so each reviewer sees the state after the previous fixes and spends
its attention on what is still wrong. Parallel cycles would each rediscover the same easy
findings.

### Each cycle

1. **Spawn the reviewer.** Spawn `review-lead` with the Agent tool
   (`subagent_type: review-lead`). If the Agent tool isn't available to you, read
   `.claude/agents/review/lead.md` and the specialist files and run the cycle inline, and
   say in the report that the cycle was not independent.
2. **Wait for its findings.**
3. **Fix between cycles:**
   - **BLOCKs:** fix before the next cycle. If one is contested or needs the person's
     decision, stop and ask.
   - **Obvious WARNs:** small, mechanical fixes (a missing test, a missing grant, a
     missing deploy-role name, a doc line). Fix them.
   - **Other WARNs and NOTEs:** apply the Address-or-Defer rule below.
4. **Commit** the fixes: `chore: address independent review #<N> findings`, with a body
   that lists what was fixed and what was deferred, with reasons.
5. **Re-run the checks** from `CLAUDE.md` ("Done means verified") for what changed.
6. Next cycle.

### The prompt for each cycle

Give the reviewer context only, never your findings or your reasoning:

- the repository path, the branch, and `<BASE>` (from Step 2);
- the phase doc path in phase mode;
- the check status ("pytest 112 passed, cfn-lint clean; don't re-run them");
- `git diff --stat` output;
- the specialist files that match the changed files (Step 5 table);
- that it is a cold review, and that earlier cycles ran and their fixes are applied: "You
  are reviewing the current state of the branch. Find what is still wrong, or what they
  missed.";
- what to look for: seams between template and code, failure paths, retries and
  timeouts, permissions, callers of changed helpers, tests that mock the thing that is
  wrong;
- the output: a punch list, BLOCK / WARN / NOTE, one line each, `path:line`, at most 20
  findings, with `(defer?)` on anything it thinks belongs in a follow-up.

**Middle cycles:** "This is pass <N>. Earlier passes ran and their fixes are applied.
Find what is still wrong or what they missed: race conditions with retried webhooks,
partial failures between two outside calls, permission gaps, missed callers."

**Final cycle:** "This is the final pass. Look in the corners: empty and missing fields in
payloads, ClickUp or Slack responses that aren't `ok`, error paths that leak details,
mocks with fields the real API doesn't return, resources missing from the deploy role,
docs that describe something the code no longer does."

### Address-or-Defer

For every WARN or NOTE you don't fix right away, choose one:

1. **Fix it now** in this branch. Small and in scope: just do it.
2. **Don't fix it, with a real reason.** A real reason cites a contract, a test, a design
   choice or a tradeoff, with a reference. "Minor", "style", or "later" are not reasons.
3. **Defer it to a follow-up GitHub issue.** This needs the person's explicit go-ahead
   before you open the issue. Don't open it on your own.

For each option-3 candidate, give the person one decision:

- **(a) Fold into this branch:** the extra work (lines, files, risk).
- **(b) Open a follow-up issue:** its title and one-sentence scope.
- **(c) Skip with a real reason:** the reason and its reference.

Then wait for the answer. **Inside `/offshore` or another unattended run,** there is no one
to ask: fold the finding in if it is small and in scope; otherwise record it in the
run's report (the briefing's "Deferrals & Blockers") with options (a)/(b)/(c) and your
recommendation, and don't open the issue.

### Reconciliation

After the last cycle:

1. List what each cycle's fixes changed.
2. Highlight findings the final cycle caught that earlier ones missed.
3. Adjust the verdict if any BLOCK is still open.
4. Fill in the Deferrals Rollup (Step 8).

Recommend multi-cycle for changes to IAM or the deploy role, new public routes, anything
that handles secrets or personal data, and diffs over 600 lines. A typo fix doesn't need
it, but if someone asks for it, run it.

---

## Step 8: The report

```markdown
## Review: <one line on what changed>

**Mode:** <On-demand | Phase: <plan> phase <N>> <+ Multi-cycle (N)>
**Base:** `<BASE>` (from <the request | the pull request | default>)
**Files changed:** <count>
**Specialists:** <list>
```

Phase mode adds:

```markdown
### Phase completeness: <plan> phase <N>

| # | Deliverable | Status |
| --- | --- | --- |
| 1 | <text> | DONE / PARTIAL / MISSING |
```

Then the findings:

```markdown
### Cross-cutting
<lead's findings, or "Single area: no cross-cutting review needed.">

### Infra
<findings, "No issues found.", or "No infra files changed.">

### Lambda
<findings, "No issues found.", or "No Lambda files changed.">

### Docs
<findings, "No issues found.", or "No docs changed.">
```

Multi-cycle adds a **Cycle reconciliation** section: per cycle, the finding counts, what
was fixed before the next cycle, and what was deferred; then the final-cycle catches and
the findings more than one cycle flagged.

### Deferrals Rollup

Required whenever a WARN or NOTE was not fixed.

**Part A: already decided.**

| # | Finding | Cycle | Decision | Reference |
| --- | --- | --- | --- | --- |
| 1 | <one line, path:line> | <N> | Fixed / Not fixed: real reason | <commit SHA, or the reason and its reference> |

If you can't fill in the Reference cell, the finding isn't decided: move it to Part B.

**Part B: waiting on the person.** One block per option-3 candidate:

```markdown
**Candidate 1: <one line, path:line>** (cycle <N>)
- (a) Fold into this branch: <work, files, risk>
- (b) Open a follow-up issue: "<title>": <scope>
- (c) Skip: "<reason>": <reference>

Recommendation: <a|b|c>, because <one line>. Tell me which and I'll do it.
```

While Part B has entries, don't open issues or change plan documents for them.

### Verdict

```markdown
### Verdict: APPROVED / CHANGES REQUESTED / NEEDS DISCUSSION

### What's good
- <brief>
```

- **APPROVED:** no BLOCKs; in phase mode, every deliverable DONE.
- **CHANGES REQUESTED:** any BLOCK; in phase mode, any deliverable MISSING.
- **NEEDS DISCUSSION:** a finding needs a person's judgment, or a deliverable is PARTIAL
  and it's unclear whether that's intended.

### Keep it short

Scale each finding to its fix:

- **Simple** (add a grant, add a deploy-role name, escape a value): one sentence.
  > **`templates/ceramics.yaml:61`**: the function reads `KILN_CONFIG_PARAM_NAME` but
  > the policy has no `ssm:GetParameter` on it. Add the parameter ARN to the statement at
  > line 58.
- **Moderate** (logic, a missing failure path): two or three sentences: what, the risk,
  the fix.
- **Subtle** (a security gap, a retry race, a seam between template and code): lead with
  the issue and the fix, then the failure scenario.

Collapse a specialist with no findings to one line. Skip specialists whose area didn't
change. Don't pad.

---

## Errors

- Not a git repository: say so and stop.
- On `stage` or `main` with no pull request: Step 2.
- No changes: Step 3.
- `gh` unavailable: skip pull request detection and use `stage`.
- Plan or phase not found: list what exists and ask.

## Notes

- Read each specialist's file before its review, every time.
- In phase mode, the phase doc says what should have been built; the diff says what was.
  Check both.
- Don't rewrite code in steps 1 to 8: flag issues and describe the fix. The only edits
  you make are the fixes between cycles in Step 7b.
- The specialists' voices differ: the lead is blunt, the Infra reviewer precise, the
  Lambda reviewer clinical, the Docs reviewer warm but firm.
