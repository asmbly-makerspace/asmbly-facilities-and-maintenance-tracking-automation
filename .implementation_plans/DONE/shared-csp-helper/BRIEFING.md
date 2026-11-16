# Offshore briefing: shared-csp-helper

**Date:** 2026-10-17
**Branch:** `feature/shared-csp-helper`
**Pull request:** #151 to `stage`, **green**. You said to merge it once it was green, so the orchestrator merges it after this briefing.
**Epic:** #136 (this run covers story #139, the epic's last story; the pull request closes #139 and #136)
**Phases completed:** 2 of 2

> **Next steps for you, in order:**
> 1. There are no admin actions.
> 2. After #151 merges, the stage deploy publishes a new common-layer version (with `common/csp.py`) and updates 12 functions.
> 3. Run `MANUAL_QA.md` on stage. Steps 1-5 were already run read-only against stage before the merge; re-run them after the deploy.
> 4. Run `/promote` to take `stage` to `main`. That release carries all of epic #136: #137, #148, #138 and #139.

---

## Admin actions

None. There is no new named resource, and no template or deploy-role (`template-cicd.yaml`) change. `csp.py` ships in the existing common layer, which the deploy role already covers.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 1h20m |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. The guardrail blocked the AWS CLI, so MANUAL_QA steps 8-9 (a read-only `get-function-configuration` and an optional direct invoke) were not run. They are yours to run. |

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| — | Implementation plan (story #139) | Done | `f1c78c4` | — | 9m |
| 1 | CSP helper, shared CSP checks and the header pins | Done | `a486acc` | 1 | 16m |
| 2 | Both pages use the helper; every page is checked; docs | Done | `4012492` | 2 | 18m |
| — | Docs | Done | `6e71ad3` | — | 2m |
| — | Manual QA steps | Done | `26ea430` | — | 9m |

## Decisions made

- **One CSP helper:** `layers/common/python/common/csp.py` uses only the standard library, which an AST test and an isolated subprocess test check. It has `sha256_source`, `style_hash_source`, `strict_policy`, `hash_policy`, `new_nonce` and `nonce_policy`. Neither function builds a CSP string by hand any more, and an AST test fails if any `lambda_function.py` contains a directive string.
- **Headers are byte-identical to stage:**
  - Phase 1 pinned the exact header bytes from stage (`07b9b79`), checked against a stage export rather than the new helper.
  - The integration gate rendered 28 cases on stage and on the branch. 25 match exactly: status, every header and the body. The kiln hash stays `sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8=`.
- **Shared test checks:** `tests/page_csp.py` computes hashes itself and never imports `common`, so a bug in the helper can't hide its own failure.
  - A `PUBLIC_PAGES` registry in `tests/test_page_csp.py` runs the hash check on every hash page and the nonce check on every nonce page.
  - `test_every_html_page_is_registered` fails for any function that serves HTML without being in the registry.
  - A `<script src=…>` on a nonce page is now reported.
- **A bug fixed on the way:** the photo page checked Host and path with `^…$` and `.match`, which accepts a trailing newline.
  - With the helper, that input would have raised an uncaught error: a 502 with a traceback. The checks now use `fullmatch` at all three call sites.
  - A Host or path ending in a newline now gets a 400; stage answered 200.
  - A `STAFF_AUTH_DOMAIN` ending in a newline now gets the logged 500. On stage, that newline was written into the CSP header.
  - API Gateway sets the Host and path, so callers can't reach this through the API today.
- **Two nonces, one per request:** a test checks that two requests get different nonces, and that each header's nonce equals the one on the page's `<style>` and `<script>`.
- **The photo test file's private `_csp` parser stays**, so `test_csp_header` is byte-identical and unedited.
- **Docs:** `docs/CONTRIBUTING.md` has an "Adding a Public Page" section, with a table of contents entry. It names `common.brand` and its markers, `common.csp`, `tests/page_style.py`, `tests/page_csp.py`, the registry, and the pins with their capture command. For the caller check, the log group and the deploy-role names, it links to CLAUDE.md.

## Plan changes

- **Phase 1:** prep said NEEDS REVISION (0 HIGH, 4 MED, 5 LOW). Amendments:
  - pin the header the handler actually serves, and the error pages' whole headers dict;
  - use `fullmatch` for directive names and nonces;
  - `page_csp` counts every `<style` and flags inline `style=` and `on*=` attributes;
  - an AST test that `page_csp` never imports `common`.
- **Phase 2:** prep said NEEDS REVISION. Amendments:
  - the trailing-newline fix belongs in this phase;
  - the photo test file keeps its existing tests;
  - the CONTRIBUTING advice on layers and pin capture was corrected.
- **Manual QA:** comparing the whole kiln header with prod fails today, because #138 (PR #150) changed the kiln `<style>` and is on stage but not on main. The doc compares against stage's value from before the merge, and against prod with each hash masked.

## Deferrals and blockers

No blockers.

- **The by-hand CSP scan covers `functions/**` only:** a CSP string built in `layers/common/python/common/` outside `csp.py` would get past it. Options: (a) extend the scan, about 5 lines in `tests/test_page_csp.py`, (b) skip it, since `csp.py` is the only layer module that writes headers. Recommendation: (a), as a small follow-up.
- **Control characters in CSP sources:** `common.csp` rejects `;`, `,`, CR and LF in sources, but not other control characters. Header injection needs CR or LF, and the plan's Security section sets exactly those four. Recommendation: leave it.
- **Duplicate parser:** the photo test file's private `_csp` parser duplicates `page_csp.directives`. Recommendation: replace it the next time that file changes.
- **Agent config:** `.claude/agents/review/lambda.md:46` still calls the kiln viewer "the only HTML page today". It is out of scope for this run. Recommendation: a one-line fix in a `.claude/` change.
- **Registry detection is narrow:** `test_every_html_page_is_registered` finds pages only by a `page.html` file or the text `text/html` in `lambda_function.py`. Its docstring says so; CONTRIBUTING doesn't. Recommendation: leave it.

## Skipped because of the environment

- MANUAL_QA steps 8-9 (AWS CLI): the offshore guardrail blocks `aws` commands, so they were not run. They are read-only checks plus one optional direct invoke, for you to run.

## Integration gate

- pytest: 1,943 passed, 8 subtests (1,871 on `stage` plus 72 new tests)
- cfn-lint: 0 errors, and 4 W3005 warnings in `template.yaml`, byte-identical to `origin/stage`
- sam validate: pass
- sam build: pass
- Cross-checks: clean.
  - No template, config, environment variable, named resource, nested parameter or route change.
  - #138's pins are unchanged, and the capture script reproduces them.
  - `csp.py` and `brand.py` use only the standard library.
  - `ruff --select F` is clean on the 10 changed Python files.

## Review

- Review rounds inside phases: 3. In phase 1, round 1 was clean. In phase 2, round 1 found one docs WARN, which was fixed; round 2, a cold review-lead, approved. `/build`'s independent review-lead approved both phases with no BLOCK.
- Pull request rounds: 0. There are no comments or reviews. Both `test` runs are green on `26ea430`, and the merge state is CLEAN.

## Rollback

```bash
git log --oneline origin/stage..feature/shared-csp-helper
git revert <sha>   # revert phase 2 (4012492) before phase 1 (a486acc)
```

Reverting phase 2 puts the hand-built CSP strings back, along with the trailing-newline bug. Phase 1 on its own changes nothing a visitor sees.

## Action items

- [ ] After the merge, run `.implementation_plans/shared-csp-helper/MANUAL_QA.md` on stage, including steps 8-9 with the AWS CLI
- [ ] Decide whether CLAUDE.md's "Shared helpers" map row should name `brand.py` and `csp.py`, and whether the map should point at `tests/page_style.py` and `tests/page_csp.py`. CLAUDE.md wasn't edited.
- [ ] Decide on extending `test_no_function_builds_a_csp_by_hand` to the common layer (see Deferrals)
- [ ] `/promote` releases epic #136 (#137, #148, #138, #139) to prod together

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
