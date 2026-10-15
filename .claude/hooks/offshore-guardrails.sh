#!/usr/bin/env bash
# Offshore guardrails: a PreToolUse hook (.claude/settings.json).
#
# /offshore runs unattended. Its hard rules are in its SKILL.md, but a long
# run can lose track of them after its context is compressed, so this hook
# enforces the ones that do damage when broken.
#
# It does nothing unless .offshore/active.sentinel exists. /offshore creates
# the sentinel when it starts and deletes it when it finishes, so ordinary
# interactive sessions are never affected.
#
# Claude Code passes the pending tool call as JSON on stdin. Exit 0 allows
# the call; exit 2 blocks it and shows the message on stderr to the model.

set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE_DIR="$ROOT/.offshore"
SENTINEL="$STATE_DIR/active.sentinel"
LOG="$STATE_DIR/guardrails.log"

[ -f "$SENTINEL" ] || exit 0

PAYLOAD=$(cat || true)
[ -n "$PAYLOAD" ] || exit 0

# Pull a field out of the payload. python3 is always present where this repo's
# tests run; if it isn't, allow the call and log that the hook couldn't check.
field() {
  printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
data = json.load(sys.stdin)
value = data
for key in sys.argv[1].split("."):
    value = value.get(key, "") if isinstance(value, dict) else ""
print(value if isinstance(value, str) else "")
' "$1" 2>/dev/null
}

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s NO_PYTHON allowed without checking\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
  exit 0
fi

TOOL=$(field tool_name)
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

block() {
  # $1: what was blocked, $2: what to do instead
  printf '%s BLOCK tool=%s %s\n' "$TS" "$TOOL" "$1" >> "$LOG"
  printf 'OFFSHORE GUARDRAIL: %s blocked: %s\n%s\n' "$TOOL" "$1" "$2" >&2
  exit 2
}

case "$TOOL" in
  Bash)
    CMD=$(field tool_input.command)
    # The same command with quoted strings removed, so a flag that only
    # appears inside a commit message doesn't count.
    BARE=$(printf '%s' "$CMD" | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g")

    # Pushing to stage or main, as a destination or a deletion. Pushing a
    # feature branch whose name merely contains "main" is allowed.
    if printf '%s' "$BARE" | grep -Eq 'git[[:space:]]+push([[:space:]]+.*)?([[:space:]](stage|main)([[:space:]]|$)|:(stage|main)([[:space:]]|$))'; then
      block "a push to stage or main" \
        "Offshore work stays on feature/<plan>. It reaches stage through the pull request the owner merges."
    fi

    # A bare --force. --force-with-lease is allowed on the feature branch.
    if printf '%s' "$BARE" | grep -Eq 'git[[:space:]]+push[[:space:]]+.*--force([[:space:]=]|$)'; then
      block "git push --force" \
        "Use --force-with-lease on feature/<plan>. It refuses to overwrite a push you haven't seen."
    fi

    if printf '%s' "$BARE" | grep -Eq '(^|[[:space:];&|])git([[:space:]]|$)' \
       && printf '%s' "$BARE" | grep -Eq '(^|[[:space:]])--no-verify([[:space:]]|$)'; then
      block "--no-verify" \
        "A failing hook is part of the work. Find the cause and fix it."
    fi

    if printf '%s' "$BARE" | grep -Eq 'git[[:space:]]+reset([[:space:]]+.*)?[[:space:]]--hard([[:space:]]|$)'; then
      block "git reset --hard" \
        "Use git reset --soft <sha> to squash, git restore for working-tree changes."
    fi

    if printf '%s' "$BARE" | grep -Eq 'git[[:space:]]+commit([[:space:]]+.*)?[[:space:]]--amend([[:space:]]|$)'; then
      block "git commit --amend" \
        "Make a new commit. Squash steps use git reset --soft, which needs no amend."
    fi

    if printf '%s' "$BARE" | grep -Eq '(^|[[:space:];&|])gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
      block "gh pr merge" \
        "The owner merges. The deliverable is a green pull request, left open."
    fi

    # Anything that deploys or changes AWS. Deploys happen through the
    # workflows; the deploy role is deployed by an admin by hand.
    if printf '%s' "$BARE" | grep -Eq '(^|[[:space:];&|])sam[[:space:]]+(deploy|sync|delete|remote)([[:space:]]|$)'; then
      block "a SAM deploy" \
        "Offshore never deploys. Use sam build and sam validate to check templates; list deploy steps as admin actions in the briefing."
    fi
    if printf '%s' "$BARE" | grep -Eq '(^|[[:space:];&|])aws[[:space:]]+[a-z0-9-]+[[:space:]]+(create|put|update|delete|remove|modify|attach|detach|associate|disassociate|execute|deploy|invoke|start|stop|tag|untag|add|set|send|publish|rotate|restore|import|register|deregister|enable|disable|change|reset|run|terminate|reboot|cancel|upload|copy|sync|mv|rm|cp)[a-z0-9-]*([[:space:]]|$)'; then
      block "an AWS command that changes something" \
        "Offshore is read-only against AWS. Put the change in the templates, or list it as an admin action in the briefing."
    fi
    ;;

  AskUserQuestion)
    block "a question to the owner" \
      "Offshore runs unattended. Decide using CLAUDE.md and the plan, record the decision as a CHECKPOINT.json event, and surface it in the briefing. If the decision is genuinely the owner's, return 'blocked' for that phase."
    ;;
esac

exit 0
