# AI agents

The rules for AI agents working in this repository are in [CLAUDE.md](CLAUDE.md). Read it
first, whichever tool you use (Claude Code, Gemini, Codex, Cursor or another): it says
what the repository does, which checks define "done", and what an agent must never do.

The agent team and its skills (`/plan-product`, `/plan-tech`, `/prep`, `/build`,
`/review`, `/write-docs`, `/offshore` and others) are described in
[docs/Working with AI Agents.md](docs/Working%20with%20AI%20Agents.md). They live in
`.claude/`; other tools can still read the agent files there as prompts.

## Where the old personas went

This file used to hold four persona prompts. Their rules are now in `CLAUDE.md`, and
each persona became one or more agents:

| Persona | Now |
| --- | --- |
| The Builder (SAM, IAM, deploys) | `.claude/agents/plan/infra.md` plans it, `.claude/agents/review/infra.md` reviews it |
| The Connector (Python, integrations) | `.claude/agents/plan/lambda.md` plans it, `.claude/agents/build/coder.md` writes it, `.claude/agents/review/lambda.md` reviews it |
| The Scribe (docs) | `.claude/agents/scribe.md`, run by `/write-docs` |
| The Triage Officer (debugging) | `/bug-fix` and its `bug-planner` agent; the template-to-code cross-checks in `.claude/agents/review/lead.md` |
