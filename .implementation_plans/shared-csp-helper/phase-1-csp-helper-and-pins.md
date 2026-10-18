---
phase_id: 1
title: CSP helper, shared CSP checks and the header pins
epic: 136
implements: [139]
depends_on: []
domain: [layer, lambda]
estimated_size: M
---

# Phase 1: CSP helper, shared CSP checks and the header pins

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`, "Rules" and "Done means verified".
- This plan's `README.md`, Decisions 3–9 and 11.
- `layers/common/python/common/brand.py` and `layers/common/tests/test_brand.py`.
  `test_brand.py` is the model for a standard-library-only layer module and its tests:
  its `sys.path` setup, the AST import test, and the subprocess import test.
- `functions/ceramics/kiln_dropoff_recent_entries_viewer/lambda_function.py`, lines
  31–64: `PAGE_TEMPLATE`, `_STYLE_BLOCK`, `_style_hash` and `RESPONSE_HEADERS`.
- `functions/classes/class_photo_upload_page/lambda_function.py`: `ERROR_HEADERS` (line
  48), `response_headers` (line 98), and `secrets.token_urlsafe(16)` in
  `lambda_handler`.
- The CSP tests these pins sit next to:
  - kiln: `test_kiln_dropoff_viewer_lambda_function.py`, lines 360–590: `_sha256_source`,
    `_directives`, `EXPECTED_CSP`, `EXPECTED_HEADERS`,
    `test_csp_style_hash_matches_served_style`, `test_csp_is_no_looser_than_before`,
    `test_style_hash_rejects_zero_or_two_style_blocks`.
  - photo: `test_lambda_function.py`: `_event`, `_call`, `_csp`, `test_csp_header`,
    `test_nonce_changes_per_request`, `test_invalid_auth_domain_returns_500`.
- `tests/page_style.py`'s module docstring, for the `*_problems` contract to copy, and
  `tests/test_page_style.py`, `test_page_style_is_outside_every_packaged_folder`.
- `tests/test_shared_brand.py`, `_sha256_source` and its one use (line 162).

## Goal

- `common.csp` exists in the common layer and can build each of today's three policies
  byte for byte. Nothing uses it yet.
- `tests/page_csp.py` can check any page's served header against its served body, for a
  hash policy or a nonce policy, and has its own tests.
- The photo page's two header strings are pinned as literals. Two requests are shown to
  get different nonces, each equal on the header, the `<style>` and the `<script>`. All
  of this passes against the unchanged functions.
- The kiln test file and `tests/test_shared_brand.py` use the shared `sha256_source`
  instead of private copies, and no assertion changes.

No function code changes in this phase.

## Files to create

| File | What |
| --- | --- |
| `layers/common/python/common/csp.py` | The helper (below). |
| `layers/common/tests/test_csp.py` | Its tests, pytest and the standard library only, set up like `test_brand.py` (below). |
| `tests/page_csp.py` | Shared CSP checks for page tests. Test code only, never packaged (below). |
| `tests/test_page_csp.py` | `page_csp`'s own tests. Phase 2 adds the per-page registry here. |

## Files to modify

| File | Change |
| --- | --- |
| `functions/classes/class_photo_upload_page/tests/test_lambda_function.py` | `from tests import page_csp` (next to the existing `from tests import capture_page_pins, page_style`). Three new tests (below). |
| `functions/ceramics/kiln_dropoff_recent_entries_viewer/tests/test_kiln_dropoff_viewer_lambda_function.py` | Remove `_sha256_source` and `_directives`, and the `base64` and `hashlib` imports they used. Each call becomes `page_csp.sha256_source(...)` or `page_csp.directives(...)`, imported as `from tests import capture_page_pins, page_csp, page_style`. No assertion or test name changes. |
| `tests/test_shared_brand.py` | Remove `_sha256_source` and the `base64`/`hashlib` imports. Line 162 calls `page_csp.sha256_source`. |
| `tests/test_page_style.py` | `test_page_style_is_outside_every_packaged_folder` checks `tests/page_csp.py` as well as `tests/page_style.py`: loop over both modules wherever it checks `module`. Keep the name, and add "and page_csp" to the docstring. |

No template, `configs/`, deploy-role or docs change in this phase. Both functions'
`lambda_function.py` and `page.html` don't change.

## Implementation details

### layer: `layers/common/python/common/csp.py`

The module docstring says:

- what every policy shares: `default-src 'none'` first, and `base-uri 'none';
  form-action 'none'; frame-ancestors 'none'` last;
- which shape each kind of page uses. The kiln page uses `hash_policy`, because it has no
  script and one fixed `<style>`. The photo page uses `nonce_policy` with `new_nonce()` on
  every request, because it has a script. A plain error page uses `strict_policy()`.
- that the module is standard library only, like `brand.py`, and that
  `layers/common/tests/test_csp.py` checks this.

```python
import base64
import hashlib
import re
import secrets
from collections.abc import Iterable

