---
phase_id: 2
title: Both pages use the helper; every page is checked; docs
epic: 136
implements: [139]
depends_on: [1]
domain: [lambda, layer, docs]
estimated_size: M
---

# Phase 2: Both pages use the helper; every page is checked; docs

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`, "What this repository does", "Rules" and "Done means verified".
- This plan's `README.md` (Decisions 4–11) and phase 1's hand-off.
- `layers/common/python/common/csp.py`, `tests/page_csp.py` and `tests/test_page_csp.py`,
  as phase 1 left them.
- Both `lambda_function.py` files. In the kiln one, lines 1–64: imports, `PAGE_TEMPLATE`,
  `_STYLE_BLOCK`, `_style_hash` and `RESPONSE_HEADERS`. In the photo one: the docstring,
  imports, `ERROR_HEADERS`, `response_headers` and the nonce line in `lambda_handler`.
- `tests/capture_page_pins.py` (`PAGES`) and `tests/test_shared_brand.py`.
- `docs/CONTRIBUTING.md`: Table of Contents, "Adding a New Lambda Function" and
  "Coding Standards".
- The kiln README's "Errors and security headers" and "Testing", and the photo README's
  "What It Serves", "Why the Route Has No Authorizer" and "Testing".
- `docs/README.md` line 159 (the `/layers` bullet).

## Goal

- Neither function writes a CSP string. The kiln page calls `csp.hash_policy`, and the
  photo page calls `csp.nonce_policy`, `csp.new_nonce` and `csp.strict_policy`.
- Every header is byte-identical to `stage`: phase 1's pins and the kiln
  `EXPECTED_HEADERS` pass unchanged.
- `tests/test_page_csp.py` registers both pages:
  - it checks every hash page's hash against its served `<style>`;
  - it checks every nonce page's nonce on the header, the `<style>` and the `<script>`;
  - it fails if a function serves HTML without being registered, or builds a CSP by hand.
- `docs/CONTRIBUTING.md` has an "Adding a Public Page" section.
- Visitors see no change: #138's pins pass unchanged.

## Files to create

None.

## Files to modify

| File | Change |
| --- | --- |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py` | `from common import brand, csp`. Remove `_STYLE_BLOCK` and `_style_hash`, and the `base64`, `hashlib` and `re` imports (nothing else uses them; check with grep). `RESPONSE_HEADERS["Content-Security-Policy"] = csp.hash_policy(PAGE_TEMPLATE)`. The comment above `RESPONSE_HEADERS` says the policy comes from `common/csp.py`, and allows the one inline `<style>` of the filled shell by its hash. |
| `functions/classes/class_photo_upload_page/lambda_function.py` | `from common import brand, csp`; remove `import secrets`. `ERROR_HEADERS["Content-Security-Policy"] = csp.strict_policy()`. `response_headers` builds `csp.nonce_policy(nonce, [("img-src", "blob:"), ("connect-src", f"'self' https://{auth_domain}")])`, and its signature and other headers are unchanged. `nonce = csp.new_nonce()`. The module docstring's last paragraph says the brand tokens, the logo and the CSP come from the common layer (`common/brand.py`, `common/csp.py`), both standard library only. |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py` | `from common import brand, csp`. `test_style_hash_rejects_zero_or_two_style_blocks` calls `csp.style_hash_source` where it called `lambda_function._style_hash`, with the same three assertions and the same name. |
| `tests/test_page_csp.py` | The registry and four tests (below). |
| `docs/CONTRIBUTING.md` | Add a Table of Contents entry and an "Adding a Public Page" section after "Adding a New Lambda Function". Add one sentence to the "Tests" bullet of Coding Standards pointing at it (below). |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/README.md` | "Errors and security headers": the policy is built by `csp.hash_policy` in `layers/common/python/common/csp.py` over the filled shell. The 502 note names `csp.style_hash_source`. Testing: the shared checks in `tests/page_csp.py` and the registry. |
| `functions/classes/class_photo_upload_page/README.md` | "What It Serves": `__CSP_NONCE__` is a fresh `csp.new_nonce()` (`secrets.token_urlsafe(16)`). The header is built by `csp.nonce_policy`, and the 400 and 500 pages' policy by `csp.strict_policy()`, both from `common/csp.py`. Testing: the byte pins and the shared nonce check. |
| `docs/README.md` | Line 159, the `/layers` bullet: "…and the brand tokens and logo the two HTML pages share, and the Content-Security-Policy helper they use." |

`template.yaml`, `templates/*.yaml`, `template-cicd.yaml`, `configs/`, both `page.html`
files, `common/brand.py`, the photo page's script and its Node harness don't change.

## Implementation details

### lambda: kiln

```python
from common import brand, csp
...
PAGE_TEMPLATE: str = brand.fill_brand(PAGE_PATH.read_text(encoding="utf-8"))

# The page runs no script and loads nothing from another site. Its one inline <style> block,
# in the filled shell above, is allowed by its hash (common/csp.py).
RESPONSE_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": csp.hash_policy(PAGE_TEMPLATE),
}
```

- **Failure.** `page.html` with zero or two `<style>` blocks makes `csp.hash_policy` raise
  `ValueError` at import, as `_style_hash` does today. Every request then gets a 502, and
  the tests are the guard. Nothing new is logged, and no response changes.
- `_render_page`, the handler and every response are unchanged.

### lambda: photo

```python
from common import brand, csp
...
ERROR_HEADERS = {
    ...,
    "Content-Security-Policy": csp.strict_policy(),
}
...
def response_headers(auth_domain: str, nonce: str) -> dict[str, str]:
    """The page's headers: one nonce for its inline script and style, images only from
    blob: URLs, and fetches only to its own origin and the sign-in host."""
    return {
        ...,  # unchanged
        "Content-Security-Policy": csp.nonce_policy(
            nonce, [("img-src", "blob:"), ("connect-src", f"'self' https://{auth_domain}")]
        ),
    }
...
    nonce = csp.new_nonce()
```

- **Failure.** `nonce_policy` raises only for a nonce that isn't base64 (impossible from
  `new_nonce`) or for unsafe sources. `auth_domain` has already passed `HOST_PATTERN`
  (`^[A-Za-z0-9.-]+$`) by then, so it can't hold `;`, `,`, CR or LF. No new error path is
  reachable from a request. The 400 and 500 pages answer as before.
- The module still imports only `common.brand` and `common.csp` from the layer.
  `tests/test_shared_brand.py`'s `test_photo_page_imports_no_third_party_module` covers
  this unchanged.

### lambda (tests): the registry in `tests/test_page_csp.py`

```python
@dataclass(frozen=True)
class PublicPage:
    """One HTML page a visitor's browser opens."""
    folder: str                                   # the function's folder, from the repository root
    policy: str                                   # "hash" (no script) or "nonce" (a script)
    responses: Callable[[], list[dict[str, Any]]] # served responses that carry the page


def _kiln_responses() -> list[dict[str, Any]]:
    """What the handler sends for the empty list, a list with a drop-off, and the error page:
    RESPONSE_HEADERS with each body (lambda_handler returns exactly these)."""


def _photo_responses() -> list[dict[str, Any]]:
    """Two handler responses for the same request, with the page's environment patched."""


# Every public HTML page. A new page adds itself here; test_every_html_page_is_registered
# fails until it does.
PUBLIC_PAGES: dict[str, PublicPage] = {
    "kiln": PublicPage("functions/ceramics/kiln_dropoff_recent_entries_viewer", "hash", _kiln_responses),
    "photo": PublicPage("functions/classes/class_photo_upload_page", "nonce", _photo_responses),
}
```

- **`_kiln_responses`** uses `kiln.generate_html_page([])`,
  `kiln.generate_html_page([A_TASK])` and `kiln.generate_error_page()`, each with
  `dict(kiln.RESPONSE_HEADERS)`. That is exactly what `lambda_handler` returns, without
  mocking ClickUp. `A_TASK` is a local copy of the kiln test's
  (`{'id': 'abc123', 'custom_id': 'KO-1', 'name': 'Customer Z', 'date_created': '1704067200000'}`).
  The kiln test file's `test_csp_style_hash_matches_served_style` already covers the
  handler's own paths.
- **`_photo_responses`** sets the environment with
  `patch.dict("os.environ", {"STAFF_AUTH_DOMAIN": "asmbly-staff.auth.us-east-2.amazoncognito.com", "CLASS_PHOTO_APP_CLIENT_ID": "fakeappclientid123", "CLASS_PHOTO_DRY_RUN": "false"}, clear=True)`.
  The event is `{"requestContext": {"domainName": "facilities.asmbly.org", "path": "/class-photo-upload"}}`.
  It asserts each response's `statusCode` is 200.
- Import the two function modules as in `tests/test_shared_brand.py` (`as kiln`,
  `as photo`). No network: neither builder calls AWS.

### docs: "Adding a Public Page" in `docs/CONTRIBUTING.md`

Table of Contents: `- [Adding a Public Page](#adding-a-public-page)` after "Adding a New
Lambda Function". The section, about 40 lines, written for a volunteer who may not know
CSP. It names, in this order:

1. **Start from "Adding a New Lambda Function".** A public page is a function too.
   The steps `CLAUDE.md` requires still apply, and the section links to
   [Rules](../CLAUDE.md#rules) rather than restating them:
   - **A caller check.** Every HTTP route is public, and a new route must check its
     caller ([What this repository does](../CLAUDE.md#what-this-repository-does)). A page
     a browser opens directly can't send a token. The class photo upload page shows one
     answer: the page serves only public values, and the routes it calls sit behind a
     Cognito authorizer (its README, "Why the Route Has No Authorizer"). Say in the plan
     and the pull request how the new page's route checks its caller. #79 tracks the
     existing routes.
   - **A log group** named `/asmbly/lambda/<FunctionName>-${Stage}`, with a retention
     period.
   - **The deploy-role names.** The function and its log group go in
     `GitHubDeployPolicystage` and `GitHubDeployPolicyprod` in `template-cicd.yaml`, and
     the pull request's **Risk** section says an admin must redeploy that stack first.
2. **The shell: `page.html` next to `lambda_function.py`.**
   - One inline `<style>`, whose first rule is `:root`, holding `/* __BRAND_TOKENS__ */`
     and the page's own tokens.
   - `<!-- __ASMBLY_LOGO__ -->` where the logo goes. It is optional, and at most once.
   - The function reads the file once with `brand.fill_brand(...)` from
     `layers/common/python/common/brand.py`, which fills in `BRAND_TOKENS` and
     `ASMBLY_LOGO`.
   - Give the function `Layers: [!Ref CommonLayerARN]` and nothing else; `brand` and
     `csp` need no other layer.
   - Escape anything from outside with `html.escape`, and put it in last.
3. **The Content-Security-Policy, from `layers/common/python/common/csp.py`.** Never
   write the string by hand.
   - No script: `csp.hash_policy(filled_page)`, computed once at import over the filled
     shell, as the kiln viewer does.
   - A script: `nonce = csp.new_nonce()` on every request,
     `csp.nonce_policy(nonce, [(directive, sources), ...])` for what the page also needs,
     and the same nonce on its `<style nonce>` and `<script nonce>`, as the class photo
     upload page does.
   - Error pages with no style: `csp.strict_policy()`.
4. **Tests.**
   - Style, colour, contrast and logo checks: `tests/page_style.py`.
   - CSP checks: `tests/page_csp.py`.
   - Register the page in `PUBLIC_PAGES` in `tests/test_page_csp.py`; the tests fail
     until you do.
   - Add it to `PAGES` in `tests/capture_page_pins.py`, run
     `.venv/bin/python -m tests.capture_page_pins`, and commit the pins in its
     `tests/fixtures/`.
   - Pin its header string in its own test file, as the photo page's
     `test_csp_header_is_byte_for_byte_unchanged` does.
5. **Docs:** the function's README, and its entry in [README.md](README.md#core-services)
   (what it does, how it is triggered, its URL, and where the caller is configured).

The "Tests" bullet in Coding Standards gets one sentence after the `page_style`
sentences: "A page's Content-Security-Policy checks come from `tests/page_csp.py`; see
[Adding a Public Page](#adding-a-public-page)."

## Tests

New, in `tests/test_page_csp.py`:

| Test | Proves |
| --- | --- |
| `test_every_html_page_is_registered` | Two sets of folders must equal the registry's folders: every function folder with a `page.html` (`ROOT.glob("functions/*/*/page.html")`), and every `functions/*/*/lambda_function.py` whose text contains `text/html`. `set(PUBLIC_PAGES) == set(capture_page_pins.PAGES)`, with the same folder for each name. Each `policy` is `"hash"` or `"nonce"`. Story #139 criterion 3: the check isn't kiln-only, and a new page can't skip it. |
| `test_hash_pages_allow_only_their_served_style` | Parametrized over the `"hash"` pages (ids are the page names). Each sample response has `page_csp.style_hash_problems(response["headers"]["Content-Security-Policy"], response["body"]) == []`, with at least one response per page. Criterion 3. |
| `test_nonce_pages_put_a_fresh_nonce_on_style_and_script` | Parametrized over the `"nonce"` pages. There are at least two responses. Each has `page_csp.nonce_problems(policy, body) == []`, and the nonces (`page_csp.nonce`) are all different. Criterion 4, for every nonce page. |
| `test_no_function_builds_a_csp_by_hand` | For every `.py` file under `functions/` outside a `tests/` folder (AST): no string constant, f-string part included, matches `(?:^|[;\s])(default-src|script-src|style-src|img-src|connect-src|base-uri|form-action|frame-ancestors)\s`. Docstrings, which are expression statements, are skipped. Each registered page's `lambda_function.py` imports `csp` from `common` (an `ImportFrom` node with `module == "common"` that names `csp`). Criterion 1. |

Changed: `test_style_hash_rejects_zero_or_two_style_blocks`, retargeted to
`csp.style_hash_source` with the same assertions.

These must pass unchanged (criteria 2 and 6), and their files are not edited:

- the kiln tests `test_lambda_handler_sets_csp_header` (`EXPECTED_HEADERS`),
  `test_csp_style_hash_matches_served_style` and `test_csp_is_no_looser_than_before`;
- the photo tests `test_csp_header`, `test_nonce_changes_per_request`,
  `test_csp_header_is_byte_for_byte_unchanged`, `test_error_page_csp_is_unchanged`,
  `test_two_requests_get_different_nonces_on_header_style_and_script` and
  `test_serves_page_with_config_and_nonce`;
- #138's `test_served_tokens_are_the_stage_tokens`, `test_served_rules_are_the_stage_rules`
  (both pages), `test_logo_matches_both_pages`, `test_capture_script_reproduces_the_fixtures`,
  `test_changing_a_shared_token_changes_both_pages` and
  `test_photo_page_imports_no_third_party_module`;
- `test_page_with_50_dropoffs_is_under_60kb`, `test_served_page_is_small`, and the Node
  harness scenarios in `test_page_script.py`.

## Acceptance criteria

Each traced to story #139:

1. **(c1)** One shared helper, `common.csp`, builds both pages' policies and the photo
   error pages' policy. Neither function holds a CSP directive string
   (`test_no_function_builds_a_csp_by_hand`). Also,
   `grep -rn "default-src\|frame-ancestors" functions --include=lambda_function.py`
   finds nothing.
2. **(c2)** Both pages send exactly the same CSP as before:
   - kiln: 5 directives with the style hash (`EXPECTED_HEADERS`,
     `test_csp_is_no_looser_than_before`);
   - photo: 8 directives with a fresh nonce on each request (`test_csp_header`,
     `test_csp_header_is_byte_for_byte_unchanged`, `test_nonce_changes_per_request`);
   - photo error pages: `test_error_page_csp_is_unchanged`.

   Each is byte-identical to `origin/stage` (Verification).
3. **(c3)** Every hash page has its hash checked against its served `<style>`
   (`test_hash_pages_allow_only_their_served_style`), and the registry can't miss a page
   (`test_every_html_page_is_registered`).
4. **(c4)** Two requests to the photo page get different nonces, each equal on the
   header, the `<style>` and the `<script>`:
   `test_two_requests_get_different_nonces_on_header_style_and_script` (phase 1) and
   `test_nonce_pages_put_a_fresh_nonce_on_style_and_script`.
5. **(c5)** `docs/CONTRIBUTING.md` has an "Adding a Public Page" section. It names the
   shared tokens (`common/brand.py`, `BRAND_TOKENS`, `fill_brand`), the logo
   (`ASMBLY_LOGO`), the CSP helper (`common/csp.py`), and the test helpers
   (`tests/page_style.py`, `tests/page_csp.py`, `PUBLIC_PAGES`,
   `tests/capture_page_pins.py`). It also names the `CLAUDE.md` steps a new page needs:
   a caller check, a log group, and deploy-role names. Checked by reading it.
6. **(c6)** Visitors see no change: #138's pinned token and rule tests pass unchanged,
   and `git diff origin/stage -- functions/*/*/page.html tests/fixtures functions/*/*/tests/fixtures`
   is empty.

## Verification

```bash
.venv/bin/python -m pytest                                          # all pass
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml  # no template change; same 4 W3005 warnings as origin/stage
sam validate --region us-east-2
sam build                                                           # a layer change; the built template's CommonLayer ContentUri points at layers/common, which holds csp.py
```

- **Byte-identical headers against `stage`.** In a scratch worktree of `origin/stage`
  (`git worktree add <scratchpad>/stage origin/stage`, removed afterwards), run the same
  script as on the branch, from each tree's root, with `PYTHONPATH=.:layers/common/python`.
  It prints three headers:
  - `kiln.RESPONSE_HEADERS["Content-Security-Policy"]`;
  - `photo.response_headers("asmbly-staff.auth.us-east-2.amazoncognito.com", "n0nce")["Content-Security-Policy"]`;
  - `photo.ERROR_HEADERS["Content-Security-Policy"]`.

  The two outputs must be identical. Don't commit the output.
- **Served bodies are unchanged:** `kiln.generate_html_page([])` and
  `photo.render_page(config, "n")` are byte-equal between the two trees.
- **On stage after the deploy** (`MANUAL_QA.md` writes these out):
  - Open `<FacilitiesApiUrl>/KilnOpsDropoffRecentEntriesViewer`. The response's
    `Content-Security-Policy` is the 5-directive policy, the page is styled, and the
    browser console shows no CSP violation.
  - Fetch `<FacilitiesApiUrl>/class-photo-upload` twice with `curl -sD - <url>`. Each
    response has the 8-directive policy, its nonce is the one on that body's `<style>`
    and `<script>`, and the nonce differs between the two. Browsers hide the nonce
    attribute in the Elements panel, which is why this uses `curl`. In a browser,
    sign-in still works and the console shows no CSP violation.
  - The 400 and 500 pages can't be reached on stage without breaking the configuration
    (API Gateway routes only the page's own path to the function). Their 4-directive
    policy is covered by `test_error_page_csp_is_unchanged`.
  - The two pages look as they did before the deploy, at 320px and 1280px.

## Admin actions

None. There is no new named resource and no deploy-role change. For **Risk**: the
deploy publishes a new `common-layer-stage` version and updates the 12 functions that use
it.

## Hand-off

To be filled in when the phase is done: the final suite count, the byte-identical check's
result, and anything `/write-docs` or `MANUAL_QA.md` should know. After this phase,
#139 is complete. The pull request says `Closes #139` and `Closes #136`, and proposes
adding `csp` to `CLAUDE.md`'s "Shared helpers" map row for the person to decide.
