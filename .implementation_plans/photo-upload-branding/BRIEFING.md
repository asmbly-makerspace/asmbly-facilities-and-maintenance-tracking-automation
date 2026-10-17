# Offshore briefing: photo-upload-branding

**Date:** 2026-10-17
**Branch:** `feature/photo-upload-branding`
**Pull request:** [#115](https://github.com/asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation/pull/115) to `stage`. Its checks were green, and the owner merged it (`a1479e6`). The stage deploy succeeded.
**Epic:** #111 (stories #112, #113, both closed by the merge)
**Phases completed:** 2 of 2

> **Next steps for you, in order:**
> 1. Run `MANUAL_QA.md` against the stage page.
> 2. When it passes, run `/promote` to take `stage` to `main` (prod).
>
> The owner merged #115 before the run reached this step, so this briefing was committed afterwards on `feature/class-photo-loading` (#114).

---

## Admin actions

None. The change has no templates, IAM, routes, secrets or deploy-role changes.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | About 2 h |
| Subagent retries | 0 |
| Transient errors retried | 0 |
| Environment problems | None. The run was on the owner's Mac with `gh`, `sam` and headless Chrome. `.venv/bin/pip` points at a different Python, so installs used `.venv/bin/python -m pip`. |

## Phases

| Phase | Title | Status | Commit | Review rounds |
| --- | --- | --- | --- | --- |
| Plan | Implementation plan | Done | `c0ae42f` | — |
| 1 | Brand tokens, header, logo and type | Done | `3e5eb81` | Build review + 3 cold review-lead rounds (1 BLOCK and WARNs fixed) |
| 2 | Controls, messages, result and layout | Done | `57a24ab` | Build review + 2 rounds, 2 of the 3 cold (2 WARNs fixed) |
| Docs | Docs for photo-upload-branding | Done | `fa4103c` | — |
| QA | Manual QA steps | Done | `4c7549b` | — |

## Decisions made

- **No hardcoded values (owner rule):** every color, tint, font stack, spacing, radius and size is a CSS custom property on `:root`. Seven tests enforce it, including `test_styles_use_tokens_only`, `test_brand_tokens_match_the_guide` and `test_derived_tokens_follow_the_formula`. The only literal allowed outside `:root` is the `@media` breakpoint, which CSS can't take from a property; a test checks that it matches its token.
- **Heading font:** a bold system font, not PP Gosha, as the owner confirmed. asmbly.org serves its PP Gosha files without CORS headers, so hotlinking them from `facilities.asmbly.org` (as the kiln page tries to) doesn't load the font.
- **Logo:** the official vector from `asmbly-classes` `app/src/lib/components/logo.svelte` (commit `9a534a6`), drawn inline with `currentColor`.
- **Pattern strip:** a faithful inline-SVG redraw in the sub-brand colors. No official vector was found.
- **Page color:** Asmbly Purple, replacing the earlier ceramics magenta. Status messages use 80/20 shades of the lasers red and the electronics green; the banners use 20% tints.
- **Frozen:** the page's `<script>`, `lambda_function.py`, the Content-Security-Policy and every message text are byte-identical to before.
- **Hover:** hover styles apply only under `@media (hover: hover)`, so a tap on a phone doesn't leave a control looking hovered.

## Plan changes

- **Phases 1 and 2:** `/prep` returned NEEDS REVISION for both, and the amendments are recorded in each phase document. Most of them reused existing tokens instead of adding duplicates, and the pattern became an SVG `<pattern>`.

## Deferrals and blockers

- **Safari:** the select's 44 px minimum height wasn't checked in Safari; none was available.
- **Older browsers:** the status glyphs don't show on Safari before 17.4 or Firefox before 128. The colored edges and tints still do.
- **Dragging:** the photo box flickers once when the pointer first enters its text during a drag. Fixing it needs a script change, which belongs with #114.
- **Loading behavior:** the loading, progress and retry behavior is left to #114.

## Skipped because of the environment

- None.

## Integration gate

- pytest: 1550 passed
- cfn-lint: 4 × W3005 warnings, the same as on `stage`
- sam validate: pass
- sam build: pass
- The CI `test` job, reproduced in a fresh venv: 1550 passed
- Cross-checks: no infra seams were touched, the script and handler are byte-identical, the token rule holds, the page is 58 KB, and the CSP is unchanged.

## Review

- Review rounds inside phases: 7, 6 of them cold and independent. Findings fixed: 1 BLOCK and several WARNs. Deferred: listed above.
- Pull request rounds: 0. No comments came in.

## Rollback

```bash
git revert -m 1 a1479e6   # undoes the whole merge of #115
```

## Action items

- [ ] Run `.implementation_plans/photo-upload-branding/MANUAL_QA.md` on the stage page
- [ ] Optional: send an official vector of the pattern strip to replace the redraw
- [ ] Optional: confirm the PP Gosha web licence, and ask whoever runs asmbly.org to add a CORS header for its fonts folder

<!--
Rules for this briefing. Don't remove them.
- Each bullet is one or two sentences.
- Admin actions come first and say when each must happen.
- Decisions, Deferrals and Skipped are required even when empty: write "None".
- Action items name files and lines, not "review the code".
- Run health is required even when the run was smooth: say so.
-->
