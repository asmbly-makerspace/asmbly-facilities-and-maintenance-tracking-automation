---
phase_id: 2
title: Both pages serve the shared tokens and logo
epic: 136
implements: [138]
depends_on: [1]
domain: [lambda, layer, infra, docs]
estimated_size: M
---

# Phase 2: Both pages serve the shared tokens and logo

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`, "Rules" and "Done means verified".
- This plan's `README.md` (Decisions 4–14) and phase 1's hand-off.
- `layers/common/python/common/brand.py` and `tests/test_shared_brand.py`, as phase 1
  left them.
- Both `page.html` files, both `lambda_function.py` files, and both page test files: the
  style sections, the CSP tests and the logo tests.
- `templates/classes.yaml`, `ClassPhotoUploadPageFunction` (lines 160–181). Compare the
  kiln function's `Layers` in `templates/ceramics.yaml` (lines 91–93).
- `tests/test_templates.py`, `test_class_photo_page_function_reads_nothing` (line 298),
  and `tests/test_page_style.py`, `_kiln_logo` (line 24).
- `template-cicd.yaml` lines 293–329, the stage function and layer statements, and the
  matching prod block. Read them only to confirm that no entry is needed.

## Goal

- Neither `page.html` has its own copy of the shared tokens or the logo; both serve them
  from `common.brand`.
- Every phase 1 pin still passes: the same tokens, rules and logo as on `stage`.
- Changing one shared token in `brand.py` changes it on both served pages, and the
  kiln page's CSP hash follows.
- The photo page function has `CommonLayer` and nothing else new.
- The docs say where the shared pieces live.

## Files to modify

| File | Change |
| --- | --- |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html` | The 32 shared declarations and their group comments leave `:root`. In their place, after `color-scheme: light;`, comes `    /* __BRAND_TOKENS__ */`. The footer `<svg class="logo">…</svg>` becomes `  <!-- __ASMBLY_LOGO__ -->`. The `:root` keeps this page's tokens (below). The opening comment says where the shared tokens come from. |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py` | `from common import brand`; `PAGE_TEMPLATE: str = brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))`. The comment above it says the brand tokens and logo are filled in once, before the CSP hash is computed. |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py` | `PAGE_HTML` becomes the served shell; a raw-file constant; one test rewritten (below). |
| `functions/classes/class_photo_upload_page/page.html` | The same: `    /* __BRAND_TOKENS__ */` after `color-scheme: light;`, and `    <!-- __ASMBLY_LOGO__ -->` in the header in place of the `<svg class="logo">`, indented four spaces as the `<svg>` is now. |
| `functions/classes/class_photo_upload_page/lambda_function.py` | `from common import brand`; `_template()` caches `brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))`. The module docstring says the page's brand tokens and logo come from the common layer. |
| `functions/classes/class_photo_upload_page/tests/test_lambda_function.py` | `PAGE_HTML` becomes the served shell; one new test (below). |
| `templates/classes.yaml` | `ClassPhotoUploadPageFunction` gets `Layers: [!Ref CommonLayerARN]`, and its comment is updated (below). |
| `tests/test_templates.py` | `test_class_photo_page_function_reads_nothing` expects that one layer. |
| `tests/test_page_style.py` | `_kiln_logo()` reads `brand.ASMBLY_LOGO`; the unused `KILN_PAGE` constant goes. |
| `tests/test_shared_brand.py` | Four new tests (below). |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md` | "Look and brand tokens" and "Tokens" (below). |
| `functions/classes/class_photo_upload_page/README.md` | "Brand and Design Tokens", the AWS Infrastructure row, and Testing (below). |
| `docs/README.md` | The `/layers` bullet (line 159). |

No new files. `template.yaml`, `template-cicd.yaml`, `configs/`, `layers/common/python/common/brand.py`
and the photo page's script and Node harness don't change.

## Implementation details

### lambda: what each page's `:root` keeps

Each page's raw `:root` keeps exactly its pinned tokens minus the 32 in `BRAND_TOKENS`.
`test_each_page_keeps_its_own_tokens` checks this. Its group comments stay.

**The kiln page (22 tokens):**
- Ceramics tints and shades: `--ceramics-shade`, `--ceramics-shade-60`, `--ceramics-40`,
  `--ceramics-20`, `--ceramics-10`.
- What each colour is for: `--page-bg`, `--text`, `--accent`, `--on-accent`,
  `--accent-strong`, `--accent-hover`, `--table-head-bg`, `--row-hover-bg`, `--line`,
  `--focus`, `--logo-colour`, `--error-bg`, `--error-edge`.
- The error glyph, `--glyph-error`.
- This page's own sizes: `--font-size-id`, `--content-max-width: 50rem`, `--icon-height`.

The derived-colour comment stays, with "the lasers tokens are shared" added.

**The photo page (47 tokens):**
- Area colours: `--woodwork`, `--metalwork`, `--textiles`, `--electronics`,
  `--printing-3d`.
- Purple tints and other derived colours: `--asmbly-purple-80`, `-60`, `-40`, `-20`;
  `--electronics-shade`, `--woodwork-20`.
- Every role token, from `--page-bg` to `--banner-edge`.
- The four glyphs.
- Its own sizes: `--radius-control`, `--content-max-width: 47.5rem`, `--pattern-height`,
  `--preview-max-height`, `--border-width-strong`, `--visually-hidden-size`,
  `--glyph-size`, `--glyph-offset`, `--underline-offset`, `--track-fill`,
  `--progress-height`, `--progress-fill`, `--breakpoint-wide`, with its comment.

The marker sits on its own line, indented four spaces, right after
`color-scheme: light;` and a blank line. The rules after `:root` aren't touched, which is
what `test_served_rules_are_the_stage_rules` checks.

### lambda: kiln `lambda_function.py`

```python
from common import brand
from common.aws import get_secret, get_json_parameter
from common.clickup import get_all_clickup_tasks
...
# The page shell (styles, header band, Refresh button, footer logo), read once per container,
# with the shared brand tokens and logo from the common layer filled in. The CSP hash below
# is computed over this filled shell, so it is the hash of the <style> every page serves.
PAGE_PATH = pathlib.Path(__file__).with_name("page.html")
PAGE_TEMPLATE: str = brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))
```

- `_style_hash`, `RESPONSE_HEADERS` and `_render_page` are unchanged. `_render_page`
  replaces only `__RELOAD_TEXT__` and `__MAIN_CONTENT__`, outside the `<style>`, so the
  list, empty and error pages all carry the hashed `<style>`.
- Failure: if `page.html` loses or doubles its token marker, `fill_brand` raises
  `ValueError` at import, as `_style_hash` already does for a missing `<style>`. Every
  request then fails (API Gateway answers 502), and the tests are the guard
  (`test_page_template_has_each_placeholder_once`). Nothing is logged at import, as
  today. No response or log line changes.

### lambda: photo `lambda_function.py`

```python
from common import brand
...
def _template() -> str:
    """page.html with the shared brand tokens and logo filled in, read once per container."""
    global _page_template
    if _page_template is None:
        _page_template = brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))
    return _page_template
