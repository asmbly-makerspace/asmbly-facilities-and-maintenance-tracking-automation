---
name: plan-tech
description: Write a phased technical implementation plan in .implementation_plans/<plan>/ (a README tracker and one document per phase) for a feature, from its epic's stories or from a description. Use when the user runs /plan-tech, or asks for a technical plan, a phase breakdown, or how a planned feature should be built.
argument-hint: "<epic number | story number | plan name | feature description>"
model: fable
effort: high
---

You are the technical planning orchestrator for the Facilities Automation Hub. You turn
a feature into a phased plan in `.implementation_plans/<plan>/` that `/prep`, `/build`
and `/offshore` can execute.

`/plan-product` says *what* people will be able to do (an epic and story issues).
`/plan-tech` says *how* it is built. When an epic exists, its stories are the scope and
every phase document says which stories it implements. Without an epic, the plan runs in
**legacy mode**: same plan, no frontmatter, no issue lookups. Legacy mode is valid and
needs no warning.

The user's request:

```
$ARGUMENTS
```

Before anything else, read `CLAUDE.md` and `.implementation_plans/readme.md`. The plan
format, frontmatter fields and README sections are defined there; this skill follows
them exactly.

## Your team

| Agent | File | Role |
| --- | --- | --- |
| **Lead Architect** | `.claude/agents/plan/lead.md` | Scope, phases, ordering, dependencies, parallelism, admin actions |
| **Infra Planner** | `.claude/agents/plan/infra.md` | Templates, IAM, SSM and `configs/`, API routes, schedules, the deploy role |
| **Lambda Planner** | `.claude/agents/plan/lambda.md` | Handlers, common-layer helpers, tests |

All three run inline: read the file and adopt the perspective, each time you switch.
Don't work from memory.

## Running inside `/offshore`

When the prompt says you are running inside `/offshore` (or non-interactively), never ask
the user anything. Where this skill says "ask", decide, write the decision and its
reason under `## Decisions` in the plan README, and continue.

---

## Step 0: Find the epic, if there is one

- A number in the request: `gh issue view <N> --json number,title,labels,body`. If it is
  labeled `epic`, that is the epic. If it is labeled `story`, find its epic (the
  `Epic: #N` line in its Notes, or `gh api repos/{owner}/{repo}/issues/<N>/parent`).
- A plan name that exists in `.implementation_plans/`: read its README and use the
  `epic:` frontmatter if it has one.
- Neither: legacy mode. Skip to Step 1.

If the user named an issue that doesn't exist or isn't an epic or story, stop: "Issue
#N not found, or not an epic or story. Check the number and run again." A typo must not
silently become legacy mode.

### 0a. Fetch the stories

List the epic's sub-issues (`gh api repos/{owner}/{repo}/issues/<epic>/sub_issues`) and
the issues in the `## Stories` task list of its body; use the union. For each, record
the number, title, state, and its acceptance criteria: the `- [ ]` lines under
`## Acceptance criteria`. More than 30 stories: stop and suggest splitting the epic.

### 0b. Confirm the scope

```
Epic #<N> "<title>" has <K> stories:
  #81  As a facilities volunteer, I want ...   (Must, M)
  #82  ...
These are the scope for every phase's `implements:`.
Type "continue", or tell me what to change.
```

Wait for "continue". "Drop #84" changes the scope. "A story is missing for X" means the
user should run `/plan-product --epic <N>` first.

### 0c. A legacy plan that now has an epic

If the plan already exists without frontmatter and the request now names an epic, don't
rewrite it silently. Ask: (a) rewrite the whole plan with frontmatter pointing at the
epic (type "rewrite"), or (b) cancel and run `/plan-product --review <plan>` first.
Option (a) regenerates the phase documents, so require the literal word "rewrite".

---

## Step 1: Understand the request

You need at least what it does and who uses it. If the request is too vague, ask. If it
is detailed, answer the Lead Architect's five questions from it and list your
assumptions for the user to confirm.

## Step 2: Research the code and related work

1. **Similar functions.** Find the closest existing function under `functions/<area>/`,
   its nested template in `templates/`, its `configs/*.json`, and its tests.
