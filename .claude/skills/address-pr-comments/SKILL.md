---
name: address-pr-comments
description: Work through every review comment and failing check on a pull request in this repository. Each comment is fixed at its root cause or answered with a reason, threads are replied to and resolved, CI failures are diagnosed from their logs, and the fixes are verified and pushed. Never merges. Use when asked to address, answer, or fix review comments or failing checks on a pull request.
argument-hint: "[PR number, URL, or branch]"
model: opus
effort: high
---

You are addressing review comments and failing checks on a pull request. No shortcuts and
no bandaids: every finding is traced to its root cause, fixed properly or answered with a
reason, and verified before you push.

The input (a pull request number, URL, branch, or empty):

```
$ARGUMENTS
```

The repository is `asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation`.
Pass `--repo asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation` to
`gh` so it works from any worktree. Below, `REPO` stands for that name.

---

## Step 1: Identify the pull request

- `#80`, `80`, a URL, or a branch name: use it.
- Empty: `gh pr view --json number,url,headRefName,baseRefName,title,state`.
- Nothing found: stop and say so. Don't guess.

Check out its head branch if you aren't on it. Never work on `stage` or `main`.

---

## Step 2: Inventory everything to address

Gather first; don't fix anything yet.

### 2a. Metadata and scope

```bash
gh pr view <n> --repo REPO --json number,title,body,headRefName,baseRefName,headRefOid,mergeable,mergeStateStatus
gh pr diff <n> --repo REPO --name-only
```

A `stage → main` pull request is a release: many changes, many authors. Fixes don't go on
it; they go in a pull request to `stage` (see `/promote`).

### 2b. All four comment surfaces

```bash
gh api repos/REPO/issues/<n>/comments --paginate        # the conversation
gh api repos/REPO/pulls/<n>/comments --paginate         # inline comments on the diff
gh api repos/REPO/pulls/<n>/reviews --paginate          # review summaries
gh api graphql -f query='query { repository(owner:"asmbly-makerspace", name:"asmbly-facilities-and-maintenance-tracking-automation") { pullRequest(number:<n>) { reviewThreads(first:100) { nodes { id isResolved isOutdated path line comments(first:50) { nodes { databaseId author { login } body createdAt } } } } } } }'
```

Comments come from people and from bots. There is no automated Claude review workflow on
this repository today; if one is added, its comments are handled like any other.

**Deduplicate** by `(path, line, body)`: the same finding can arrive twice under two
accounts.

### 2c. Checks

```bash
gh pr checks <n> --repo REPO
gh run view <run-id> --repo REPO --log-failed
```

`test` is the required check on `stage` and `main`.

### 2d. The punch list

Keep one table and work through it:

| # | Source | path:line | Author | Summary | Resolved? | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | inline | `functions/x/y/lambda_function.py:42` | a reviewer | ... | no | FIX / EXPLAIN / ALREADY-FIXED |

- **FIX:** a real issue. The default for anything substantive.
- **EXPLAIN:** the comment is wrong, out of scope, or the fix is worse than the issue.
  Needs a written reply with a reference.
- **ALREADY-FIXED:** verify by reading the current code on this branch, then say where.

Skip resolved threads whose fix is in HEAD (verify), outdated threads on deleted lines
(verify), and acknowledgments with nothing to act on. Don't skip a comment because it is
old, from a bot, or looks minor.

Classify each FIX: bug, security, failing test, style, question, or out of scope. Out of
scope becomes EXPLAIN, with a suggested follow-up issue for the person to decide on.

---

## Step 3: Read before you fix

For every FIX item:

1. Read the whole file, not just the commented lines.
2. Read what it touches: the template for a function, the callers of a helper, the tests.
3. Look for the same pattern elsewhere. If the comment is about one handler sending
   `str(e)` to the caller and three others do too, decide with the person whether they
   belong in this pull request; don't silently widen it.
4. Find the rule in `CLAUDE.md` the comment invokes and cite it in the commit or reply.

---

## Step 4: Address each item

### FIX

1. Fix the root cause, not the place the symptom showed.
2. Add or update a test that would have caught it, when one is feasible.
3. Run the checks for what you touched (`CLAUDE.md`, "Done means verified") before
   moving on:

   ```bash
   python -m pytest                                              # always
   cfn-lint template.yaml templates/*.yaml template-cicd.yaml    # after a template change
   sam validate --region us-east-2                               # after a template change
   sam build                                                     # after a template, layer, or requirements change
   ```

### EXPLAIN

Write what you considered, why no change, and what would change your mind. Reply in the
thread:

```bash
gh api repos/REPO/pulls/<n>/comments -X POST -f body="<reply>" -F in_reply_to=<comment databaseId>
```

Never dismiss a comment silently.

### ALREADY-FIXED

Reply with the commit and line that fixed it, then resolve the thread:

```bash
gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<thread id>"}) { thread { isResolved } } }'
```

Resolve a thread after a FIX too, once the reply naming the commit is posted. Leave a
thread open when the reviewer asked a question only they can close.

---

