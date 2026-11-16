# Offshore briefing: shared-brand-tokens

**Date:** 2026-10-17
**Branch:** `feature/shared-brand-tokens`
**Pull request:** #150 to `stage`, **green**. You said to merge it once it was done, so the orchestrator merges it after this briefing.
**Epic:** #136 (this run covers story #138; #139 comes next)
**Phases completed:** 2 of 2

> **Next steps for you, in order:**
> 1. There are no admin actions.
> 2. After #150 merges, the stage deploy publishes a new common-layer version and updates 12 functions.
> 3. Run `MANUAL_QA.md` against the stage stack. It compares stage with prod at 320px and 1280px, and checks both pages' CSP headers, the photo function's single layer, and the page sizes.
> 4. When it passes, run `/promote` to take `stage` to `main` (prod).

---

## Admin actions

None. There is no new named resource, and `template-cicd.yaml` doesn't change. The deploy role already allows `lambda:UpdateFunctionConfiguration` on `ClassPhotoUploadPageFunction-<stage>` and `lambda:GetLayerVersion` on `common-layer-<stage>:*`, so attaching the layer needs no admin redeploy.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 1h15m |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. Python 3.12.11, SAM CLI 1.166.2 and `gh` were all present. |

During the docs step, the scribe subagent's hand-back came back empty. The docs agent that ran it checked its commit against the code itself. The docs it wrote match the code.

## Phases

| Phase | Title | Status | Commit | Review rounds | Time |
| --- | --- | --- | --- | --- | --- |
| — | Implementation plan (story #138) | Done | `925d2cc` | — | 12m |
| 1 | Brand module and the stage pins | Done | `709880a` | 1 | 20m |
| 2 | Both pages serve the shared tokens and logo | Done | `267355c` | 2 | 20m |
| — | Docs | Done | `bba0614` | — | 2m |
| — | Manual QA steps | Done | `b79a8d6` | — | 12m |

## Decisions made

- **One shared module:** `layers/common/python/common/brand.py` uses only the standard library, which a test checks. It holds:
  - `BRAND_TOKENS`: the 32 shared tokens as CSS text;
  - `ASMBLY_LOGO`: the 17-path SVG, copied byte for byte from the photo page;
  - `fill_brand(page)`: fills the markers. It raises `ValueError` unless the tokens marker appears exactly once and the logo marker at most once.
- **Markers in the pages:** each `page.html` keeps `/* __BRAND_TOKENS__ */` inside `:root` and `<!-- __ASMBLY_LOGO__ -->` where the logo goes.
  - The kiln function fills them at import, before `_style_hash`, so the CSP hash covers the `<style>` it serves on the list, empty and error pages. The hash value changes; the 5-directive policy doesn't.
  - The photo function fills them in `_template()`, before the nonce goes in. Its 8-directive nonce CSP is unchanged.
- **Pins prove visitors see no change:**
  - Phase 1 captured each page's served tokens and CSS rules from stage (`6fd11c9`) into `tests/fixtures/pinned_tokens.json` and `pinned_rules.css` for each page. Phase 2 had to pass them without regenerating them, and it did.
  - A committed script, `.venv/bin/python -m tests.capture_page_pins`, regenerates the pins, and a test checks that it reproduces them.
  - Rendered side by side with stage, the only byte difference is the kiln logo's closing `</svg>`, now indented 4 spaces instead of 2.
- **One shared change reaches both pages:** a test changes a shared token's value and checks that both served pages change, then restores it.
- **The photo function gets the common layer only:** templates/classes.yaml adds `Layers: [!Ref CommonLayerARN]` to `ClassPhotoUploadPageFunction`. `template.yaml` already passes that parameter. A subprocess test checks that the photo function loads no `boto3`, `botocore` or `requests`.
- **No test calls git**, because CI uses a shallow checkout.
- **Plan error found and fixed:** the plan said to look for `brand.py` under `.aws-sam/build/CommonLayer`. `CommonLayer` has no `BuildMethod`, so SAM doesn't copy it there; the built template points at `layers/common`.

## Plan changes

- **Phase 1:** prep said NEEDS REVISION (drift 1 MED, audit 1 MED fix-before-build, 4 LOW). The amendments were applied:
  - a committed capture script replaced the one-time `git show` command, which would stop working after phase 2;
  - token JSON is sorted;
  - rule normalization is defined once;
  - pin tests don't call git;
  - an extra test checks that the capture script reproduces the fixtures.
- **Phase 2:** prep said READY.

## Deferrals and blockers

No blockers.

- **Three tokens stay per page:** `--page-bg`, `--text` and `--glyph-error` have the same name and value on both pages, but #138's list doesn't name them. A test pins this choice. Options: (a) share them in a follow-up, (b) keep them per page. Recommendation: (b) until a third page needs them.
- **The pin fixtures are permanent:** every deliberate change to a page's look has to regenerate them with `.venv/bin/python -m tests.capture_page_pins`. Options: (a) keep them, (b) drop them after #139. Recommendation: (a). They are what proves "no visible change" on later refactors.
- **A broken marker shows up as a collection error:** if a marker is broken, `fill_brand` raises at import, so pytest reports a collection error instead of a failure from `test_page_template_has_each_placeholder_once`. CI still fails. No action needed.
- **Layer tests ship in the layer:** `layers/common/tests/`, now including `test_brand.py`, is packaged into the layer, like the other layer tests. This is the existing "test code ships to Lambda" follow-up from #137's briefing.

## Skipped because of the environment

None.

## Integration gate

- pytest: 1,871 passed (1,849 on `stage` plus 22 new tests)
- cfn-lint: 0 errors, and 4 W3005 warnings in `template.yaml`, byte-identical to `origin/stage`
- sam validate: pass
- sam build: pass. `ClassPhotoUploadPageFunction` has `Layers: [CommonLayerARN]`.
- Cross-checks: clean. 11 functions used the common layer before, 12 after. No environment variable, named resource, route or deploy-role change. No new nested parameters (`CommonLayerARN` already existed).
- Page sizes: kiln with 50 rows is 24.0 KB (limit 60 KB); photo is 70.6 KB (limit 100 KB).

## Review

- Review rounds inside phases: 3 (phase 1: 1, which was clean; phase 2: 2, each fixing one small NOTE or WARN). `/build`'s independent review-lead approved both phases with no BLOCK.
- Pull request rounds: 0. There are no comments or reviews. Both `test` runs are green, and the merge state is CLEAN.

## Rollback

```bash
git log --oneline origin/stage..feature/shared-brand-tokens
git revert <sha>   # revert phase 2 (267355c) before phase 1 (709880a)
```

Reverting phase 2 alone puts each page's own tokens and logo back and removes the photo function's layer. Phase 1 on its own changes nothing a visitor sees.

## Action items

- [ ] After the merge, run `.implementation_plans/shared-brand-tokens/MANUAL_QA.md` on stage. Compare the pages with prod, allowing for the photo page's dry-run banner on stage.
- [ ] Decide whether CLAUDE.md's "Shared helpers" map row should also mention `brand.py`, the brand tokens and logo the HTML pages share. CLAUDE.md wasn't edited.
- [ ] Decide on sharing `--page-bg`, `--text` and `--glyph-error` (see Deferrals)
- [ ] #139 (the CSP helper and the "Adding a public page" docs) is next

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
