# Working with AI Agents

This repository comes with a team of AI agents for [Claude Code](https://code.claude.com).
They plan work as GitHub issues, turn the issues into a phased plan, build each phase with
tests, review it with a reviewer that has never seen the code, write the docs, and open a
pull request. A person still decides what gets built, merges, and does anything that
needs admin rights in AWS, Slack or ClickUp.

You don't need the agents to contribute. Everything they do follows the same rules a
person follows: [CONTRIBUTING.md](CONTRIBUTING.md), [Branching Strategy.md](Branching%20Strategy.md)
and [Deploying.md](Deploying.md).

## Table of Contents

- [How it fits together](#how-it-fits-together)
- [Getting started](#getting-started)
- [The skills](#the-skills)
- [Common journeys](#common-journeys)
- [The agent team](#the-agent-team)
- [What agents never do](#what-agents-never-do)
- [What a person still does](#what-a-person-still-does)
- [Changing the agents](#changing-the-agents)

## How it fits together

```
/plan-product ──► epic + story issues on GitHub
      │
/plan-tech ─────► .implementation_plans/<plan>/  (README + one doc per phase)
      │
      ├─ for each phase:  /prep ──► /build ──► /review
      │
/write-docs ────► function READMEs, docs/README.md
      │
pull request ───► stage  (deploys the stage stack)  ──► /promote ──► main  (deploys prod)
```

`/offshore` runs that whole chain by itself and stops at a green pull request to `stage`.

## Getting started

1. Install Claude Code and open it in the repository's root folder.
2. Claude Code reads [CLAUDE.md](../CLAUDE.md) on its own: the rules every agent follows.
   Other tools read [AGENTS.md](../AGENTS.md), which points to the same rules.
3. Set up the checks the agents run (see [CONTRIBUTING.md](CONTRIBUTING.md), "Running Tests"):

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt cfn-lint
   ```

   Install the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
   for `sam validate` and `sam build`, and the [GitHub CLI](https://cli.github.com/)
   (`gh auth login`) for issues and pull requests.
4. Type `/` in Claude Code to see the skills below.

`.claude/settings.json` lets the agents run the tests, the template checks, and read-only
`git` and `gh` commands without asking you each time. Anything else asks first.

## The skills

| Skill | What it does | It asks you |
| --- | --- | --- |
| `/plan-product <idea>` | Turns an idea into an epic issue and story issues with acceptance criteria. `--epic <N>` adds stories to an epic; `--review <plan>` checks a plan against its stories. | To approve the stories before it creates them |
| `/plan-tech <plan or epic>` | Writes `.implementation_plans/<plan>/`: a README and a document per phase, with files, tests, and admin actions | To approve the phase breakdown |
| `/prep <plan> [phase N]` | Checks a phase document against the code: do the files exist, are the deploy-role names planned, what could go wrong | Only if the plan is ambiguous |
| `/build <plan> [phase N]` | Builds a phase: plans the files, writes code and tests, runs the checks, reviews itself, then gets an independent review | Rarely |
| `/review [against <branch>]` | Reviews the branch as specialists would: templates, Python, docs, and the seams between them. "three cycles" runs three independent reviewers in turn | Before opening follow-up issues |
| `/write-docs` | Updates the function READMEs and `docs/` for what changed | To approve its list of documents |
| `/offshore <idea or plan>` | All of the above, unattended, then a pull request to `stage`, a manual QA document, and a briefing | Never |
| `/bug-fix <description or #N>` | Plans the fix, writes a failing test first, fixes, reviews, and opens a pull request to `stage` | Only for open questions |
| `/address-pr-comments <N>` | Fixes or answers every comment on a pull request, and fixes failing checks | Rarely |
| `/promote` | Opens the pull request from `stage` to `main` and, when you say so, merges it and watches the prod deploy | To merge |
| `/rigor` | Tells the agent it cut corners: stop, re-check, and redo it properly | — |

## Common journeys

**A bug with an issue.** `/bug-fix #74`. You get a pull request to `stage` with a test
that failed before the fix and passes after it.

**A feature, step by step.** `/plan-product` with a paragraph about what people should be
able to do. Approve the stories. `/plan-tech <plan-name>`, approve the phases. Then for
each phase: `/prep`, `/build`, `/review`. Push and open the pull request to `stage`.

**A feature, unattended.** `/offshore <description>`. The shared settings only let agents
run the tests, the template checks and read-only `git` and `gh` commands without asking.
An unattended run also edits files, commits, pushes, and creates issues and a pull
request, so start it in a permission mode that allows those, or it will wait for you at
the first prompt. The guardrail hook below still applies in any mode. Come back to a green
pull request, `.implementation_plans/<plan>/BRIEFING.md` (start with its **Admin
actions**), and `MANUAL_QA.md`. For a very large plan, `/loop 10m /offshore <plan>` lets
it continue across sessions.

**A release.** After the pull request merges to `stage`, the stage deploy runs. Do the
manual QA on the stage stack, then `/promote`.

## The agent team

The skills are orchestrators. They hand the work to agents in `.claude/agents/`:

| Team | Agents | Used by |
| --- | --- | --- |
| Product | `domain-expert`, overlap analyst, acceptance-criteria reviewer | `/plan-product` |
| Planning | plan lead, infra planner, Lambda planner, `bug-planner` | `/plan-tech`, `/bug-fix` |
| Prep | `drift-detector`, `prep-auditor` | `/prep` |
| Build | architect, coder, critic, validator, fixer | `/build` |
| Review | `review-lead`, infra reviewer, Lambda reviewer, docs reviewer | `/review`, `/build` |
| Docs | `scribe` | `/write-docs` |

Most agents are perspectives that a skill reads and adopts in its own context. The ones in
`code font` above run as **separate subagents** with a fresh context, for one reason:
a reviewer who watched the code being written shares the writer's blind spots. The
independent `review-lead` reads only the diff and the rules. Each of those agents has a
model and an effort level chosen for its job (in its file's frontmatter).

The reviewers check this repository's real failure points: an environment variable the
template sets but the code never reads (or the other way round), an IAM statement that
doesn't match the AWS calls the code makes, a new resource the deploy role doesn't know
about, a nested-template parameter the root template never passes, and a route without
its invoke permission.

## What agents never do

These rules are in [CLAUDE.md](../CLAUDE.md), and every agent follows them:

- deploy (`sam deploy`) or change anything in AWS;
- push to `stage` or `main`, or merge a pull request without being told to;
- skip or delete a failing test, or bypass hooks with `--no-verify`;
- force-push without `--force-with-lease`;
- log or return secrets, tokens, or people's personal details.

During `/offshore`, nobody is watching, so `.claude/hooks/offshore-guardrails.sh` also
blocks the commands it can recognize: deploys and AWS commands that change something,
pushes to `stage` or `main`, `gh pr merge`, force pushes without a lease, `--no-verify`,
`git commit --amend`, `git reset --hard`, and questions to you. It can't see whether a
test was skipped or what a log line contains; the reviewers check those. It is a
guardrail, not a sandbox: it checks commands, not code that a script runs.

## What a person still does

- **Decide.** Approve stories and phases; answer the questions a plan can't settle.
- **Admin actions.** Every plan, pull request and briefing lists them. The common ones:
  - redeploy the deploy role (`template-cicd.yaml`) when a change adds a named AWS
    resource, **before** the change reaches `stage` ([Deploying.md](Deploying.md),
    "How to Manage the Deployer Role");
  - create secrets in Secrets Manager;
  - point Slack, ClickUp, Smartwaiver or the Google Apps Script at a new URL.
- **Merge** the pull request to `stage`, run the manual QA on the stage stack, and merge
  the `/promote` pull request to `main`.

## Changing the agents

The skills are in `.claude/skills/<name>/SKILL.md`, the agents in `.claude/agents/`, and
the guardrail hook in `.claude/hooks/`. Change them with a pull request like any other
code, and keep [CLAUDE.md](../CLAUDE.md) and this document in step with them. The plan
format is in [.implementation_plans/readme.md](../.implementation_plans/readme.md).
