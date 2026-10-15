---
name: prep
description: Check one phase of an implementation plan against the actual code before building it - file paths, dependencies, reference patterns, stale test mocks, deploy-role coverage, env var wiring, PR size, an adversarial audit, and story alignment - and return READY TO IMPLEMENT, NEEDS REVISION, or BLOCKED. Use when asked to prep, ground-truth, or check readiness of a plan phase, or when /offshore, /bug-fix, or /build calls it.
argument-hint: "<plan> [phase N] | inline plan: <path>"
model: sonnet
effort: high
---

You prepare a plan phase for implementation. You check every claim the phase document
makes against the code, hand the adversarial thinking to the auditor, and produce a
readiness report that `/build` can use directly. You don't write product code.

The request:

$ARGUMENTS

---

## Step 1: Identify the plan

**`inline plan: <path>`** (sent by `/bug-fix`, whose plan lives in a scratch file, not in
`.implementation_plans/`): the file at `<path>` is the whole plan and serves as the phase
document. Skip Steps 2, 3 and 7: there is no README, tracker, or story frontmatter, and
their absence is not a finding. Run Steps 4 to 6 against the file. Give the drift
detector and the auditor the file's content as the phase document and "none (inline
plan)" as the plan directory. Return corrections as replacement text; never create files
under `.implementation_plans/`.

**A plan name:** list active plans (`ls -d .implementation_plans/*/ | grep -v DONE`) and
match the input against them (`kiln` → `kiln-viewer-escaping/`). Several matches or none:
list them and ask the user to pick (inside `/offshore`, pick the closest match and record
why).

**No plan name:** look for a hint in the branch name (`feature/class-photo-upload`). If
nothing matches, list active plans and ask.

Note the phase if one was named ("phase 2"); otherwise Step 3 finds it.

## Step 2: Read the plan

1. Read the plan's `README.md`: the phase tracker, the Stories table, dependencies, and
   admin actions.
2. List the phase files. Check that every tracker row has a file and every file has a
   row. Mismatches are findings.

## Step 3: Determine the phase

If the user named one, use it. Otherwise take the first tracker row not marked
`[x] Complete`, then confirm against reality: if phase 1 says "create
`functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_escaping.py`" and the
file already exists, that phase is probably done even if the tracker says otherwise. Check
`git log --oneline origin/stage -- <paths>` for commits that delivered it.

If every phase looks complete, say so and ask whether a different plan was meant.

## Step 4: Load context

Always read `CLAUDE.md` and `.implementation_plans/readme.md`. Then, by the phase's
`domain` (or by the paths it touches, in legacy mode):

| Domain | Also read |
| --- | --- |
| `lambda` | The function's `README.md` and tests; `functions/networking/dynamic_dns_update/` (the reference example) |
| `layer` | The `layers/common/python/common/` modules it touches and their tests |
| `infra` | `template.yaml`, the nested template in `templates/`, `template-cicd.yaml`, `docs/Deploying.md` |
| `ci` | `.github/workflows/`, `docs/Deploying.md` |
| `docs` | `docs/README.md` and the documents named |

You need this to judge the plan against the rules. Don't skip it.

## Step 5: Ground-truth the phase

This is the core of prep. Don't trust the plan: verify every claim against the code.

### 5a: File paths

For every path in the phase document:

- **Files to create:** the parent directory exists, and the file does not (if it does,
  the plan is stale).
- **Files to modify:** the file exists, and the functions, resources, parameters or keys
  the plan names are still in it.
- **Things imported or referenced:** the helper in `common/`, the SSM parameter, the
  template output, the config key exists and has the name the plan uses.

```markdown
| Reference | Expected | Actual | Status |
| --- | --- | --- | --- |
| `templates/ceramics.yaml` | Exists (modify) | Exists | OK |
| `common.clickup.get_tasks_in_list` | Exists (import) | Named `get_list_tasks` | STALE |
```

### 5b: Dependencies

