# Facilities Automation Hub: rules for AI agents

Read this file first, then the document for the area you change. When a plan, an issue,
or a prompt disagrees with these documents, the documents win and you say so. The code
is the final source of truth: when a document disagrees with the code, say which one is
wrong instead of quietly following either.

| Area | Path | Read first |
| --- | --- | --- |
| A Lambda function | `functions/<area>/<name>/` | Its `README.md`, its tests, and "Python" below |
| Shared helpers (AWS, ClickUp, Slack, Neon, Discourse, Google Forms) | `layers/common/python/common/` | The module you call, and its tests in `layers/common/` |
| Application templates | `template.yaml`, `templates/*.yaml`, `configs/*.json`, `samconfig.toml` | "Templates" below, [docs/Deploying.md](docs/Deploying.md) |
| The deploy role | `template-cicd.yaml` | [docs/Deploying.md](docs/Deploying.md), "CI/CD Infrastructure" |
| CI and deploy | `.github/workflows/` | [docs/Deploying.md](docs/Deploying.md) |
| What each service does and how it is triggered | | [docs/README.md](docs/README.md) |
| Plans | `.implementation_plans/` | [.implementation_plans/readme.md](.implementation_plans/readme.md) |
| The agent team and its skills | `.claude/` | [docs/Working with AI Agents.md](docs/Working%20with%20AI%20Agents.md) |

The closest example of how new code should look is
`functions/networking/dynamic_dns_update/`: it logs lazily, has type hints, checks its
caller, and never shows an error's details to the caller. Much of the older code does
not do these things yet. Follow the rules below in the code you write or change, and
leave unrelated code alone.

## What this repository does

Lambda functions behind one API Gateway (`FacilitiesApi`, `https://facilities.asmbly.org`
in prod) and EventBridge schedules. They connect Slack, ClickUp, NeonCRM, Discourse,
Smartwaiver and Google Forms for Asmbly's facilities, ceramics and admin teams. Everything
in AWS comes from the SAM templates; nothing is changed in the console.

- Every HTTP route is public. Only the Dynamic DNS route checks its caller today. A new
  route must check its caller (a Slack signing secret, a ClickUp webhook signature, a
  shared secret compared with `hmac.compare_digest`, or a Cognito authorizer). Don't add
  checks to an existing route as a side effect of other work: open an issue.
- Asmbly's AWS account (110104886034, us-east-2) also runs the MCP servers and the Login
  Service. Never touch their resources.

## Done means verified

Before you say a change is done, run the checks for what you touched and report the real
results, including failures:

```bash
python -m pytest                                              # every change
cfn-lint template.yaml templates/*.yaml template-cicd.yaml    # after a template change
sam validate --region us-east-2                               # after a template change
sam build                                                     # after a template, layer, or requirements change
```

Install the test tools with `pip install -r requirements-dev.txt` (and `pip install
cfn-lint` if it is missing) in a Python 3.12 virtual environment. If a check also fails
on `stage` without your change, say so, and make sure your change adds no new failure.
If you couldn't run a check, say which one and why. A check you didn't run is not a pass.

Write code that these checks can verify. A rule that no check catches needs more care,
because a reviewer has to verify it by reading.

## Rules

**Always**

- Read the code you're changing and its tests before editing. Don't guess at an API
  (ClickUp, Slack, Neon, AWS); open the helper or the vendor's reference.
- Add or update tests with every behavior change, next to the function
  (`functions/<area>/<name>/tests/`, fixtures in `tests/fixtures/`). Tests never call the
  network: patch the module where it is used
  (`functions.<area>.<name>.lambda_function.clickup`) or use `moto` for AWS.
- Read configuration with `os.environ`, using the names the template sets. Check required
  variables at the top of the handler and fail with a logged 500.
- Fetch secrets from Secrets Manager and JSON configuration from SSM through
  `common.aws`. Channel IDs, list IDs and field IDs belong in `configs/*.json`, which the
  templates turn into SSM parameters.
- Call outside services through the helpers in `layers/common/python/common/`, inside
  `try`/`except` with a log line. Add a helper there before calling a new endpoint from
  two functions.
- In new or changed Python: type hints on every function signature, `logging` with lazy
  arguments (`logger.info("Task %s updated", task_id)`, not f-strings or `print`), and
  only the imports you use.
- Answer Slack within 3 seconds. Work that takes longer runs asynchronously (the router
  and `/reorder` invoke a function with `InvocationType='Event'`). Use Block Kit for new
  Slack messages where it fits.
- Escape anything from outside with `html.escape` before it goes into HTML.
- Give every named AWS resource `${Stage}` in its name, an explicit log group
  (`/asmbly/lambda/<FunctionName>-${Stage}`, with a retention period) for every function,
  and a `Project` tag.
- When a nested template gets a new parameter, pass it from `template.yaml`.
- When you add a named resource (function, log group, SSM parameter, table, rule, layer),
  add its name to both `GitHubDeployPolicystage` and `GitHubDeployPolicyprod` in
  `template-cicd.yaml`, and say in the pull request's **Risk** section that an admin must
  deploy that stack by hand before the change reaches `stage`. The deploy fails otherwise.