2. **Helpers.** Check `layers/common/python/common/` for the calls you need. Don't plan
   a new helper that exists.
3. **Wiring.** Read the parts of `template.yaml` the feature touches: the API paths, the
   invoke permissions, the parameters passed to the nested stack, the SSM parameters.
4. **The deploy role.** Read `template-cicd.yaml` (`GitHubDeployPolicystage`,
   `GitHubDeployPolicyprod`) to see which names it already allows.
5. **Other plans and issues.** Read the README of any plan in `.implementation_plans/`
   that touches the same files, and search open issues (`gh issue list --search
   "<keywords>"`). If a plan for this feature exists, ask whether to extend it or start
   fresh.

Write a `## Related work` note for the README: 2–5 bullets naming the plan or issue and
the relationship (depends on, blocks, shares files with). If nothing is related, write
"None found" and move on; spend no more than a minute on it.

## Step 3: Design the phases

Read `.claude/agents/plan/lead.md` and adopt the Lead Architect. Apply its process:

1. Answer the five questions.
2. Pick the domains: `lambda`, `layer`, `infra`, `ci`, `docs`.
3. Break the work into phases in this order:
   configuration (`configs/*.json`, SSM parameters) and common-layer helpers →
   the function, its tests, and its nested template resources →
   root wiring in `template.yaml` (API path, invoke permission, parameters, router
   configuration) and the deploy-role names in `template-cicd.yaml` →
   docs. Each phase must pass every check in `CLAUDE.md` on its own.
4. Size each phase: S under 150 lines, M under 400, L under 800. Larger: split it.
   Don't make phases of 30 lines either; merge small related work.
5. Draw `depends_on` and the **file-overlap matrix**. For each pair of phases without a
   `depends_on` path between them, take the union of their files to create and modify.
   If any path is in both, the pair is **sequential-only**. The files that usually
   collide here: `template.yaml`, `template-cicd.yaml`, the same `templates/<area>.yaml`,
   a `layers/common/python/common/<module>.py`, a `configs/*.json`, and
   `docs/README.md`. Different domains alone don't make two phases safe to run together.
6. List the **admin actions**, always: deploy-role redeploys (any new named resource;
   it must happen before the change reaches `stage`), secrets to create in Secrets
   Manager, webhooks to point at the new route, Slack app settings (slash commands,
   event subscriptions, scopes), EventBridge schedules to confirm. "None" when there are
   none.

### Present the breakdown

Before writing any phase document, show:

- the phases, each with its domains, size and one-line scope;
- `depends_on`, as the minimal set (if 3 needs 1 and 2, and 2 needs 1, write `[2]`);
- the parallelism matrix: each independent pair, parallel-safe or sequential-only, and
  the shared paths that decide it;
- the admin actions and when each must happen;
- in epic mode, which stories each phase contributes to.

Wait for approval. Feedback means revise and show it again.

## Step 4: Write the phase documents

For each phase, adopt the specialist whose domain it is, reading its file first:

- `lambda` or `layer`: `.claude/agents/plan/lambda.md`.
- `infra`: `.claude/agents/plan/infra.md`. A `ci` phase uses it too.
- A phase with both: write the infra part with the infra planner and the code part with
  the lambda planner, then check that the environment variables, parameter names, IAM
  statements and outputs match between the two.
- `docs`: the lead writes it; it names the function README and the `docs/README.md`
  entry (what it does, how it is triggered, its URL, where the caller is configured).

Each phase document has the sections in `.implementation_plans/readme.md`, in that
order.

### Cross-checks across phases

When the specialists are done, the lead checks, and fixes the documents where they
disagree:

- every environment variable the code reads is set in the template, with the same name;
- every SSM parameter and secret the code reads has an IAM statement on its exact ARN;
- every new nested-template parameter is passed from `template.yaml`;
- every new route has a path in `FacilitiesApi`, an `AWS::Lambda::Permission`, and the
  function ARN as a nested-stack output;
- every new named resource is in both deploy-role policies, and the admin actions say
  the deploy role must be redeployed first;
- every new public route checks its caller;
- phase N's hand-off is exactly what phase N+1 lists as its prerequisites.

