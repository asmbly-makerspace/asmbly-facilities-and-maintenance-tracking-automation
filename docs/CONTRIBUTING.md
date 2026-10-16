# Contributing to Asmbly Facilities, Maintenance, and Tracking Automation

Thanks for helping. This page covers how to make a change here and get it to production.
It is short on purpose: each step links to the document with the details. If this page
and one of those documents ever disagree, the linked document is right; fix this page.

## Table of Contents

- [Start Here](#start-here)
- [From Issue to Production](#from-issue-to-production)
- [Running Tests](#running-tests)
- [Adding a New Lambda Function](#adding-a-new-lambda-function)
- [Coding Standards](#coding-standards)
- [Working with AI Agents](#working-with-ai-agents)
- [AWS and Production](#aws-and-production)

---

## Start Here

1. Read [README.md](README.md) to learn what each service does and how it is triggered,
   and [Architecture Overview](Deploying.md#architecture-overview) to see how the stacks
   fit together.
2. Read [CLAUDE.md](../CLAUDE.md). It is written for AI agents, but its rules are the
   project's rules and apply to you too.
3. Install Python 3.12 and the tools in [Prerequisites](Deploying.md#prerequisites).
   On Windows, tick **"Add python.exe to PATH"** when you install Python. Then set up the
   tests ([Running Tests](#running-tests)).
4. Find the issue for your change in
   [GitHub Issues](https://github.com/asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation/issues),
   or open one. There is no other tracker ([Tracking](../CLAUDE.md#tracking)).

---

## From Issue to Production

```
issue → branch from stage → commits → tests → pull request to stage → review → merge
      → stage stack deploys → check it on stage → pull request stage → main → prod deploys
```

1. **Branch from `stage`.** Never commit to `stage` or `main`. Name the branch
   `feature/<name>`, `fix/<name>`, or `chore/<name>`
   ([Branch Naming Convention](Branching%20Strategy.md#branch-naming-convention)). If you
   have write access, push the branch to this repository. If you don't, fork the
   repository and push to your fork.
2. **Write the change, its tests, and its docs.** Every behavior change comes with a test.
   Update the function's `README.md` and `docs/README.md` in the same change. Commit after
   each logical step, using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`.
3. **Run the checks.** See [Running Tests](#running-tests).
4. **Open a pull request to `stage`.** Fill in every section of the
   [template](../.github/PULL_REQUEST_TEMPLATE.md). The **Risk** section lists the admin
   actions your change needs. Write `Closes #<issue>`, `Refs #<issue>` if the issue isn't
   finished, or `n/a: <reason>` for a chore with no issue.
5. **Get the `test` check green.** It is required on `stage` and `main`, and the branch must
   be up to date with `stage` before it can merge.
6. **Get a review.** At least one other collaborator reviews the pull request
   ([The Workflow](Branching%20Strategy.md#3-the-workflow)). Answer every comment: either
   fixed, with the commit, or not fixed, with the reason
   ([Review discipline](../CLAUDE.md#review-discipline)). If you add commits after opening
   the pull request, update its description so it shows what it finally contains.
7. **Admin actions come before the merge.** If the pull request needs an admin action,
   such as redeploying the deploy role, an admin does it first. Otherwise the stage deploy
   fails ([How to Manage the Deployer Role](Deploying.md#how-to-manage-the-deployer-role)).
8. **Merging deploys the stage stack.** The **Deploy Staging Pipeline** workflow deploys
   it. Then run the manual check from your pull request's **Test plan** against the stage
   stack.
9. **Promote to `main`.** Open a pull request from `stage` to `main` and merge it with a
   merge commit, not a squash. Merging it deploys prod
   ([The Workflow](Branching%20Strategy.md#3-the-workflow), step 6). In Claude Code,
   `/promote` does this step.

---

## Running Tests

The tests use `pytest` and never call the network. Set them up once, from the repository
root:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt cfn-lint
```

Run this for every change:

```bash
.venv/bin/python -m pytest
```

Run these after a change to a template:

```bash
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
```

After a change to a template, a layer, or requirements, also run `sam build`.

On Windows, create the environment with `py -3.12 -m venv .venv`. Its programs are in
`.venv\Scripts\` instead of `.venv/bin/`.

Report what the checks printed, including failures. If a test also fails on `stage`
without your change, say so in the pull request. A check you didn't run is not a pass
([Done means verified](../CLAUDE.md#done-means-verified)).

---

## Adding a New Lambda Function

Copy the shape of [`functions/networking/dynamic_dns_update/`](../functions/networking/dynamic_dns_update/)
and its block in [`templates/networking.yaml`](../templates/networking.yaml). It is the
closest example of how new code should look.

1. **Code.** Put the code in `functions/<area>/<name>/lambda_function.py`, with a
   `lambda_handler` function. Add a `README.md` and a `tests/` folder next to it.
2. **Template.** Add an `AWS::Serverless::Function` to the area's nested template,
   `templates/<area>.yaml`, with `CodeUri: ../functions/<area>/<name>/`. Give it:
   - `${Stage}` in its name
   - its own log group, named `/asmbly/lambda/<FunctionName>-${Stage}`, with a retention
     period
   - a `Project` tag

   If the nested template gets a new parameter, pass that parameter from `template.yaml`.
3. **Deploy role.** Add every new resource name to both `GitHubDeployPolicystage` and
   `GitHubDeployPolicyprod` in `template-cicd.yaml`. In the pull request's **Risk** section,
   say that an admin must redeploy that stack before the change reaches `stage`
   ([How to Manage the Deployer Role](Deploying.md#how-to-manage-the-deployer-role)).
4. **Configuration and secrets.**
   - Channel, list, and field IDs go in `configs/*.json`. The templates turn that file
     into SSM parameters. SSM Parameter Store is where the configuration lives.
   - Tokens go in Secrets Manager, which is where the secrets live. An admin creates each
     one.
   - Read both through `common.aws`.
5. **Callers.** A new HTTP route must check who is calling it
   ([What this repository does](../CLAUDE.md#what-this-repository-does)).
6. **Docs.** Add the service to [README.md](README.md#core-services) with the same lines
   every service has: what it does, how it is triggered, its URL, and where the caller is
   configured.

---

## Coding Standards

The full list, with the reasons, is under [Rules](../CLAUDE.md#rules). In short:

- **Python 3.12.** Put type hints on every function signature. Use `logging` with lazy
  arguments (`logger.info("Task %s updated", task_id)`), never f-strings or `print`.
  Import only what you use.
- **Configuration.** Read settings with `os.environ`, using the names the template sets,
  and check the required ones at the top of the handler. Never hardcode a token, an ID
  that belongs in `configs/`, or an account-specific ARN.
- **Outside services.** Call Slack, ClickUp, Neon, and other outside services through the
  helpers in `layers/common/python/common/`, inside `try`/`except` with a log line.
- **Logs and errors.** Log ID numbers, not names, emails, or phone numbers. Never log or
  return a token, a secret, an `Authorization` header, or a whole request body. Never
  send an exception's text to the caller: log it, and return a plain message.
- **HTML.** Escape anything that comes from outside with `html.escape`.
- **Slack.** Answer within 3 seconds. Run longer work asynchronously.
- **Tests.** Tests go next to the function, in `functions/<area>/<name>/tests/`. They never
  call the network: patch the module where it is used, or use `moto` for AWS. Don't skip
  or delete a failing test, and don't use `--no-verify`.
- **IAM.** Grant the least privilege that works: name exact parameter and secret ARNs, and
  use `Resource: "*"` only for actions that have no resource-level permissions.
- **Scope.** Keep a pull request to its task, and open an issue for any unrelated problem
  you find. Much of the older code doesn't follow these rules yet. Follow them in the code
  you write or change, and leave the rest alone.

---

## Working with AI Agents

You don't need an AI agent to contribute. If you use one, this repository gives it its
rules and a team of skills, so it can do much of the work. You are still the one who
answers for the result.

- **CLAUDE.md is the agent's rulebook.** Claude Code reads [CLAUDE.md](../CLAUDE.md) at
  the start of every session, and other tools read [AGENTS.md](../AGENTS.md), which points
  to it. When your prompt disagrees with the docs, the agent follows the docs and tells
  you. If a rule is wrong, change the rule rather than arguing with the agent.
- **Use the skills.** These are the most common ones:

  | Command | Use it to |
  | --- | --- |
  | `/bug-fix <#N>` | Fix a bug, with a test that failed before the fix, in a pull request to `stage` |
  | `/plan-product`, `/plan-tech`, `/build` | Turn an idea into issues, then a plan in phases, then build each phase |
  | `/review` | Review your branch before you open the pull request |
  | `/address-pr-comments <N>` | Fix or answer every comment on a pull request |
  | `/promote` | Open the `stage` → `main` pull request, and merge it when you say so |

  The full list, including `/offshore` for unattended runs, is in
  [The skills](Working%20with%20AI%20Agents.md#the-skills).
- **Read the whole diff.** Do it before you push or ask for a review, as you would with a
  colleague's work. Look hardest at the agent's [Never](../CLAUDE.md#rules) list: what
  gets logged, IAM and the deploy role, a public route without a caller check, and tests
  that were skipped or deleted.
- **Ask for results, not reassurance.** The agent must run the checks and report what
  they printed ([Done means verified](../CLAUDE.md#done-means-verified)). If it says it
  couldn't run one, run that check yourself.
- **Approve commands with care.** [.claude/settings.json](../.claude/settings.json)
  pre-approves only the tests, the template checks, and read-only `git` and `gh` commands,
  so anything else asks you first. Read each command before you approve it. During
  `/offshore`, a guardrail hook blocks deploys and merges, but it checks commands, not
  code ([What agents never do](Working%20with%20AI%20Agents.md#what-agents-never-do)).
- **You do the admin actions.** An agent can't redeploy the deploy role, create a secret,
  or point Slack or ClickUp at a new URL. Every plan, pull request, and briefing lists
  those actions ([What a person still does](Working%20with%20AI%20Agents.md#what-a-person-still-does)).
- **A pull request the agent opens is yours.** GitHub sees it as opened from your
  account, and you answer for it in review.
- **Keep the agents' instructions current.** If your change alters how something should
  be done, update `CLAUDE.md`, the skill, or
  [Working with AI Agents](Working%20with%20AI%20Agents.md) in the same pull request
  ([Changing the agents](Working%20with%20AI%20Agents.md#changing-the-agents)).

---

## AWS and Production

- Everything in AWS comes from the SAM templates. Never change anything in the AWS
  console, because the next deploy overwrites it
  ([How It's Managed](README.md#how-its-managed-the-important-part)).
- Only the workflows deploy `stage` and `prod`. You can deploy `dev` by hand
  ([Manual Deployment](Deploying.md#manual-deployment-for-dev--stage)).
- An admin deploys the deploy role (`template-cicd.yaml`) by hand. It is never deployed
  by a workflow ([CI/CD Infrastructure](Deploying.md#cicd-infrastructure-the-deployer-role)).
- The same AWS account also runs Asmbly's MCP servers and the Login Service. Never touch
  their resources.
