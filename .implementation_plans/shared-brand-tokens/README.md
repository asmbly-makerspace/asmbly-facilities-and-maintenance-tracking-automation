---
plan: shared-brand-tokens
epic: 136
---

# Shared brand tokens: implementation plan

**Created:** 2026-10-17

## Overview

The kiln drop-off viewer (`functions/ceramics/kiln_dropoff_recent_entries_viewer/`) and
the class photo upload page (`functions/classes/class_photo_upload_page/`) are the
repository's only two HTML pages. Each `page.html` carries its own copy of the Asmbly
brand tokens and of the 17-path Asmbly logo. At `stage` 6fd11c9, 35 tokens have the same
name and value on both pages, and the two logos are the same apart from indentation. A brand
change has to be made twice, and the copies can drift.

After this plan, one module in the common layer, `layers/common/python/common/brand.py`,
holds the 32 shared brand tokens (`BRAND_TOKENS`) and the logo (`ASMBLY_LOGO`). It imports
nothing outside the Python standard library. Each `page.html` keeps only its own tokens,
plus two markers: `/* __BRAND_TOKENS__ */` inside its `:root` block and
`<!-- __ASMBLY_LOGO__ -->` where the logo goes. Each function fills the markers with
`brand.fill_brand` when it reads `page.html`: the kiln function at import, before it
computes its CSP style hash, and the photo page function in `_template()`, before the
nonce and config go in. The photo page function gets the existing `CommonLayer`. It
gets no other layer and no IAM change, and the deploy role doesn't change.

Visitors see no change. Phase 1 pins each page's tokens and CSS rules as they are on
`stage` before the refactor, and phase 2 has to keep those pins passing.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #138 | Brand colours, type, spacing and the Asmbly logo come from one place | 1, 2 |

Both phases go into one pull request. That pull request lands phase 2, so it says
`Closes #138` and `Refs #136`. The epic stays open: #139 ("A new page can reuse the CSP
helper and the shared pieces") builds on this plan in a later run.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [Brand module and the stage pins](phase-1-brand-module-and-stage-pins.md) | layer, lambda | L | [ ] Pending |
| 2 | [Both pages serve the shared tokens and logo](phase-2-pages-use-shared-brand.md) | lambda, layer, infra, docs | M | [ ] Pending |

## Dependencies

