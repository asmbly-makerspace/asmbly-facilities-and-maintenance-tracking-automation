# Offshore briefing: shared-style-checks

**Date:** 2026-10-17
**Branch:** `feature/shared-style-checks`
**Pull request:** #147 to `stage`, **green, waiting for your review and merge**
**Epic:** #136 (this run covers story #137; #138 and #139 come later)
**Phases completed:** 1 of 1

> **Next steps for you, in order:**
> 1. There are no admin actions. Nothing has to happen before the merge.
> 2. Review pull request #147 and merge it. That deploys the stage stack, with no change to what runs.
> 3. Run `MANUAL_QA.md`: the local steps, then the stage regression check.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod), or wait and promote it together with #138.
>
> Offshore never merges, deploys, or changes anything in AWS.

---

## Admin actions

None. The branch changes only test code and docs. No page, handler, template, config, IAM policy or deploy role (`template-cicd.yaml`) changes. `tests/page_style.py` sits outside every `CodeUri` and `ContentUri`, so nothing deploys differently.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 50m |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. Python 3.12.11, SAM CLI 1.166.2 and `gh` were all present. |

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| — | Implementation plan (story #137) | Done | `b84d084` | — | 7m |
| 1 | Shared style-check module | Done | `00ada2c` | 2 | 28m |
| — | Docs | Done | `64b140a` | — | 1m |
| — | Manual QA steps | Done | `3ca7e8d` | — | 6m |

## Decisions made

- **Scope:** the run covers #137 only, not all of epic #136, so the pull request holds one story. #138 (shared tokens and logo in the common layer) and #139 (the CSP helper) build on it in later runs.
- **Where the module lives:** `tests/page_style.py`, with its own tests in `tests/test_page_style.py` and an empty `tests/__init__.py`. Tests import it with `from tests import page_style`. A regular package at the repository root always wins over the two `tests/` folders under `layers/common/`, which have no `__init__.py`. The integration gate confirmed this in every collection order.
- **Checks return problems instead of asserting:** each check returns a list of every problem it finds. pytest only rewrites `assert` inside test modules, so the page tests assert that each list is `[]` and get readable failures.
- **One phase, not two:** the diff is about 1,440 lines, but about 515 are deleted duplicates and about 250 are mechanical renames. A split would leave a commit where the photo page still has its own copy of the helpers.
- **Deliberate tightenings, all passing on today's pages:**
  - The photo page's logo check now uses the kiln page's stricter forbidden list.
  - The photo page must have exactly one `<style>` block.
  - An unbalanced quote is now reported on the photo page.
  - A `<style>` inside an inline SVG is now reported on the kiln page.
- **Proof that the checks still bite:** 23 mutations to the pages (11 kiln, 12 photo) each made the named test fail. The pages were restored afterwards.
- **CLAUDE.md not edited:** it is agent configuration, so the map row is left for you (see the action items).

## Plan changes

- **Phase 1:** prep said NEEDS REVISION. The amendments were applied to the phase doc before the build:
  - a rewrite map for the helpers and constants that moved;
  - the check semantics to keep (contrast is compared unrounded, glyph exemptions match as a prefix);
  - a sturdier packaging test;
  - `sam build` with a positive control;
  - a mutation check for each replaced check;
  - the CLAUDE.md row moved to the pull request.

## Deferrals and blockers

No blockers.

- **Test code ships to Lambda today:** every function's `CodeUri` packages its `tests/` folder into the Lambda zip, and `CommonLayer`'s `ContentUri` (`layers/common/`) packages `layers/common/tests` and `layers/common/python/tests`. This was true before this change, which doesn't alter it. Options: (a) a follow-up issue to exclude tests from the packages, (b) accept it. Recommendation: (a). It makes the zips smaller and keeps test fixtures out of production.
- **Gaps inherited by `page_style`:** both page copies already had these.
  - `token_block_problems` accepts a single word as a `--font-*` stack (for example `--font-x: red`).
  - `Stylesheet.rules()` splits selector lists on the commas inside `:is()` or `:not(a, b)`. Neither page uses those today.
  - Options: (a) fold them into #138, (b) a follow-up issue, (c) skip. Recommendation: (b), a small issue named "Tighten page_style font-stack and selector-list parsing".

## Skipped because of the environment

None.

## Integration gate

- pytest: 1,847 passed, 0 skipped (1,831 on `stage` plus 16 new tests in `tests/test_page_style.py`)
- Test IDs: kiln 73 = 73 and photo 113 = 113, with nothing missing in either direction. The files pass alone, together, in either order, and after the `layers/common` tests.
- cfn-lint: 4 W3005 warnings in `template.yaml`, byte-identical to `origin/stage`. The branch adds none.
- sam validate: pass
- sam build: pass. `page_style` doesn't appear in `.aws-sam/build`, while 19 other test files do (the positive control).
- Cross-checks: clean. No template, config or code outside tests changed. `ruff --select F` is clean on the changed files.

## Review

- Review rounds inside the phase: 2, plus `/build`'s independent review, which approved. That review's docs WARN and NOTE were fixed. Round 1 found one import-order nit, which was fixed. Round 2 found only NOTEs: the small ones were fixed and two were deferred (above).
- Pull request rounds: 0. There are no comments or reviews yet. Both `test` runs are green on `3ca7e8d`, and the merge state is CLEAN.

## Rollback

```bash
git log --oneline origin/stage..feature/shared-style-checks
git revert 00ada2c   # undoes phase 1 (the page test files get their own helpers back)
```

## Action items

- [ ] Review pull request #147, especially `tests/page_style.py` (the shared checks and `Stylesheet.from_page`) and the two page test files' calls into it: `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py` and `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`
- [ ] Add or decline this row in CLAUDE.md's map: `| Style checks for the HTML pages | tests/page_style.py | Its docstring and tests/test_page_style.py |`
- [ ] Run `.implementation_plans/shared-style-checks/MANUAL_QA.md`: the local steps, then the stage check after the merge
- [ ] Decide on a follow-up issue to keep `tests/` folders out of the Lambda and layer packages
- [ ] Decide on a follow-up issue for the `page_style` font-stack and selector-list gaps
- [ ] #138 can start after this merges

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
