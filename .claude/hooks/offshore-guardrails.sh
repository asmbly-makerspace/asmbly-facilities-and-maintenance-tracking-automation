#!/usr/bin/env bash
# Offshore guardrails: a PreToolUse hook (.claude/settings.json).
#
# /offshore runs unattended. Its hard rules are in its SKILL.md, but a long
# run can lose track of them after its context is compressed, so this hook
# enforces the ones that do damage when broken.
#
# It does nothing unless .offshore/active.sentinel exists. /offshore creates
# the sentinel when it starts and deletes it when it stops, so ordinary
# interactive sessions are never affected.
#
# Claude Code passes the pending tool call as JSON on stdin. Exit 0 allows
# the call; exit 2 blocks it and shows the message on stderr to the model.
#
# This is a guardrail, not a sandbox: it reads the command the way a shell
# would (separate commands, quotes, heredocs) and checks the command words,
# but code that calls AWS or git from inside a script gets past it.

set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE_DIR="$ROOT/.offshore"

[ -f "$STATE_DIR/active.sentinel" ] || exit 0

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s NO_PYTHON allowed without checking\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE_DIR/guardrails.log"
  exit 0
fi

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

read -r -d '' CHECKS <<'PY'
import datetime, json, os, re, shlex, sys

log_path, branch = sys.argv[1], sys.argv[2]
PROTECTED = {"stage", "main"}

try:
    payload = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
tool = payload.get("tool_name", "")


def block(what, instead):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(log_path, "a") as log:
        log.write(f"{ts} BLOCK tool={tool} {what}\n")
    sys.stderr.write(f"OFFSHORE GUARDRAIL: {tool} blocked: {what}\n{instead}\n")
    sys.exit(2)


if tool == "AskUserQuestion":
    block("a question to the owner",
          "Offshore runs unattended. Decide using CLAUDE.md and the plan, record the decision "
          "as a CHECKPOINT.json event, and surface it in the briefing. If the decision is "
          "genuinely the owner's, return 'blocked' for that phase.")
if tool != "Bash":
    sys.exit(0)


def strip_heredocs(text):
    """A heredoc's body is data (a file, a message), not commands."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", lines[i])
        i += 1
        if match:
            while i < len(lines) and lines[i].strip() != match.group(2):
                i += 1
            i += 1
    return "\n".join(out)


OPERATOR = re.compile(r"^[;&|()\n]+$")


def commands(text):
    """Yield each simple command as a list of words, quotes removed."""
    # A ";" after each newline keeps commands apart even when a "# comment" swallows
    # the newline (shlex reads a comment to the end of its line).
    text = strip_heredocs(text.replace("\\\n", " ")).replace("\n", "\n;")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = re.findall(r"&&|\|\||[;&|()\n]|[^\s;&|()]+", text)
    current = []
    for token in tokens + [";"]:
        if OPERATOR.match(token):
            if current:
                yield current
            current = []
        else:
            current.append(token)


WRAPPERS = {"time", "sudo", "env", "nohup", "command", "exec", "builtin", "xargs"}


def words_of(cmd):
    while cmd and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", cmd[0]) or cmd[0] in WRAPPERS):
        cmd = cmd[1:]
    if cmd:
        cmd = [os.path.basename(cmd[0])] + cmd[1:]
    return cmd


def subcommand(args, value_options):
    """Skip a CLI's global options; return (subcommand, the words after it)."""
    i = 0
    while i < len(args):
        if args[i] in value_options:
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i], args[i + 1:]
    return "", []


AWS_VALUE_OPTIONS = {"--region", "--profile", "--output", "--endpoint-url", "--query",
                     "--cli-read-timeout", "--cli-connect-timeout", "--color", "--ca-bundle",
                     "--cli-binary-format"}
AWS_READ = ("describe", "get", "list", "lookup", "search", "filter", "tail", "validate",
            "estimate", "wait", "help", "ls", "head", "start-query", "stop-query",
            "batch-get", "scan", "query", "select", "simulate")


def check(cmd):
    words = words_of(cmd)
    if not words:
        return
    name, args = words[0], words[1:]

    if name in {"bash", "sh", "zsh"} and "-c" in args and args.index("-c") + 1 < len(args):
        for inner in commands(args[args.index("-c") + 1]):
            check(inner)
        return
    if name == "eval":
        for inner in commands(" ".join(args)):
            check(inner)
        return

    if name == "git":
        sub, rest = subcommand(args, {"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
        if "--no-verify" in rest or (sub == "commit" and "-n" in rest):
            block("--no-verify", "A failing hook is part of the work. Find the cause and fix it.")
        if sub == "commit" and "--amend" in rest:
            block("git commit --amend",
                  "Make a new commit. Squash steps use git reset --soft, which needs no amend.")
        if sub == "reset" and "--hard" in rest:
            block("git reset --hard",
                  "Use git reset --soft <sha> to squash, git restore for working-tree changes.")
        if sub == "push":
            flags = [a for a in rest if a.startswith("-")]
            refs = [a for a in rest if not a.startswith("-")]
            forced = any(f == "--force" or (not f.startswith("--") and "f" in f[1:]) for f in flags)
            if forced or any(r.startswith("+") for r in refs[1:]):
                block("a force push without --force-with-lease",
                      "Use --force-with-lease on feature/<plan>. It refuses to overwrite a push you haven't seen.")
            if "--all" in flags or "--mirror" in flags:
                block("git push --all or --mirror", "Push feature/<plan> only.")
            for ref in refs[1:]:
                dest = ref.lstrip("+").split(":")[-1].replace("refs/heads/", "")
                if dest in {"HEAD", "@"}:
                    dest = branch
                if dest in PROTECTED:
                    block(f"a push to {dest}",
                          "Offshore work stays on feature/<plan>. It reaches stage through the pull request the owner merges.")
            if len(refs) <= 1 and branch in PROTECTED:
                block(f"a push from {branch}", "Switch to feature/<plan> before pushing.")

    if name == "gh":
        sub, rest = subcommand(args, {"-R", "--repo"})
        if sub == "pr" and rest[:1] == ["merge"]:
            block("gh pr merge", "The owner merges. The deliverable is a green pull request, left open.")
        if sub == "api" and any(re.search(r"/pulls/\d+/merge$", a) for a in rest):
            block("a merge through the API", "The owner merges.")

    if name == "sam":
        sub, _ = subcommand(args, {"--config-file", "--config-env", "--region", "--profile"})
        if sub in {"deploy", "sync", "delete", "remote"}:
            block(f"sam {sub}",
                  "Offshore never deploys. Use sam build and sam validate to check templates; "
                  "list deploy steps as admin actions in the briefing.")

    if name == "aws":
        service, rest = subcommand(args, AWS_VALUE_OPTIONS)
        operation, _ = subcommand(rest, AWS_VALUE_OPTIONS)
        if service and operation and not operation.startswith(AWS_READ):
            block(f"aws {service} {operation}",
                  "Offshore is read-only against AWS. Put the change in the templates, or list it "
                  "as an admin action in the briefing.")


for command in commands((payload.get("tool_input") or {}).get("command", "") or ""):
    check(command)
sys.exit(0)
PY

python3 -c "$CHECKS" "$STATE_DIR/guardrails.log" "$BRANCH"