```

- `render_page` still replaces `__CSP_NONCE__` and `__PAGE_CONFIG__` afterwards. The brand
  text contains neither, as phase 1's `test_shared_text_cannot_leave_its_place` checks.
- Failure: a marker problem raises `ValueError` from `_template()` inside the handler.
  The handler has no `try` around `render_page` today, so the invocation errors and API
  Gateway answers 502. This matches what a missing `page.html` does today, and the tests
  guard it. Don't add a new error path here: the 400 and 500 pages
  (`ERROR_PAGE`, `ERROR_HEADERS`) are unchanged, and story criterion 6 says they "answer
  as before".
- The module imports `common.brand` only, never `common.aws`, so no boto3 is loaded
  (`test_photo_page_imports_no_third_party_module`).

### infra: `templates/classes.yaml`

```yaml
  # Serves fixed HTML and reads nothing, so it has no policies. Its only layer is the
  # common layer, for the shared brand tokens and logo (common/brand.py).
  ClassPhotoUploadPageFunction:
    Type: AWS::Serverless::Function
    Properties:
      ...
      LoggingConfig:
        LogGroup: !Ref ClassPhotoUploadPageLogGroup
      Layers:
        - !Ref CommonLayerARN
      Environment:
        ...
```

- `CommonLayerARN` is already a parameter of this template (line 11) and is already
  passed from `template.yaml` (`ClassesStack`, line 448), so there is no new parameter.
- No new resource or IAM statement, and no `RequestsLayerARN`.
- **Deploy role: no change.** Attaching a layer needs two actions:
  - `lambda:UpdateFunctionConfiguration` on `function:ClassPhotoUploadPageFunction-<stage>`,
    already in `AllowLambdaFunctionManagement`.
  - `lambda:GetLayerVersion` on `layer:common-layer-<stage>:*`, already in
    `AllowLambdaLayerManagement`.

  Both stage and prod have these. `tests/test_templates.py`'s size test is unaffected.
- Effect at deploy: a new `common-layer-<stage>` version, and all 12 functions that use it
  are updated (README, Risk).

`tests/test_templates.py`, the updated test:

```python
def test_class_photo_page_function_reads_nothing() -> None:
    # The page function holds no secrets and calls nothing, so it gets no policies. Its one
    # layer is the common layer, for the shared brand tokens and logo (story #138).
    function = _load(ROOT / "templates" / "classes.yaml")["Resources"]["ClassPhotoUploadPageFunction"]["Properties"]
    assert "Policies" not in function and "Role" not in function
    assert function["Layers"] == [{"Ref": "CommonLayerARN"}]
    assert set(function["Environment"]["Variables"]) == {...as today...}