- **Satisfied:** #137, the shared test module `tests/page_style.py` (PR #147), and #148's
  tightened `FONT_STACK` and top-level selector splitting (PR #149). Both are merged on
  `stage` at 6fd11c9. This plan uses `page_style.Stylesheet`, `find_logo` and
  `logo_problems` from that module.
- No secret, SSM parameter, third-party setup or other plan is needed.
- Phase 2 depends on phase 1. It needs `common.brand` and the pins that prove the
  refactor changed nothing.

## Parallelism

Two phases in sequence (phase 2 `depends_on: [1]`), so no pair can run in parallel.
They also share `tests/test_shared_brand.py`, both page test files and both function
READMEs. Don't build #139 while this plan is open, because it will edit the same files.

## Admin actions

None.

- No new named resource (function, layer, log group, SSM parameter, table or rule), so
  `template-cicd.yaml` doesn't change and no admin redeploy is needed.
- Attaching `CommonLayer` to `ClassPhotoUploadPageFunction-<stage>` needs only permissions the
  deploy role already has:
  - `lambda:UpdateFunctionConfiguration` on that function (`AllowLambdaFunctionManagement`,
    `template-cicd.yaml` lines 293–319 for stage and the matching prod block).
  - `lambda:GetLayerVersion` on `common-layer-<stage>:*` (`AllowLambdaLayerManagement`,
    lines 320–329).
  - The other 11 functions attach this layer through the same role today.
- No secret, webhook, Slack app setting or schedule changes.

**Risk for the pull request** (not an admin action): `layers/common/` changes, so the
stage deploy publishes a new `common-layer-stage` version and updates every function that
uses it. That is the 11 that use it today plus `ClassPhotoUploadPageFunction-stage`, 12
in all, in one deploy. Prod gets the same when `/promote` runs. No function's behavior
changes apart from the two pages, which serve the same tokens, rules and logo.

## Related work

- **#137 / PR #147 (merged):** `tests/page_style.py` and the two page test files this
  plan edits. Its plan, `.implementation_plans/shared-style-checks/`, warned that #138
  edits the same files.
- **#148 / PR #149 (merged):** stricter `FONT_STACK` and selector splitting in
  `tests/page_style.py`. The shared font stacks must still pass it, and they do on
  `stage`.
- **#139 (open, epic #136):** the CSP helper and the "Adding a public page" docs. It
  depends on this plan and will reuse `common.brand.fill_brand`.
- **#79 (open):** caller checks on the public routes. These two routes are unchanged
  here, as the epic's Out of scope says.
- Known and unchanged: `CommonLayer`'s `ContentUri: layers/common/` packages
  `layers/common/tests/`, so the new `test_brand.py` ships in the layer, as the other
  layer tests do. The shared-style-checks briefing flagged this for a possible follow-up
  issue.

## Out of scope

- Making the pages look alike. Each page keeps what differs today: the kiln page's
  ceramics accent, its error, table, line and focus colours, the 50rem width and the logo
  in the footer; the photo page's purple band, area colours, control and progress tokens,
  the 47.5rem width and the logo in the header.
- The CSP code, a CSP helper and the "Adding a public page" docs (#139).
- The photo page's script, its Node harness (`tests/page_script_harness.mjs`, which reads
  only the script and element IDs from the raw `page.html`, and neither changes) and its
  API.
- Caller checks on these routes (#79) and helper exception text (#95).
- Keeping `tests/` folders out of the Lambda and layer packages.
- The `CommonLayer` resource's `Description` ("aws, clickup, slack"), which is already
  incomplete. Changing it is unrelated to the story.

## Security

- **No new access.** No route, authorizer, IAM statement, secret or log line changes. The
  photo page function still has no policies. With the layer attached, it imports only
  `common.brand`, which imports nothing (a test checks this), so no boto3 or requests code
  is loaded into it.
- **The shared text can't break out of its place.** `BRAND_TOKENS` holds no `{`, `}`,
  `<` or `>`, so it can't close the `:root` rule or the `<style>` element. Neither
  constant contains a marker of any page (`__…__`). Tests in
  `layers/common/tests/test_brand.py` check both. The brand text is filled in before
  either page's own placeholders, and the kiln page still puts ClickUp text in last,
  escaped with `html.escape`.
- **CSP unchanged in shape.** The kiln page keeps its 5-directive hash CSP. The hash is
  computed at import over the filled page, so it still matches the served `<style>` on
  the list, empty and error pages. Its value changes, because the served `:root` text
  changes order and comments. The photo page keeps its 8-directive nonce CSP. The
  existing tests that check both stay as they are.

## Decisions

Made without asking, inside `/offshore`:

1. **Scope is story #138 only.** Alternative: also plan #139. The orchestrator scoped
   this run to #138, and #139 builds on it in a later run.
2. **Two phases: pins and module first, then the switch.** Alternatives: one L phase, or
   three (kiln and photo switched separately).
   - Phase 1 captures the pins from `stage` (6fd11c9) and proves `common.brand` holds
     exactly the values and logo both pages serve, while the pages are unchanged. The
     pins then show "before".
   - Phase 2 switches both pages and must keep every pin passing: "after".
   - Switching the pages in two phases would leave a commit where only one page uses the
     module, and the "changing a shared token changes both pages" test could not be
     written yet.
3. **One module holds both.** `layers/common/python/common/brand.py` holds
   `BRAND_TOKENS` (CSS text) and `ASMBLY_LOGO` (the `<svg>` element), so each is
   defined in exactly one file. Alternative: data files (`brand_tokens.css`,
   `asmbly_logo.svg`) and a reader. Rejected:
   - Python constants need no file-path handling at run time.
   - Tests can patch the constants directly.
   - The logo can't render on its own anyway: it carries no `xmlns` or `fill`, which
     `page_style.LOGO_FORBIDDEN` forbids.
4. **The shared set is the story's list, exactly: 32 tokens.**
   - **Brand colours present on both pages:** `--asmbly-purple`, `--asmbly-white`,
     `--midnight-black`, `--ceramics`, `--lasers`.
   - **The derived `--lasers-*` tints:** `--lasers-shade`, `--lasers-20`.
   - **Font stacks:** `--font-body`, `--font-heading`, `--font-mono`.
   - **Type sizes:** `--font-size-body`, `-h1`, `-h2`, `-small`.
   - **Line heights and weights:** `--line-height`, `--line-height-heading`,
     `--weight-heading`, `--weight-strong`.
   - **Spacing:** `--space-1` to `--space-6`, `--gutter`.
   - **Radius:** `--radius`.
   - **Border, focus and tap-target sizes:** `--border-width`, `--border-width-accent`,
     `--focus-width`, `--focus-offset`, `--tap-target`.
   - **Logo height:** `--logo-height`.

   Three other tokens have the same name and value on both pages: `--page-bg`, `--text`
   and `--glyph-error`. They are what a page uses a colour for, and which glyph its error
   shows. The story's list doesn't name them, so each page keeps its own. A test pins this
   choice.

   The photo page's other area colours stay on that page. The story says so, and sharing
   them would add five tokens to the kiln page's served `:root`, which its pin forbids.
5. **The markers are comments.** `/* __BRAND_TOKENS__ */` and `<!-- __ASMBLY_LOGO__ -->`
   keep the raw `page.html` valid CSS and HTML. `page_style` can still parse the raw file
   (it strips comments), which lets a test prove the raw file defines only the page's own
   tokens.
6. **Fill once, when the page is read.**
   - The kiln function sets `PAGE_TEMPLATE = brand.fill_brand(PAGE_PATH.read_text(...))`
     at import, so `_style_hash(PAGE_TEMPLATE)` hashes exactly the `<style>` it serves.
   - The photo function fills the page inside `_template()`, before `render_page`
     replaces the nonce and the config.
   - `fill_brand` reads the module's constants when it is called, not when it is
     defined, so a patched value reaches both pages.
   - `fill_brand` requires the token marker exactly once and the logo marker at most once,
     and raises `ValueError` otherwise. A page without a logo is allowed, for #139's next
     page; two copies of a marker is a mistake.
7. **Pins are fixtures captured from `stage` 6fd11c9 with `git show`.** Each page has two:
   - `tests/fixtures/pinned_tokens.json`: the served `:root` tokens, compared as a dict,
     because the order of the declarations inside `:root` changes and doesn't matter when
     each name is defined once.
   - `tests/fixtures/pinned_rules.css`: every rule after `:root`, compared line by line
     with trailing whitespace and blank lines dropped.

   Alternative: SHA-256 digests. Rejected, because a failing digest doesn't show what
   changed. A deliberate later change to a page's look updates its fixtures in the same
   commit (the test docstrings say how).
8. **The logo is pinned by comparison, not by a copy.** In phase 1, a test checks that
   `brand.ASMBLY_LOGO`, with whitespace collapsed, equals the logo each page serves; the
   pages still carry their own copies then. In phase 2 the same test checks that both
   pages serve the module's logo. The served whitespace inside the kiln page's `<svg>`
   changes by two spaces before `</svg>`, which nobody can see. The photo page's logo
   stays byte-identical.
9. **Where the tests go.**
   - `layers/common/tests/test_brand.py`: the module's own tests, using pytest and the
     standard library only, next to the other layer tests.
   - `tests/test_shared_brand.py`: the tests that span both pages, in the root `tests`
     package, which no template packages.
   - The pins live in each page's own test file.
10. **"Standard library only" is checked two ways.** An AST test checks that every import
    in `brand.py` is in `sys.stdlib_module_names`, with no relative import. A subprocess
    test imports the photo page's `lambda_function` with only the repository and
    `layers/common/python` on the path, and checks that `boto3`, `botocore` and `requests`
    are not loaded. That proves the photo function needs no requests layer.
11. **The template change is one `Layers` entry.** It goes on `ClassPhotoUploadPageFunction`
    in `templates/classes.yaml`. `CommonLayerARN` is already a parameter of that template,
    and `template.yaml` already passes it (`ClassesStack`, line 448). There is no new
    parameter, IAM statement or deploy-role entry. `tests/test_templates.py`'s
    `test_class_photo_page_function_reads_nothing` changes from "no layers" to "exactly
    `[!Ref CommonLayerARN]`, still no policies". The test is updated, not deleted.
12. **`CLAUDE.md` isn't edited.** Its map row "Shared helpers (AWS, ClickUp, Slack, Neon,
    Discourse, Google Forms, GitHub)" would gain "brand tokens and logo". As in the
    shared-style-checks run, the row is proposed in the pull request for the person to
    add, because `CLAUDE.md` is agent configuration.
13. **The visual check at 320px and 1280px on stage goes in `MANUAL_QA.md`.** It is for a
    person; the tests here pin tokens, rules and the logo. No browser automation is
    added.
14. **Docs:**
    - Both function READMEs: where the shared tokens and logo come from, and the pins.
    - The photo README's "no layers" row in AWS Infrastructure.
    - In `docs/README.md`, the `/layers` bullet, which says the folder holds only
      `requests`. That is already wrong, and this plan adds a reason to read it.
    - No service's behavior, trigger or URL changes.
15. **Closing keywords:** the final pull request says `Closes #138` and `Refs #136`.