# The one inline <style> block of a hash-policy page: a bare <style> tag, no attributes.
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
# Every policy starts and ends with these; a caller can't set them.
FIRST: tuple[str, str] = ("default-src", "'none'")
LAST: tuple[tuple[str, str], ...] = (("base-uri", "'none'"), ("form-action", "'none'"), ("frame-ancestors", "'none'"))
_FIXED = frozenset({FIRST[0], *(name for name, _ in LAST)})
_DIRECTIVE_NAME = re.compile(r"[a-z]+(?:-[a-z]+)*")
# A ';' would end the directive, a ',' would start a second policy, CR or LF a new header.
_UNSAFE_IN_SOURCES = re.compile(r"[;,\r\n]")
# base64 or base64url, as secrets.token_urlsafe makes it.
_NONCE = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")


def sha256_source(text: str) -> str:
    """The CSP hash source for this exact text: 'sha256-<base64 digest>'. Nothing is stripped."""


def style_hash_source(page: str) -> str:
    """The hash source for the page's one inline <style> block.

    Raises ValueError when the page has no bare <style> block or more than one.
    """


def strict_policy(allow: Iterable[tuple[str, str]] = ()) -> str:
    """default-src 'none', then each (directive, sources) in order, then base-uri,
    form-action and frame-ancestors 'none', joined with "; ".

    Raises ValueError for one of the four fixed directives, a repeated directive, a name
    that isn't lower-case words joined by '-', or sources that are blank or contain ';',
    ',', CR or LF.
    """


def hash_policy(page: str) -> str:
    """The policy for a page with no script and one inline <style>, allowed by its hash."""
    return strict_policy([("style-src", style_hash_source(page))])


def new_nonce() -> str:
    """A fresh nonce for one response: 16 random bytes, base64url (22 characters)."""
    return secrets.token_urlsafe(16)


def nonce_policy(nonce: str, allow: Iterable[tuple[str, str]] = ()) -> str:
    """script-src and style-src allowed by this nonce, then `allow`, inside strict_policy.

    Raises ValueError when the nonce isn't base64 or base64url.
    """
```

- `style_hash_source`'s error text is the same as kiln's today, without the file name:
  `"page must have exactly one <style> block, found {n}"`. It is never shown to a
  visitor, because it raises at import (kiln) and API Gateway answers 502.
- `strict_policy`'s `ValueError` messages may name the directive, never the sources.
- No logging: the module has no logger, like `brand.py`.
- The output for each of today's three calls (pinned in `test_csp.py`):
  - `strict_policy()` →
    `default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
  - `hash_policy(page)` →
    `default-src 'none'; style-src 'sha256-…'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
  - `nonce_policy("n0nce", [("img-src", "blob:"), ("connect-src", "'self' https://asmbly-staff.auth.us-east-2.amazoncognito.com")])`
    → `default-src 'none'; script-src 'nonce-n0nce'; style-src 'nonce-n0nce'; img-src blob:; connect-src 'self' https://asmbly-staff.auth.us-east-2.amazoncognito.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`