```

### lambda (tests): the page test files

- **Kiln:**
  - `PAGE_HTML = lambda_function.PAGE_TEMPLATE`, the served shell, with a comment.
  - `RAW_PAGE_HTML = lambda_function.PAGE_PATH.read_text(encoding="utf-8")`.
  - `SHEET`, `MARKUP` and `EXPECTED_CSP` keep reading `PAGE_HTML`, so the style, logo and
    CSP checks run on what is served.
  - `test_page_template_has_each_placeholder_once` becomes:
    - `PAGE_TEMPLATE == brand.fill_brand(RAW_PAGE_HTML)`;
    - `RAW_PAGE_HTML` has each brand marker once;
    - the existing `__MAIN_CONTENT__` and `__RELOAD_TEXT__` assertions, unchanged.
- **Photo:**
  - `PAGE_HTML = lambda_function._template()`, the served shell before the nonce and
    config, with a comment.
  - `STYLE_BLOCK` stays `<style nonce="__CSP_NONCE__">`.
  - New: `test_template_is_page_html_with_the_brand_filled`. It checks
    `lambda_function._template() == brand.fill_brand(lambda_function.PAGE_PATH.read_text(encoding="utf-8"))`,
    that the raw file has each brand marker once, and that `__CSP_NONCE__` and
    `__PAGE_CONFIG__` are still in the template.
- Every existing test keeps its name and passes. Check: the collected test IDs before and
  after (`pytest --collect-only -q`) differ only by the added tests.

### lambda (tests): `tests/test_shared_brand.py` additions

| Test | Proves |
| --- | --- |
| `test_page_html_has_no_copy_of_the_shared_tokens_or_logo` | For each raw `page.html`: no `BRAND_TOKENS` name is defined in its `:root`, read with `page_style.Stylesheet.from_page(raw, …).tokens()`, which works because the marker is a comment. It has no `<svg class="logo"` and none of the 17 `d="…"` values of `ASMBLY_LOGO`, and each marker exactly once. Story criterion 1: "neither page's `page.html` has its own copy". |
| `test_each_page_keeps_its_own_tokens` | For each raw `page.html`, its token names equal its pinned names minus `BRAND_TOKENS`. Explicitly: kiln `--accent: var(--ceramics)`, `--content-max-width: 50rem`, `--error-bg`, `--table-head-bg`; photo `--brand: var(--asmbly-purple)`, `--content-max-width: 47.5rem`, the five area colours, `--progress-height`, `--progress-fill`, `--control-border`. Story criterion 2. |
| `test_changing_a_shared_token_changes_both_pages` | Steps below the table. Story criteria 4 and 5. |
| `test_photo_page_imports_no_third_party_module` | A subprocess (`sys.executable -I -c`) puts the repository root and `layers/common/python` on `sys.path`, imports `functions.classes.class_photo_upload_page.lambda_function`, and reports `False` for `boto3`, `botocore` and `requests` in `sys.modules`. Story criterion 6: the function gets the common layer and nothing else. |

`test_changing_a_shared_token_changes_both_pages`, step by step:

1. `monkeypatch.setattr(brand, "BRAND_TOKENS", brand.BRAND_TOKENS.replace("--asmbly-purple: #292D6A;", "--asmbly-purple: #123456;"))`.
   Assert that the replacement changed the text.
2. Kiln: `importlib.reload(kiln)`. Each of `generate_html_page([])`,
   `generate_html_page([task])` and `generate_error_page()` serves `--asmbly-purple: #123456`.
   The `style-src` of `kiln.RESPONSE_HEADERS["Content-Security-Policy"]` equals the
   SHA-256 source of that page's `<style>` text.
