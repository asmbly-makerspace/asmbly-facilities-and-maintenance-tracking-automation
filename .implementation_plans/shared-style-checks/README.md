---
plan: shared-style-checks
epic: 136
---

# Shared style checks: implementation plan

**Created:** 2026-10-17

## Overview

The kiln drop-off viewer (`functions/ceramics/kiln_dropoff_recent_entries_viewer/`) and
the class photo upload page (`functions/classes/class_photo_upload_page/`) are the
repository's only two HTML pages. Each page's test file carries its own copy of the
same style-check machinery: the regexes that read the `:root` token block, the colour
helpers (`_channels`, `_mix`, `_luminance`, `_contrast`), the CSS-rule parser (`_rules`,
`_rule`), and the bodies of the token, contrast and logo tests. The kiln copy says so
itself ("copied from the class photo upload page's tests, adapted", line 681). A fix
to one copy does not reach the other.

After this plan, one test-only module, `tests/page_style.py`, holds the token-parsing,
colour, contrast, CSS-rule and logo-check helpers, and has its own tests in
`tests/test_page_style.py`. Each page's test file keeps only its own data (brand
colours, derived colours, contrast pairs, allowed words and literals, reserved tokens)
and its page-specific tests, and calls the shared module for everything else. Every
test that ran before still runs, under the same name. No page, handler, template or
served response changes, and nothing `sam build` produces contains the module.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #137 | Both pages' style checks come from one test module | 1 |

The pull request that lands phase 1 says `Closes #137` and `Refs #136`. The epic stays
open: #138 ("Brand colours, type, spacing and the Asmbly logo come from one place") and
#139 ("A new page can reuse the CSP helper and the shared pieces") are later work in
their own plans and pull requests, and build on this one.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Shared style-check module](phase-1-shared-style-check-module.md) | lambda, docs | L | [x] Complete |

## Dependencies