These three are byte-equal to what the functions send today (captured on 07b9b79 with
`PYTHONPATH=.:layers/common/python`). The kiln header today is
`default-src 'none'; style-src 'sha256-yq0AVdJG/UwixzICb54qAjwd5qThPETwyd7OZjKOSM8='; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.

### test helpers: `tests/page_csp.py`

The module docstring follows `page_style.py`'s:

- "CSP checks shared by the tests of the repository's HTML pages."
- Each `*_problems` check returns a list of messages, and an empty list is a pass.
- The checks compute hashes themselves and don't import `common.csp`, so a bug in the
  helper can't hide in its own check.
- Test code only: nothing outside the tests imports it, and no template packages it
  (`tests/test_page_style.py` checks this).

```python
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
_TAG = re.compile(r"<(script|style)\b([^>]*)>", re.I)
_NONCE_ATTRIBUTE = re.compile(r'\bnonce="([^"]*)"')
_DATA_SCRIPT = re.compile(r'\btype="application/json"')

def sha256_source(text: str) -> str: ...
def directives(policy: str) -> dict[str, str]: ...
def nonce(policy: str) -> str: ...
def style_hash_problems(policy: str, body: str, style_block: re.Pattern[str] = STYLE_BLOCK) -> list[str]: ...
def nonce_problems(policy: str, body: str) -> list[str]: ...
```

- `sha256_source`: `hashlib` and `base64`, as the kiln test's private copy does today.
- `directives`: as the kiln test's `_directives`. It splits on `;`, splits each part at
  its first space, and returns `{name: sources}` (`""` for a directive with no sources).
  It raises `ValueError` on a repeated directive. Today it asserts; a helper raises,
  which the kiln tests see the same way.
- `nonce`: the `N` in `script-src 'nonce-N'`. Raises `ValueError` when `script-src`
  isn't exactly one nonce source.
- `style_hash_problems` reports, each as one message:
  - `default-src` isn't `'none'`;
  - `'unsafe-inline'` anywhere in the policy;
  - a `script-src`;
  - the body has a number of `style_block` matches other than one;
  - `style-src` isn't exactly `sha256_source(<that block's text>)`.
- `nonce_problems` reports:
  - `default-src` isn't `'none'`;
  - `'unsafe-inline'`;
  - `script-src` or `style-src` isn't exactly `'nonce-N'` with the same `N`;
  - `__CSP_NONCE__` is left in the body;
  - the body has no `<style` tag or no executable `<script` tag;
  - any `<style …>` tag, or `<script …>` tag other than a `type="application/json"` data
    block, has no `nonce="N"` or a different nonce.

  The photo page's config block is such a data block. The browser never runs it, so it
  needs no nonce, and it has none today.

Type hints on every function. No logging.

### layer tests: `layers/common/tests/test_csp.py`

Set up like `test_brand.py`: `LAYER_PYTHON` on `sys.path`, then `from common import csp`.
Each test computes its expected hash with `hashlib` and `base64` itself.

### lambda (tests): the photo page's new tests

All three go in `test_lambda_function.py`, near `test_csp_header`:

```python
PINNED_CSP = (
    "default-src 'none'; script-src 'nonce-n0nce'; style-src 'nonce-n0nce'; img-src blob:; "
    f"connect-src 'self' https://{AUTH_DOMAIN}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
PINNED_ERROR_CSP = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
```

A comment above them says these are the strings sent on `stage` 07b9b79, before story
#139 moved the CSP into `common/csp.py`, and must stay byte-identical.

`test_csp_header` and `test_nonce_changes_per_request` are not edited.

## Tests

`layers/common/tests/test_csp.py`:

| Test | Proves |
| --- | --- |
| `test_strict_policy_alone_is_the_error_page_policy` | `strict_policy()` equals the 4-directive literal. |
| `test_hash_policy_is_the_kiln_shape` | For `"<html><style>\n  a { }\n</style></html>"`, `hash_policy` equals the 5-directive literal, with the hash computed in the test. |
| `test_nonce_policy_is_the_photo_shape` | The `nonce_policy("n0nce", [img-src, connect-src])` call above equals the 8-directive literal. |
| `test_style_hash_source_needs_exactly_one_style_block` | Raises `ValueError` for no `<style>`, for two, and for a page whose only style is `<style nonce="x">`. That last case means a nonce page passed to `hash_policy` fails loudly. |
| `test_style_hash_covers_the_text_exactly` | `"<style>a{}</style>"` and `"<style> a{}</style>"` give different sources, so nothing is stripped. |
| `test_strict_policy_keeps_the_order_given` | `[("style-src", "x"), ("img-src", "y")]` and the reverse give the directives in the order given. |
| `test_strict_policy_refuses_fixed_repeated_or_bad_names` | Parametrized, each raises `ValueError`: `default-src`, `base-uri`, `form-action`, `frame-ancestors`, `Style-Src`, `""`, `"img src"`, and `img-src` twice. |
| `test_strict_policy_refuses_sources_that_could_break_the_header` | Parametrized, each raises `ValueError`: `""`, `"  "`, `"'self'; script-src *"`, `"a, b"`, `"a\r\nX-Injected: 1"`, `"a\nb"`. |
| `test_nonce_policy_refuses_a_nonce_that_is_not_base64` | Parametrized, each raises `ValueError`: `""`, `"a b"`, `"abc'"`, `"a;b"`, `"a\nb"`. |
| `test_new_nonce_is_fresh_and_url_safe` | Two calls differ, and each fullmatches `[A-Za-z0-9_-]{22}`. |
| `test_csp_imports_only_the_standard_library` | AST walk, as in `test_brand.py`: each import's top name is in `sys.stdlib_module_names`, with no relative import. |
| `test_importing_csp_loads_no_third_party_module` | A subprocess (`sys.executable -I -c`) with only `LAYER_PYTHON` on the path imports `common.csp` and prints `False` for `boto3`, `botocore` and `requests` in `sys.modules`. |

`tests/test_page_csp.py` (`page_csp`'s own tests):

| Test | Proves |
| --- | --- |
| `test_sha256_source_matches_a_known_digest` | `sha256_source("") == "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='"`, the published SHA-256 of the empty string. |
| `test_directives_reads_each_directive_once` | It parses the 8-directive photo literal into 8 entries, and `img-src` is `blob:`. A repeated `style-src` raises `ValueError`. |
| `test_nonce_reads_the_script_nonce` | `nonce` on the photo literal returns `n0nce`. It raises on a policy with no `script-src`. |
| `test_style_hash_problems_passes_a_matching_page` | A body with one `<style>` and its correct hash gives `[]`. |
| `test_style_hash_problems_reports_each_fault` | Parametrized, each gives exactly one message: a wrong hash, two `<style>` blocks, none, `'unsafe-inline'` added, a `script-src` added, `default-src *`. |
| `test_nonce_problems_passes_a_matching_page` | `<style nonce="N">`, `<script type="application/json" id="c">{}</script>` (no nonce) and `<script nonce="N">` under a matching policy give `[]`. |
| `test_nonce_problems_reports_each_fault` | Parametrized, each gives at least one message naming the fault: a `<style>` with no nonce, a `<script>` with another nonce, `style-src` with a different nonce from `script-src`, a `__CSP_NONCE__` left in, `'unsafe-inline'` added, no `<script nonce>`. |

`functions/classes/class_photo_upload_page/tests/test_lambda_function.py`:

| Test | Proves |
| --- | --- |
| `test_csp_header_is_byte_for_byte_unchanged` | `lambda_function.response_headers(AUTH_DOMAIN, "n0nce")["Content-Security-Policy"] == PINNED_CSP`. Story #139 criterion 2: same directives, same order, same bytes. |
| `test_error_page_csp_is_unchanged` | The `Content-Security-Policy` of a 400 (`_call(_event(path="/other"))`) and of a 500 (`STAFF_AUTH_DOMAIN` missing) both equal `PINNED_ERROR_CSP`. |
| `test_two_requests_get_different_nonces_on_header_style_and_script` | Two `_call(_event())` responses, A and B. For each, `page_csp.nonce_problems(policy, body) == []`, and `f'<style nonce="{n}">'` and `f'<script nonce="{n}">'` are in the body, where `n = page_csp.nonce(policy)`. A's nonce differs from B's, and A's nonce isn't in B's body. Story #139 criterion 4. |

Changed, with no change to what they assert: the kiln CSP tests (they now call
`page_csp`), `tests/test_shared_brand.py`'s `test_changing_a_shared_token_changes_both_pages`
(the same), and `test_page_style_is_outside_every_packaged_folder` (it now checks one
more file).

## Acceptance criteria

Each traced to story #139:

1. `common.csp.strict_policy()`, `hash_policy(kiln.PAGE_TEMPLATE)` and the photo
   `nonce_policy` call equal what the functions send today, byte for byte:
   `test_*_shape` and `test_strict_policy_alone_*` in `test_csp.py`, plus the Verification
   one-liner. This prepares criterion 1.
2. **(c2)** The photo page's 8-directive header and its error pages' 4-directive header
   are pinned as literals (`test_csp_header_is_byte_for_byte_unchanged`,
   `test_error_page_csp_is_unchanged`). The kiln page's 5-directive header is already
   pinned (`EXPECTED_HEADERS`, `test_lambda_handler_sets_csp_header`). All pass against
   the unchanged functions.
3. **(c3, part)** `tests/page_csp.style_hash_problems` checks any page's hash against its
   served `<style>`, with its own tests. Phase 2 runs it for every registered hash page.
4. **(c4)** Two requests to the photo page get different nonces, and each response's
   header nonce equals the one on its `<style>` and its `<script>`:
   `test_two_requests_get_different_nonces_on_header_style_and_script`.
5. **(c6)** No page body changes: #138's pins (`test_served_tokens_are_the_stage_tokens`,
   `test_served_rules_are_the_stage_rules` on both pages, `test_logo_matches_both_pages`)
   pass unchanged. `git diff origin/stage -- functions/*/*/page.html functions/*/*/lambda_function.py`
   is empty.
6. `common.csp` imports only the standard library (`test_csp_imports_only_the_standard_library`,
   `test_importing_csp_loads_no_third_party_module`). `tests/page_csp.py` is in no
   packaged folder.

## Verification

```bash
.venv/bin/python -m pytest layers/common/tests/test_csp.py tests/test_page_csp.py \
  functions/classes/class_photo_upload_page functions/ceramics/kiln_dropoff_recent_entries_viewer \
  tests/test_shared_brand.py tests/test_page_style.py
.venv/bin/python -m pytest                                          # all pass; 1871 + the new tests
sam build                                                           # a layer change
```

- `cfn-lint` and `sam validate` aren't needed, because no template changes. Run them
  anyway if the integration gate asks.
- Check that the test IDs before and after (`pytest --collect-only -q`) differ only by
  the added tests.
- Check that the helper reproduces today's headers. Run this from the repository root;
  it prints `True True True`:

```bash
PYTHONPATH=.:layers/common/python .venv/bin/python -c "
from common import csp
from functions.ceramics.kiln_dropoff_recent_entries_viewer import lambda_function as k
from functions.classes.class_photo_upload_page import lambda_function as p
a = 'asmbly-staff.auth.us-east-2.amazoncognito.com'
print(csp.hash_policy(k.PAGE_TEMPLATE) == k.RESPONSE_HEADERS['Content-Security-Policy'],
      csp.nonce_policy('n0nce', [('img-src', 'blob:'), ('connect-src', \"'self' https://\" + a)]) == p.response_headers(a, 'n0nce')['Content-Security-Policy'],
      csp.strict_policy() == p.ERROR_HEADERS['Content-Security-Policy'])"
```

There is nothing to see on stage after this phase alone: no page changes. Phase 2 has the
stage checks.

## Admin actions

None. There is no new named resource, and `csp.py` ships in the existing `CommonLayer`.

## Hand-off

To be filled in when the phase is done. Phase 2 relies on:

- `common.csp` with `sha256_source`, `style_hash_source`, `strict_policy`,
  `hash_policy`, `new_nonce` and `nonce_policy`, with the signatures above, and the three
  calls that reproduce today's headers;
- `tests/page_csp.py` with `sha256_source`, `directives`, `nonce`, `style_hash_problems`
  and `nonce_problems`, and `tests/test_page_csp.py` to add the registry to;
- the photo pins `PINNED_CSP` and `PINNED_ERROR_CSP` and their tests, passing;
- the suite count after this phase.