- Grant the least privilege that works: `ssm:GetParameter` on the exact parameter ARNs,
  `secretsmanager:GetSecretValue` on the exact `secret:<name>-*`. `Resource: "*"` only
  for actions that have no resource-level permissions.
- Update the docs in the same change: the function's `README.md`, and in
  `docs/README.md` what the service does, how it is triggered (webhook, EventBridge,
  Slack command, async invoke), its URL, and where the caller is configured.
- Keep changes scoped to the task. Note unrelated problems, or open an issue for them,
  instead of fixing them silently.

**Never**

- Log, return, or put in an error message a token, a secret, an `Authorization` header,
  or a whole request body. Log IDs, not people's names, emails or phone numbers.
- Send an exception's text to the caller. Log it; return a plain message.
- Hardcode a token, an ID that belongs in `configs/`, or an account-specific ARN.
- Change anything in the AWS console, run `sam deploy`, or run an AWS command that
  changes something. Read-only AWS commands are fine. Deploys happen through the
  workflows, and the deploy role (`template-cicd.yaml`) is deployed by an admin by hand.
- Weaken the deploy role: no wildcard resource names, no new trust subjects, no
  `Resource: "*"` beyond what it has.
- Skip or delete a failing test, or bypass hooks (`--no-verify`).
- Commit secrets, `.env` files, `.aws-sam/`, or anything from `.offshore/`.
- Push to `stage` or `main`. Open a pull request. Merge only when the person you're
  working for says so, for that pull request.

## Don't stop short

- **Retry transient failures.** A 5xx, a timeout, a dropped connection or a "try again"
  from a tool, `gh`, or AWS is not a reason to stop. Retry at least 4 times in the same
  turn, waiting 2, 4, 8 and 16 seconds. Escalate only after that.
- **Done is the success criterion, not a milestone.** A pushed branch or an opened pull
  request is not done when the task was a green pull request. If you don't know what
  done looks like, ask before starting, not at the point where you'd stop.
- **Poll what you can poll.** Don't end a turn with "tell me when CI finishes": watch it
  (`gh pr checks --watch`, `gh run watch`). End a turn only when the work is done, a
  decision is genuinely the person's, or they told you to stop.

## How work flows

| Step | Skill | Result |
| --- | --- | --- |
| What users can do | `/plan-product` | An epic issue and story issues with acceptance criteria |
| How it is built | `/plan-tech` | `.implementation_plans/<plan>/`: a README and one doc per phase |
| Check a phase against the code | `/prep` | A readiness report: READY / NEEDS REVISION / BLOCKED |
| Build a phase | `/build` | Code, tests and docs, validated and independently reviewed |
| Review a branch | `/review` | BLOCK / WARN / NOTE findings and a verdict |
| Write the docs | `/write-docs` | Function READMEs and `docs/` updated |
| All of it, unattended | `/offshore` | A green pull request to `stage`, a manual QA doc, a briefing |
| A bug | `/bug-fix` | A fix with a regression test, reviewed, in a green pull request |
| Reviewer comments | `/address-pr-comments` | Each comment fixed or answered |
| Release | `/promote` | A pull request from `stage` to `main` |
| Corners were cut | `/rigor` | Stop, re-check, redo it properly |

The agents these skills use are in `.claude/agents/`. Most are perspectives a skill reads
and adopts; a few (`review-lead`, `drift-detector`, `prep-auditor`, `domain-expert`,
`bug-planner`, `scribe`) run as separate subagents so that they see the work cold.

## Tracking

Work is tracked in GitHub Issues on this repository. An epic is an issue labeled `epic`
whose sub-issues are stories labeled `story`. A pull request that finishes an issue says
`Closes #12`; earlier partial work says `Refs #12`. Only the pull request that lands the
last piece of a story closes it. If you find follow-up work you won't do now, open an
issue for it, or list it for the person to decide.

## Branches, commits and pull requests

- Branch from `stage`: `feature/<name>`, `fix/<name>`, or `chore/<name>`. Pull requests
  target `stage`, which deploys to the stage stack. `stage` reaches `main`, which deploys
  to prod, through a pull request from `stage` to `main` (`/promote`).
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`.
- Commit after each logical step; don't hold a large change uncommitted. Keep tool
  output small: grep first, then read the lines you need.
- Fill in every section of the pull request template, including **Risk** and the admin
  actions the change needs.
- The `test` check must be green. It is required on `stage` and `main`.
- Before a merge, the pull request's description must say what it finally contains:
  update it when commits are added after it was opened.

## Review discipline

- Answer every review comment: fixed (with the commit), or not fixed (with the reason
  and a reference to the code or document that supports it).
- **Two rounds on style.** For a finding where both forms work, change it once or
  explain why not. If it comes back, keep the code as it is and point to the earlier
  answer. A real bug, a security gap or a failing test always reopens it.
- Don't push an empty commit to start a review again.