- **Satisfied:** the kiln Central time fix (#140, `fix/kiln-dropoff-central-time`) and
  bug #95's fix (#146, `feature/safe-exception-text`) are merged on `stage` (b96cac3).
  Both edited the kiln test file; #137's notes asked for them to land first.
- No secret, SSM parameter, third-party setup or other plan is needed.
- One phase, so no phase depends on another.

## Parallelism

One phase: nothing to run in parallel. Don't build #138 or #139 at the same time as
this plan: both will edit the two page test files and the new `tests/page_style.py`.

## Admin actions

None. No named resource, secret, SSM parameter, route, schedule, template or deploy-role
change; `template-cicd.yaml` is not touched. The change is test code and docs only, so
the stage deploy changes nothing in AWS.

## Related work

- **#138** (open, epic #136): moves the brand tokens and the Asmbly logo into the common
  layer. It builds on this plan's module (the token and logo checks) and edits the same
  test files. Depends on this plan.
- **#139** (open, epic #136): the CSP helper and shared pieces for a new page. Depends on
  #138 and so on this plan.
- **#140** and **#146** (merged): edited the kiln test file; this plan starts from the
  result.
- Plans `kiln-dropoff-ceramics-branding` and `photo-upload-branding`: wrote the two copies
  of the checks this plan merges. Their documents stay as history.
- Found while planning, not fixed here (for the person to decide whether to open an
  issue): every function's `CodeUri` packages its `tests/` folder into the Lambda zip, and
  `CommonLayer`'s `ContentUri: layers/common/` packages `layers/common/tests/` and
  `layers/common/python/tests/` into the layer. Test code ships to Lambda today. This
  plan adds nothing to that: the new module is outside every packaged folder.

## Out of scope

- Moving any token, colour, the logo or the CSP code into the common layer (#138).
- Making the pages look alike, or changing any page, handler, template or response.
- Merging the page-specific tests (`test_ceramics_is_the_accent`, the photo page's
  message-kind, focus and tap-target tests, the kiln band and table tests). They stay in
  their page's file; they only switch to the shared helpers for parsing.
- The photo page's script tests (`test_page_script.py`, the Node harness).
- Excluding test folders from the Lambda packages (see Related work).

## Security

Test code only. No route, IAM statement, secret, log line or response changes, and the
new module is never imported at runtime and never packaged (phase 1 adds a test that
fails if a template ever packages the folder it is in, and the verification step checks
`.aws-sam/build`). The helper's own tests read the kiln page's committed `page.html` and
small inline CSS strings; they call no network.

## Decisions

Made without asking, inside `/offshore`:

1. **Scope is story #137 only.** Alternative: plan the whole epic. The orchestrator
   chose one story per pull request; #138 and #139 build on this and get their own runs.
2. **One phase, size L.** Alternative: two phases (module plus kiln, then photo plus
   docs). The module's API has to fit both pages' differences (the photo page's nonce
   `<style>`, grid-area strings, `font: inherit`, `fill="url(#…)"`, `fr` units), so it is
   designed against both at once; most of the diff is deleted duplicates, and a split
   would leave an intermediate commit where the photo page still keeps its own copy.
3. **The module is `tests/page_style.py`, and `tests/` becomes a regular package (an
   empty `tests/__init__.py`).** Tests import it with `from tests import page_style`.
   `pytest.ini` puts `.` and `layers/common/python` on `sys.path`, and
   `layers/common/python/tests/` (no `__init__.py`) is also a directory named `tests`:
   today `import tests` resolves to a namespace package spanning both folders (checked
   with `.venv/bin/python`). A regular package at the repository root is found first and
   wins outright, so the import can't depend on which `tests` folders exist. The four
   existing root test modules become `tests.test_templates` and so on instead of
   top-level `test_templates`; nothing imports them by name (checked). Alternatives: rely
   on the namespace package (works today, but silently depends on no other `tests`
   folder on the path gaining an `__init__.py`), or a new top-level folder (one more
   place for volunteers to learn).
4. **Checks return a list of problems; they don't assert.** pytest rewrites `assert`
   only in test modules and conftest files, so asserts inside `tests/page_style.py`
   would fail with bare messages. Each `*_problems` function returns `list[str]` (empty
   means pass), the page tests write `assert page_style.x_problems(...) == []`, and pytest
   prints the list. This also makes story criterion 4 ("the helper reports a failure")
   directly testable. Parsing helpers that meet malformed input (no style block, two
   style blocks, a token that is not a colour, no rule for a selector) raise `ValueError`
   or `LookupError` with a message, which fails the calling test as the old `assert`
   did. Alternative: `pytest.register_assert_rewrite` in `tests/__init__.py`.
5. **Every existing test keeps its name, its parametrization and its assertions' scope.**
   The function READMEs name tests (`test_colour_pairs_meet_contrast`,
   `test_styles_use_tokens_only`, `test_tokens_are_defined_once`, …), and story criterion
   3 counts tests. Baseline at b96cac3: 73 tests collected in the kiln file, 113 in the
   photo page's `test_lambda_function.py`, 1831 in the whole suite. Phase 1 compares the
   collected test IDs before and after (`comm -23` must print nothing).
6. **One shared logo check, with the kiln's stricter forbidden list for both pages.**
   The photo page's test forbade only `fill=` and `xmlns` in the logo; the kiln's forbade
   `fill`, `stroke`, `style`, `xmlns`, `href` and `<image`. The photo page's logo has none
   of the six (checked), so the shared check passes on it unchanged and is stricter
   there. Alternative: a per-page forbidden list (keeps a difference nobody chose).
7. **Where the two pages' checks differ in substance, the difference is a parameter or
   stays in the page's file.** Parameters: allowed value words, allowed words inside
   quoted strings (the photo page's grid areas; none on the kiln page), allowed `font:`
   shorthand values (`inherit` on the photo page; none on the kiln page), the minimum
   declaration count (60 and 100), token value pattern (the photo page allows `fr`),
   glyph-name exemptions, SVG attributes and the allowed `fill` value. Page-local: the
   `--space-N` step check (the kiln page requires ascending pixel steps, the photo page
   unique values), the markup's forbidden strings, the photo page's breakpoint check.
   Alternative: unify them, which would change what a test enforces.
8. **`Stylesheet.from_page` requires exactly one match of the page's style-block
   pattern on both pages.** The kiln helper already did; the photo helper took the first
   match. The photo page has exactly one `<style nonce=` (its own
   `test_page_has_one_inline_script_and_style`), so this passes and is stricter.
9. **Absence from the build is proved two ways.** A test in `tests/test_page_style.py`
   reads every `CodeUri` and `ContentUri` in `template.yaml` and `templates/*.yaml` and
   fails if `tests/page_style.py` is inside one, so a check catches it on every run; and
   phase 1's verification runs `sam build` and searches `.aws-sam/build` for the module.
10. **Docs:** both function READMEs (their style-test sections say where the shared
    checks live), `docs/CONTRIBUTING.md` (the Tests bullet), and one row in `CLAUDE.md`'s
    map. (Prep amendment: the `CLAUDE.md` row is proposed in the pull request for the
    person to add, not committed by the unattended run.) `docs/README.md` doesn't change: no service's behavior, trigger or URL changes.
11. **Closing keywords:** the final pull request says `Closes #137` and `Refs #136`.