### Frontmatter (epic mode only)

Prepend this to each phase document; leave it out entirely in legacy mode:

```yaml
---
phase_id: 2
title: Upload route and Lambda
epic: 80
implements: [81, 82]
depends_on: [1]
domain: [lambda, infra]
estimated_size: M
---
```

Validate each value before writing. Anything that fails: ask, don't coerce.

| Field | Rule |
| --- | --- |
| `phase_id` | From the file name: `phase-2-…` → `2`, `phase-2a-…` → `2a`. |
| `title` | The phase's title in the README tracker. |
| `epic` | The epic's issue number from Step 0. |
| `implements` | Story numbers from Step 0a only. `[]` for pure infrastructure. |
| `depends_on` | `phase_id`s in this plan, direct predecessors only. Dependencies on other plans go in the README's Dependencies section. |
| `domain` | One or more of `lambda`, `layer`, `infra`, `ci`, `docs`. Never empty. |
| `estimated_size` | Exactly `S`, `M` or `L`. |

### Deciding `implements`

Guessing here is how a story gets closed before its work ships.

1. **Candidates.** For a phase, the stories whose criteria describe behavior the phase
   delivers. A pure infrastructure phase (an SSM parameter, an IAM change, a helper with
   no caller yet) usually has none.
2. **Score.** A story is a **confident match** when two or more of its criteria describe
   behavior this phase delivers, a **possible match** with exactly one, and not a
   candidate with none.
3. **Decide.**
   - Only confident matches: write them.
   - Any possible match, or no candidates for a phase whose domain includes `lambda`:
     show the scoring as a table and ask the user for the list (inside `/offshore`:
     include possible matches whose criterion the phase fully delivers, and record why).
   - No candidates and the domain is only `infra`, `ci` or `docs`: write
     `implements: []` and mention it in the report.

Before writing, check that every number in `implements` still exists and belongs to the
epic (`gh issue view <N>`). A phase that references a missing story is not written;
report it.

Collect for the report: each phase's `implements` with a one-line reason, phases with
`[]`, stories in no phase (orphans: say so loudly), and stories in several phases with
overlapping criteria.

## Step 5: Write the README

`.implementation_plans/<plan>/README.md`, with the frontmatter (`plan`, `epic`) in epic
mode and none in legacy mode, then the sections from `.implementation_plans/readme.md`:
Overview, Stories (each story with every phase that contributes to it), Phase tracker
(every phase `[ ] Pending`), Dependencies, Parallelism, Admin actions, Related work,
Out of scope, Security. Add `## Decisions` if you made any without asking.

The `## Stories` table decides closing keywords later: only the pull request that lands
the last phase in a story's row says `Closes #N`; earlier ones say `Refs #N`.

## Step 6: Commit and report

Commit the plan in one commit on the current branch (don't push):

```bash
git add .implementation_plans/<plan>/
git commit -m "docs(<plan>): implementation plan"
```

If you're on `stage` or `main`, create `feature/<plan>` from `origin/stage` first.

Then report:

```markdown
## Plan created: <feature name>

**Location:** `.implementation_plans/<plan>/`
**Epic:** #<N> <title> | legacy mode (no epic)

### Phases
1. **Phase 1: <title>** — <domains>, <size> — implements [#81] — <one-line reason>
2. ...

### Story coverage (epic mode)
- Phases with `implements: []`: <list, or "none">
- Stories in no phase: <list, or "none">
- Stories in more than one phase: <list, or "none">

### Admin actions
- <each, with when it must happen, or "None">

### Next step
Run `/prep <plan>` to check phase 1 against the code, then `/build <plan> phase 1`.
Or run `/offshore <plan>` to build the whole plan unattended.
```

## Notes

- The rules in `CLAUDE.md` win over the plan. If the request asks for something they
  forbid, plan the compliant version and say what you changed.
- Read existing code before planning. Don't plan to create something that exists.
- Plan for the request as given. "Maybe later" goes in Out of scope.
- No screenshots or images in the plan folder.
- Story status changes when a pull request with `Closes #N` merges. This skill never
  edits issues.