## Step 4a: Round-trip discipline: don't flip-flop

Review is a conversation. Reviewers, bots especially, contradict their own earlier
comments across rounds. Each reversal costs a commit, a CI run and trust.

**Track decisions per location.** For every place you change in response to a comment,
note the line, the state it landed in, and a one-sentence reason. When a later round
flags the same place, check your notes first.

**When a comment contradicts a decision already defended on this pull request** (a reply
on the thread explains the current state):

1. Keep the current state by default.
2. Make sure it really is a contradiction and not a new concern on the same line.
3. Reply once: the decision is locked, what state it is in, which earlier reply
   established it (link it), and what would change your mind (a concrete bug, not a
   preference).
4. Don't push a commit for it.

This applies only to lines already defended in writing on this pull request. A first
comment on untouched code is judged on its merits.

**Two rounds on style.** For a finding where both forms work: in round 1, change it if
it's a clear improvement or explain why not. In round 2, if it comes back, keep the code
as it is and point to round 1. Pick the form the surrounding code uses (grep for it).

**Stale duplicates.** If the comment describes something that isn't in the current code,
reply with the evidence (`git grep` output) and move on. Applying a fix that is already in
place creates a no-op commit and another round.

**What reopens a locked decision:** a new, concrete failure (a bug, a security gap, a
failing test), a rule in `CLAUDE.md` that changed, or the person telling you to.

---

## Step 5: Failing checks

- **Test failures:** fix the test or the code, whichever is wrong. Never skip or delete a
  test to go green.
- **Lint and template failures:** fix them; don't disable the rule. If `cfn-lint` fails
  on `stage` too, say so, and make sure this pull request adds nothing new.
- **Build failures:** find the cause (a missing dependency, a wrong `CodeUri`, a
  requirements file). Don't delete the failing step.
- **A failure that is red on `stage` too** isn't this pull request's: say so once on the
  pull request and in the report.

**Two diagnostic commits at most.** If you can't read why a check failed, you may push up
to two commits that only add diagnostic output (verbose flags, `::group::` markers). If
that doesn't reveal the cause, stop and ask the person for the log. Revert diagnostic
commits before the pull request is merged.

---

## Step 6: Self-review before pushing

1. `git status`: only the intended files changed. No `.aws-sam/`, no `.offshore/`, no
   secrets.
2. `git diff`: read every line. No debug prints, no commented-out code.
3. Re-run the checks for everything you touched.
4. Every punch-list row has a commit, a reply, or both.

---

## Step 7: Commit and push

One logical change per commit, Conventional Commits:

```bash
git add <files>
git commit -m "fix: <summary>

<why, and which review comments this answers>"
```

Review-fix commits carry no `Closes #N`: the pull request body says what it closes.

**When called by `/offshore` (a review round):** squash the round's fix commits into one
before pushing, because the push starts the next round:

```bash
ROUND_BODY=$(git log --pretty=format:'- %s%n%n%b' "$PRE_ROUND_SHA"..HEAD)
git reset --soft "$PRE_ROUND_SHA"
git commit -m "fix(review-round-<N>): <one-line summary>

$ROUND_BODY"
git push --force-with-lease origin HEAD
```

Skip the squash for a round with no code changes. `--force-with-lease` only, and only on
the feature branch.

Otherwise push normally (`git push`). If a pre-commit hook fails, fix the cause and make a
new commit. Never `--no-verify`.

**Update the pull request description** when the commits change what it contains:
`gh pr edit <n> --body-file <file>`, or a comment summarizing what the new commits do.

**Never push an empty commit** to start a review or CI again. A round where you only
replied gets no new run; say so in the report. To re-run a flaky check, use
`gh run rerun <run-id> --failed`.

---

## Step 8: Watch it go green

```bash
gh pr checks <n> --repo REPO --watch
```

If a check fails, go back to Step 5. Retry transient `gh` failures 4 times (2, 4, 8, 16
seconds) before stopping. Stop when the checks are green and every punch-list row is
handled.

---

## Step 9: Report

```text
PR #<n>: <title>
Base: <base>  Head: <head>  New HEAD: <sha>

Addressed:
  - <N> fixed (<areas>)
  - <N> answered without a change (replies posted)
  - <N> already fixed (threads resolved)

Checks fixed:
  - <check>: <root cause and fix>

Not fixed:
  - <item>: <reason>

Suggested follow-up issues (for you to decide):
  - <title>: <one line>

Pushed: <N> commits. Checks: <green | waiting on X>.
```

Under 200 words.

---

## Hard rules

- **Never merge,** and never push to `stage` or `main`.
- **No `--no-verify`, no bare `--force`, no `git reset --hard`, no deleting branches.**
  `--force-with-lease` only for an `/offshore` round squash on the feature branch.
- **No skipping tests or disabling checks** to go green.
- **No silent dismissals.** Every comment gets a fix or a reply.
- **No assumptions.** Read the file, grep the pattern, verify the fix on this branch.
- **No `sam deploy` and no AWS command that changes anything.**
- **No flip-flopping** (Step 4a).
