# Offshore briefing: class-photo-upload

**Date:** 2026-10-17
**Branch:** `claude/inspiring-bell-o4i5t9` (this environment only lets the session push its own `claude/*` branch, so the run did not use `feature/class-photo-upload`. Rename it if you like.)
**Pull request:** [#110](https://github.com/asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation/pull/110) to `stage`, **waiting for your review and merge** (not merged)
**Epic:** #73 (stories #104–#109, attached as sub-issues)
**Phases completed:** 6 of 6

> **Next steps for you, in order:**
> 1. Do the admin actions below that say "before merge".
> 2. Review pull request #110 and merge it. That deploys the stage stack.
> 3. Run `MANUAL_QA.md` against the stage stack.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod).
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

The exact procedure is in `docs/Deploying.md`, "One-Time Admin Setup: Class Photo Upload". Do the actions in this order.

| When | Action | Why |
| --- | --- | --- |
| Before merge | In the AsmblyMCPs staff pool, create the app client `class-photo-upload`: public, no secret, authorization code grant (PKCE), scope `openid`. Use the prod and stage page addresses as both callback and sign-out URLs. | The page signs in through it. Its ID is the `aud` the API checks. |
| Before merge | Create the SSM `String` parameters `/config/cognito/staff/user-pool-id`, `/config/cognito/staff/auth-domain` (host only, no `https://`) and `/config/cognito/staff/class-photo-app-client-id` in us-east-2. | The application template and the deploy role read them at deploy time. Both deploys fail without them. |
| Before merge | A GitHub org owner creates the App `Asmbly Class Photos`: Contents RW, Pull requests RW, Metadata R, webhook off, "Only on this account". The owner installs it on `asmbly-classes` only, then notes the App ID and the installation ID and generates a private key. | Prod opens the pull requests through it. Stage uses it read-only. |
| Before merge | Create the Secrets Manager secret `github/class-photo-upload-app` in us-east-2 as JSON `{"app_id": "<string>", "installation_id": "<string>", "private_key": "<whole .pem>"}`, then delete the local `.pem`. | The API function reads it on every submission. |
| Before merge | Redeploy `AsmblyFacilitiesMaintTrackingStack-cicd` from this branch (`docs/Deploying.md`, "How to Manage the Deployer Role"). | It lists the new function, log group and SSM names for stage and prod, plus the Cognito reads. The stage deploy fails without it. |
| After the prod deploy | Nothing to configure. The page is at `https://facilities.asmbly.org/class-photo-upload`. | |
| Optional | Create the `epic` and `story` labels, and apply them to #73 and #104–#109. | The labels don't exist, and the GitHub tools here can't create them. |

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 2 h 15 m |
| Subagent retries | 1. The container restarted during the manual QA step. The writer resumed from its saved transcript, and its file was intact. |
| Transient errors retried | 0 |
| Environment problems | The `gh` CLI was not authenticated, so GitHub work went through the GitHub MCP tools. `sam` was not installed, so I installed `aws-sam-cli` 1.169.0 into a scratch venv (not committed). Phase subagents had no Agent tool, so `/prep`, `/build` and `/review` ran their sub-reviews inline. To make up for it, I ran one independent `review-lead` per phase (see Review). |

## Phases

| Phase | Title | Status | Commit | Review rounds |
| --- | --- | --- | --- | --- |
| Plan | Implementation plan | Done | `060129e` | — |
| 1 | Class list and file-name rule | Done | `425febe` | 2 inline + 1 independent (1 WARN fixed) |
| 2 | Photo checks | Done | `f1a7c81` | 2 inline + 1 independent (3 WARNs fixed) |
| 3 | GitHub App client | Done | `e8daf15` | 1 inline + 1 independent (2 hardenings applied) |
| 4 | Pull request flow and dry run | Done | `7247336` | 3 inline + 1 independent (2 WARNs + 1 note fixed) |
| 5 | API function, routes and Cognito authorizer | Done | `937e379` | 3 inline + 1 independent (no findings) |
| 6 | The upload page and docs | Done | `55f0222` | 3 inline + 1 independent (1 docs WARN fixed) |
| Docs | Docs for class-photo-upload | Done | `a2c7f31` | — |
| QA | Manual QA steps | Done | `57b16a0` | — |

## Decisions made