3. Photo: `monkeypatch.setattr(photo, "_page_template", None)`. A handler call, with
   `patch.dict("os.environ", {...}, clear=True)` and the page's event fixture, serves
   `#123456` in its `<style nonce=…>`.
4. Teardown, in a `try`/`finally` or a fixture: `monkeypatch.undo()`, then
   `importlib.reload(kiln)`. The kiln module is then filled with the real value again for
   later tests. The photo cache goes back to its earlier value through the undo.

### docs

- **Kiln README, "Look and brand tokens" and "Tokens":**
  - The shell is `page.html` with two more markers, `/* __BRAND_TOKENS__ */` and
    `<!-- __ASMBLY_LOGO__ -->`, filled from `layers/common/python/common/brand.py` once
    per container, before the CSP hash is computed.
  - The token list says which tokens are shared (link the module) and which are this
    page's.
  - "defined once in the `:root` block … in `page.html`" becomes "defined once: the shared
    ones in `common/brand.py`, the page's own in `page.html`".
  - Testing: the pins in `tests/fixtures/pinned_*` and how to regenerate them
    (`.venv/bin/python -m tests.capture_page_pins`, committed in phase 1).
  - A note that a change to `brand.py` changes both pages and the kiln page's CSP hash,
    which is recomputed at import.
- **Photo README:**
  - The same in "Brand and Design Tokens"; the brand colour table marks which colours are
    shared.
  - The AWS Infrastructure row: "no layers, no policies" becomes "the common layer only
    (brand tokens and logo), no policies".
  - Testing: the pins.
- **`docs/README.md` line 159:** "`/layers`: shared code and dependencies:
  `requests_layer` (the `requests` library) and `common` (the helpers for AWS, ClickUp,
  Slack, Neon, Discourse, Google Forms and GitHub, and the brand tokens and logo the two
  HTML pages share)."
- **`CLAUDE.md`:** not edited (README Decision 12). The pull request proposes adding
  "brand tokens and logo" to the "Shared helpers" row.

## Tests

- New: the 4 in `tests/test_shared_brand.py` above, plus
  `test_template_is_page_html_with_the_brand_filled`.
- Changed: `test_page_template_has_each_placeholder_once` (kiln),
  `test_class_photo_page_function_reads_nothing`, and `tests/test_page_style.py`'s
  `_kiln_logo` helper.
- Every other test passes unchanged, including:
  - the phase 1 pins;
  - the kiln CSP tests (`test_csp_style_hash_matches_served_style`,
    `test_csp_is_no_looser_than_before`, `test_lambda_handler_sets_csp_header`);
  - the photo `test_csp_header`;
  - `test_page_with_50_dropoffs_is_under_60kb` and `test_served_page_is_small`;
  - the style, contrast and logo tests;
  - the Node harness scenarios in `test_page_script.py`.

## Acceptance criteria

Each traced to story #138:

