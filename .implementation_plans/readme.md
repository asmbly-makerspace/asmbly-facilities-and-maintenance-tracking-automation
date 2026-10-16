# Implementation plans

A plan says how a piece of work is built, in phases. `/plan-tech` writes it, `/prep`
checks a phase against the code, `/build` builds a phase, and `/offshore` runs the whole
plan. The stories it delivers live in GitHub Issues, written by `/plan-product`.

The rules in [`CLAUDE.md`](../CLAUDE.md) win over a plan. When a plan asks for something
the rules forbid (a hardcoded ID, a route that doesn't check its caller, a resource
without `${Stage}` in its name), say so and follow the rules.

## Layout

```
.implementation_plans/<plan-name>/
├── README.md              # overview, stories, phase tracker, dependencies
├── phase-1-<slug>.md      # one document per phase
├── phase-2-<slug>.md
├── CHECKPOINT.json        # /offshore only: run state, so a stopped run can resume
├── MANUAL_QA.md           # /offshore only: acceptance steps for a person, by story
└── BRIEFING.md            # /offshore only: what happened during the run
```

- The plan name is kebab-case and says what the work is: `class-photo-upload`,
  `kiln-viewer-escaping`. No "plan" or "implementation" in it.
- Phase files are `phase-N-<slug>.md`; sub-phases are `phase-Na-<slug>.md`.
- No screenshots or other images in a plan folder.
- When every phase is on `main`, move the folder to `DONE/` in a `chore:` pull request.

## README.md

Start with this frontmatter when the plan has an epic. Leave it out entirely when it
doesn't (legacy mode): no empty block, no `epic: null`.

```yaml
---
plan: class-photo-upload
epic: 80            # the epic issue's number
---
```

Then these sections:

- `# <Name>: implementation plan` and `**Created:** YYYY-MM-DD`.
- `## Overview`: the problem and the outcome, in a few sentences.
- `## Stories`: one row per story issue: `| Story | Title | Phases |`. A story that
  more than one phase delivers lists them all. Only the pull request that lands the
  last phase in that cell says `Closes #N`; earlier ones say `Refs #N`.
- `## Phase tracker`: `| Phase | Title | Domain | Size | Status |`, with Status
  `[ ] Pending` (written by `/plan-tech`), `[~] In progress` (set by `/build` when it
  starts the phase), or `[x] Complete` (set by `/build` when it finishes).
- `## Dependencies`: what must exist first (other plans, secrets, third-party setup),
  and which phases depend on which.
- `## Parallelism`: for each pair of phases with no dependency between them, whether
  they can run at the same time, and the shared files that decide it.
- `## Admin actions`: everything a person with admin rights must do, and when:
  secrets to create, the deploy role to redeploy, webhooks and Slack app settings to
  change. Write "None" if there are none.
- `## Related work`: other plans, open issues or pull requests that touch the same
  files or depend on this work. "None" if there are none.
- `## Out of scope` and `## Security`.
- `## Decisions`, only when decisions were made without asking (inside `/offshore`):
  each decision, the alternative, and why.

## Phase documents

Start with this frontmatter when the plan has an epic; leave it out in legacy mode.

```yaml
---
phase_id: 2                  # from the file name: 2, 2a
title: Upload route and Lambda
epic: 80
implements: [81, 82]         # story issues this phase contributes to; [] for pure infrastructure
depends_on: [1]              # phase_ids in this plan; direct predecessors only
domain: [lambda, infra]      # any of: lambda, layer, infra, ci, docs
estimated_size: M            # S (<150 lines), M (<400), L (<800); larger means split it
---
```

Then these sections:

- `# Phase N: <title>` and `> **Status:** [ ] Pending`.
- `## Required reading`: the documents and the existing code to read first, including
  the closest existing example to copy.
- `## Goal`: what is true when this phase is done.
- `## Files to create` and `## Files to modify`: exact paths, and for each, what changes.
- `## Implementation details`: by domain.
  - **lambda / layer:** handler flow, environment variables (each one also in the
    template), secrets and SSM parameters read, outside calls and their failure
    handling, responses for each outcome, what is logged.
  - **infra:** resources with their names, IAM statements, parameters passed from
    `template.yaml`, API routes and their invoke permissions, outputs, and the names to
    add to the deploy role in `template-cicd.yaml`.
  - **ci / docs:** what changes and why.
- `## Tests`: each test, by name, with what it proves. Every failure path the caller can
  hit gets one.
- `## Acceptance criteria`: checkable statements, each traced to a story's criterion
  where there is one.
- `## Verification`: the commands from `CLAUDE.md` that apply, and how to see it work on
  the stage stack after deploy (what to post, click or send, and what should happen).
- `## Admin actions`: this phase's share of the README's list, or "None".
- `## Hand-off`: filled in when the phase is done: what the next phase can rely on.