- **Unauthenticated page route (needs your OK):** `GET /class-photo-upload` serves a fixed sign-in page with no caller check (plan Decision 7). This is an exception to CLAUDE.md's "a new route must check its caller": a browser navigation can't carry a bearer token. The page holds only public values (the hosted sign-in host and the public client ID). Both data routes use the Cognito authorizer, and the function also checks `aud` and `token_use`. The independent reviewer judged it acceptable.
- **Location data means GPS coordinates:** the server refuses EXIF GPS (IFD0, IFD1, the Exif sub-IFD) and XMP GPS, in the main image and in up to 16 embedded images or trailers. Place names that photo apps add from GPS (IPTC City, `photoshop:City`, `LocationCreated`) are not checked. Widening this is your call (plan README Decisions 25–26).
- **Repeat submissions:** the tree and the description are always built from the current `main`. With an open pull request, the new commit fast-forwards the branch, and `main` becomes a second parent only if it has moved. When a branch has no open pull request (merged or closed), the `class-photo/` branch is reset onto `main` and a new pull request opens; the old one is never reopened (plan Decision 27).
- **GitHub text safety:** class names in the description are in CommonMark-safe code spans. In the title and commit message, `#` and `@` before a word get a space, so a Neon name can't reference or close an issue or mention a user.
- **Limits:** 4 MB means 4 × 1024 × 1024 bytes. A photo counts as 3:2 when `100·|2w−3h| ≤ 3h` (1% tolerance), after the EXIF orientation is applied.
- **Time budget:** Neon gets 4 s per page for at most 8 pages, each GitHub call 5 s, the Lambda 25 s in all. No prod write starts with less than 8 s left, which keeps the request inside API Gateway's 29 s.
- **Dependency:** `PyJWT[crypto]==2.15.1`, the newest 2.x release at least two weeks old, pinned in `requirements-dev.txt` and the API function's `requirements.txt`. `cryptography` is unpinned underneath it, as `slack-sdk` is elsewhere.
- **Deploy role:** `cognito-idp:DescribeUserPool` on the exact staff pool ARN was added as a precaution. I couldn't confirm offline whether API Gateway needs it. Consider removing it after the first successful stage deploy.
- **"README.md Core Services"** in #73 was read as `docs/README.md`, since the repository has no root README.

## Plan changes

- **Phases 1–6:** `/prep` returned NEEDS REVISION on phases 1, 2, 4, 5 and 6, and the amendments are recorded in each phase document. The largest change, in phase 4, builds repeat submissions from the current `main` rather than the branch head, so the description matches the diff.
- **Phase 2:** after the independent review, the photo check now also looks in embedded images and trailers (phone gain maps, motion photos), in IFD1 and in the Exif sub-IFD. Real header fixtures from `asmbly-classes` were added.

## Deferrals and blockers

- **Decision 7 (above):** accept it in the pull request, or open an issue for another design. Recommendation: accept it.
- **Place names in photos:** options: (a) leave it as is; (b) also strip and refuse IPTC and XMP place names. Recommendation: (a), since the photos are taken at Asmbly anyway.
- **`requestContext.path` on the custom domain:** this can only be confirmed on a deployed stack. If it differs, the page answers 400. MANUAL_QA covers it.
- **Rare valid JPEGs** (bytes between segments, DNL height 0, malformed EXIF APP1) are refused as unreadable. MANUAL_QA mentions this.
- **A class name starting with `.`** produces a dotfile name the site never loads. It is not refused. MANUAL_QA mentions it.
- **Two simultaneous submissions for the same class:** if they race a branch reset, one gets a conflict message, and the description may come from the other.
- **Pre-existing, not touched:** `template.yaml`'s `MethodSettings` `ResourcePath "/nic/update"` probably needs `/~1nic~1update` to take effect. Open an issue if you agree.

## Skipped because of the environment

- None. Every check ran; `sam` ran from a scratch install.

## Integration gate

- pytest: 1499 passed (198 before this work)
- cfn-lint: 4 × W3005 (redundant `DependsOn` on the custom-domain resources), the same 4 as on `stage`; nothing new
- sam validate: pass
- sam build: pass (the API function bundles PyJWT and cryptography)
- The CI `test` job, reproduced in a fresh venv: 1499 passed
- Browser parity: I ran the page's JavaScript checks in headless Chromium against the server's `check_photo` on 5,062 photos, with 0 mismatches. The page also ran under its real CSP: 54/54 checks passed, with no violations.
- Cross-checks (environment variables, deploy-role names, nested parameters, routes, config keys, requirement pins): clean

## Review

- Review rounds inside phases: 14 inline and 6 independent. Findings fixed from the independent reviews: 9 WARNs and 3 notes. Deferred: listed above.
- Pull request rounds: none yet, and no comments so far.

## Rollback

Each phase is one commit:

```bash
git log --oneline origin/stage..claude/inspiring-bell-o4i5t9
git revert <sha>   # undoes one phase
```

After deploy, the whole feature can be switched off by suspending the GitHub App, or by uninstalling it from `asmbly-classes`. A bad pull request on `asmbly-classes` is undone by closing it and deleting its `class-photo/...` branch.

## Action items

- [ ] The admin actions above, in order
- [ ] Review pull request #110, especially `functions/classes/class_photo_upload_api/submission.py` (the Git writes), `layers/common/python/common/github_app.py` (token scope and the branch guard), `functions/classes/class_photo_upload_page/page.html` (sign-in and token handling) and `template-cicd.yaml` (the new deploy-role entries)
- [ ] Accept or reject Decision 7 (the unauthenticated page route)
- [ ] Decide on place names in photos (above)
- [ ] Run `MANUAL_QA.md` on the stage stack
- [ ] Close #73 after prod QA

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