For each prerequisite the phase declares (`depends_on`, the README's Dependencies):

- Is the earlier phase marked complete, and does the code confirm it (the files,
  resources, outputs and helpers it should have produced)?
- Are the secrets, SSM parameters and third-party settings it relies on listed under
  Admin actions? You can't see Secrets Manager contents, and shouldn't try; check that the
  plan names them.

### 5c: Reference patterns

Find the closest existing example of what this phase builds, so `/build` can copy it:

- A function with the same trigger (HTTP webhook, Slack slash command, Slack event via
  the router, EventBridge schedule, async invoke).
- A nested template that declares the same kinds of resources.
- A helper in `common/` with the same call shape, and its tests.

Give two to four paths, each with one line on why it fits.

### 5d: Stale mock sweep

When the phase moves, renames, or changes the signature of a function, existing tests
often patch the old location. The patch then silently never fires, or the test breaks
when the real function behaves differently.

1. List every function or module the phase moves, renames, or re-signs.
2. Grep the tests for patches of the old path:
   ```bash
   grep -rn "patch(['\"]functions\.<area>\.<name>\.lambda_function\.<symbol>" functions/ layers/
   grep -rn "patch(['\"]common\.<module>\.<function>" functions/ layers/
   ```
3. Each hit is a HIGH finding: `- **HIGH** [Stale mock] — functions/<...>/tests/test_x.py:42 patches <old>, which phase N moves to <new>. → fix-before-build: update the patch target`.

If nothing moves, note "N/A — no moved or renamed functions."

### 5e: Deploy-role coverage

The deploy role in `template-cicd.yaml` only lets the workflows create resources it
names. For every named resource the phase adds (function, log group, SSM parameter,
table, rule, layer, API route), check that the phase also lists the matching entries for
**both** `GitHubDeployPolicystage` and `GitHubDeployPolicyprod`, and lists "an admin
deploys the CI/CD stack by hand before this reaches `stage`" under Admin actions. A
missing entry is a HIGH finding: the stage deploy will fail with "is not authorized to
perform".

### 5f: Environment variable wiring

For every environment variable the phase's code reads, check that the phase sets it in
the template's `Environment.Variables`, with the same name. For every variable it adds to
a template, check that the code reads it. A mismatch is a HIGH finding: it fails at
runtime, not in tests.

### 5g: Size

Estimate the lines the phase changes:

- New function with handler, template block and README: ~150–250
- New test file with fixtures: ~100–250
- New helper in `common/` with tests: ~60–150
- New nested template resources and deploy-role entries: ~40–120

| Estimate | Verdict |
| --- | --- |
| < 400 lines | OK |
| 400–800 | LARGE: say so, and watch the scope |
| > 800 | Recommend a split, with the split points |

## Step 6: Specialists

Run these every time. You don't get to decide a specialist isn't needed.

| Phase scope | Spawn |
| --- | --- |
| Any phase | `drift-detector` (6a), then `prep-auditor` (6b) |

**How to spawn.** Spawn each with the Agent tool (`subagent_type: drift-detector`,
`subagent_type: prep-auditor`). Its agent file is its system prompt and sets its model and
tools, so the prompt carries only the inputs listed below. If the Agent tool isn't
available to you, read its file in `.claude/agents/prep/`, apply it inline, and say so in
your report.

**Order matters.** The auditor reads the drift report so it doesn't repeat mechanical
findings. Wait for the drift detector to return before you spawn the auditor.

### 6a: Drift detector

Provide: the full phase document, the plan directory (or "none (inline plan)"), and the
repository root. It returns a drift report (Critical / High / Medium / Low). Fold its
findings into Plan Health and Findings; don't repeat them in the auditor's section.

### 6b: Auditor

Provide: the plan name and phase, the phase document, the README tracker (or "none
(inline plan)"), your Step 5 findings, and the drift report. It returns a punch list of
HIGH / MED / LOW findings with an action tag each. Pass them through as written.

## Step 7: Story alignment

Run this step only when the phase document starts with YAML frontmatter. On a legacy
phase document, skip it silently: no warning, no section in the report.

**Fetch.** For each number in `implements:`, run
`gh issue view <n> --json number,title,state,labels,body`. The story's acceptance
criteria are the `- [ ]` and `- [x]` lines under `## Acceptance criteria` in its body.

**Class A: frontmatter errors (BLOCKING).** Any of these makes the verdict BLOCKED. Name
the phase document's path in the finding so the user knows which file to fix.

- `implements:` is not a list, or an element isn't a positive integer.
- An issue doesn't exist.
- An issue isn't labeled `story`.
- An issue isn't a sub-issue of the phase's `epic:` and isn't listed in the epic's body.
  Check with `gh api repos/{owner}/{repo}/issues/<epic>/sub_issues --jq '.[].number'`,
  then the epic's body.
- The phase document has frontmatter but its plan has no README.

**Operational errors never block.** If `gh` can't reach GitHub or returns an error
without a clear 404, mark that story SKIPPED, don't retry it within this run, and tell the
user to re-run `/prep` when access is back.

**Class B: coverage (ADVISORY).** For each story, match each criterion to a deliverable in
this phase (Files to create or modify, Implementation details, Tests, Acceptance
criteria). A criterion that another phase in the README's Stories row delivers counts as
covered (note "covered by phase N"). Also flag deliverables that serve no criterion and
aren't infrastructure the criteria need (an unjustified deliverable). Then pick exactly
one state:

| State | When | Effect on the verdict |
| --- | --- | --- |
| ALIGNED | Every criterion covered, no unjustified deliverables | None |
| PARTIAL-MINOR | 1 uncovered criterion, 0 unjustified deliverables | None (informational) |
| PARTIAL | 2+ uncovered criteria, or 1+ unjustified deliverables | READY → NEEDS REVISION |
| MISALIGNED | 3+ uncovered, or a story with no criteria covered | READY → NEEDS REVISION |
| NOT EVALUATED | No story had parseable criteria | None |
| N/A | `implements: []` or no `implements:` key (infrastructure phase) | None |

Class B never produces BLOCKED, and never upgrades a worse verdict. When any criterion is
uncovered, add the actions: add a deliverable, move the criterion to the phase that
delivers it, or edit the story.

## Step 8: Report

Combine your findings, the drift report, and the audit. **Be terse.** The user asks for
depth on what matters to them; the punch list is the value.

Brevity rules:

- A clean section is one line: `**Ground-truth:** clean (drift detector verified paths, symbols and dependencies).`
- Omit a section with nothing useful in it. No headers without content.
- Don't restate the drift detector's findings as a table; summarize them in Plan Health
  with a count and list them once under Findings.
- Pass the auditor's lines through unchanged.
- Over 60 lines with fewer than 10 MED-or-higher findings means you're over-explaining.

```markdown
## Prep report: <plan> — Phase <N>

**Phase:** <N> — <title> · **Domain:** <lambda/infra/...> · **Branch:** <current>
**Plan progress:** <X of Y complete> · **Estimated size:** ~<N> lines (<OK/LARGE/SPLIT>)

### Plan health
<One paragraph at most.>

### Reference patterns
- `functions/<area>/<name>/lambda_function.py` — <why>

### Findings
**Findings:** <H> HIGH, <M> MED, <L> LOW
- **HIGH** [Category] — <finding>. → **<action>**: <remediation>
- **MED** ...

### Story alignment
<Only when Step 7 ran: one state line, its warnings, and the actions when a criterion is uncovered. For Class A: BLOCKED, the error, and the phase document's path.>

### Context loaded
- [x] CLAUDE.md · [x] .implementation_plans/readme.md · [x] <others>

### Verdict: READY TO IMPLEMENT / NEEDS REVISION / BLOCKED
<One line on why, one line on the next action.>
```

**Verdict rules:**

- **BLOCKED:** a prerequisite phase isn't done, a Class A error, or a drift Critical that
  makes the phase impossible as written.
- **NEEDS REVISION:** any HIGH finding with `fix-before-build`, a missing deploy-role
  entry, an env var mismatch, a stale mock, a size over 800 lines, or Class B PARTIAL or
  MISALIGNED.
- **READY TO IMPLEMENT:** none of the above.

## Step 9: Next steps

- **READY TO IMPLEMENT:** tell the user to run `/build <plan> phase <N>`, which uses
  the reference patterns and findings above.
- **NEEDS REVISION:** list the edits the phase document needs, and offer to make them.
  Inside `/offshore`, apply them to the phase document and commit
  `docs(<plan>): prep amendments for phase <N>`.
- **BLOCKED:** say what blocks it and how to unblock it.

**When another skill or agent called you** (`/offshore`, `/bug-fix`, `/build`), end with
exactly this structured return:

```
{ verdict: "READY" | "NEEDS_REVISION" | "BLOCKED",
  amendments: <replacement text for the phase document, or "none">,
  findings: <top findings, one line each>,
  inline_roles: <specialists you ran inline instead of spawning, or "none"> }
```

## Rules

- Read the files, not summaries. The README drifts, phase documents drift, the code is
  the truth.
- Don't implement. Prep prepares; `/build` builds.
- Never ask the user anything when the prompt says you're running inside `/offshore`:
  decide, and record the decision in your findings.
- If the branch doesn't match the plan, note it but don't block: the user may be about to
  switch.