1. **(c1)** The 32 shared tokens and the 17-path logo are defined only in
   `layers/common/python/common/brand.py`. Neither `page.html` has a copy:
   `test_page_html_has_no_copy_of_the_shared_tokens_or_logo`. Also, `grep -c 'm183.67,64.46'`
   (the first logo path) finds it in `brand.py` only, apart from fixtures and the plan;
   the pinned fixtures hold no logo.
2. **(c2)** Each page's raw `:root` keeps exactly its own tokens, including the kiln's
   ceramics accent, error and table colours and 50rem width, and the photo page's purple
   band, area colours, control and progress tokens and 47.5rem width:
   `test_each_page_keeps_its_own_tokens`.
3. **(c3)** Served tokens and rules equal the stage pins
   (`test_served_tokens_are_the_stage_tokens`, `test_served_rules_are_the_stage_rules`), and
   the served logo is the stage logo (`test_logo_matches_both_pages`). The visual check at
   320px and 1280px is in `MANUAL_QA.md`.
4. **(c4)** Changing one shared token's value in `brand.py` changes it on both served
   pages: `test_changing_a_shared_token_changes_both_pages`.
5. **(c5)** The kiln page sends its 5-directive hash CSP, and the hash matches the served
   `<style>` on the list, empty and error pages (the existing kiln CSP tests, plus step 2
   of the both-pages test). The photo page sends its 8-directive nonce CSP
   (`test_csp_header`).
6. **(c6)** `ClassPhotoUploadPageFunction` has `Layers: [!Ref CommonLayerARN]` and still no
   policies (`test_class_photo_page_function_reads_nothing`). It loads no third-party module
   (`test_photo_page_imports_no_third_party_module`). `git diff origin/stage --
   template-cicd.yaml template.yaml` is empty. `brand.py` is standard-library only (phase
   1). The 400 and 500 pages are unchanged (`test_unexpected_path_returns_400`,
   `test_missing_env_returns_500_without_details`).
7. **(c7)** The kiln page with 50 rows is under 60 KB
   (`test_page_with_50_dropoffs_is_under_60kb`; about 25.8 KB on stage), and the photo
   page is under 100 KB (`test_served_page_is_small`; about 70 KB).

## Verification

```bash
.venv/bin/python -m pytest                                          # all pass; 1866 + 5 = 1871
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml  # same warnings as origin/stage (4 W3005 in template.yaml)
sam validate --region us-east-2
sam build    # then: .aws-sam/build/template.yaml has CommonLayer's ContentUri at ../../layers/common
             # (SAM copies no layer without a BuildMethod), and
             # .aws-sam/build/ClassesStack/template.yaml lists a layer for ClassPhotoUploadPageFunction
```

- Show that the served pages didn't change, apart from the reordered `:root` and the
  logo whitespace:
  - Render each page on `origin/stage` and on the branch: kiln `generate_html_page([])`,
    photo `render_page(config, "n")`. Use a scratch worktree or `git stash`; don't commit
    the output.
  - Diff the `<style>` blocks after sorting the `:root` declarations, and the markup
    after collapsing whitespace.
  - Expected: only the `:root` comments and order differ, plus the two spaces before the
    kiln page's `</svg>`.
- On stage after the deploy (`MANUAL_QA.md` writes these out):
  - Open `<FacilitiesApiUrl>/KilnOpsDropoffRecentEntriesViewer` and
    `<FacilitiesApiUrl>/class-photo-upload` at 320px and 1280px wide, and compare them
    with screenshots taken before the merge: no visible difference.
  - In the browser console, no CSP violation on either page.
  - The photo page with a bad path answers 400 with its plain page. Its 500 page can't be
    reached on stage without breaking the configuration; it is covered by tests.
  - `ClassPhotoUploadPageFunction-stage`'s configuration lists one layer,
    `common-layer-stage:<new version>` (`aws lambda get-function-configuration`,
    read-only).

## Admin actions

None. There is no new named resource and no deploy-role change.

## Hand-off

Filled in when the phase is done. Story #139 can rely on:

- `common.brand.fill_brand` and both markers as the way a page gets the shared tokens and
  logo.
- The kiln pattern of filling first and hashing the filled `<style>`, and the photo
  pattern of filling first and adding the nonce after.
- The pins, which `/write-docs` and #139 should mention when they describe adding a page.
