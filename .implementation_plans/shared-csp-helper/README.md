---
plan: shared-csp-helper
epic: 136
---

# Shared CSP helper: implementation plan

**Created:** 2026-10-17

## Overview

The repository's two HTML pages each build their Content-Security-Policy header by hand:

- The kiln drop-off viewer (`functions/ceramics/kiln_dropoff_recent_entries_viewer/`)
  hashes its one `<style>` block in a private `_style_hash` and writes a 5-directive
  policy as an f-string.
- The class photo upload page (`functions/classes/class_photo_upload_page/`) makes a nonce
  with `secrets.token_urlsafe(16)` and writes an 8-directive policy as an f-string. It
  also writes a 4-directive policy for its 400 and 500 pages as a literal.

A third page would copy one of them. The tests that check the hash against the served
`<style>` live only in the kiln test file.

After this plan:

- One module in the common layer, `layers/common/python/common/csp.py`, builds every
  policy. Like `brand.py`, it uses only the Python standard library.
  - `hash_policy(page)` builds the kiln page's policy.
  - `nonce_policy(nonce, allow)` builds the photo page's policy, and `new_nonce()` makes
    its nonce.
  - `strict_policy(allow)` builds the base that both use, and the photo error pages' policy.
- Neither function writes a CSP string. Both send the same header, byte for byte, as on
  `stage` 07b9b79.
- A shared test module, `tests/page_csp.py`, checks any page's served header against its
  served body: the hash against the `<style>`, or the nonce against every `<style>` and
  executable `<script>`.
- `tests/test_page_csp.py` keeps a registry of the public pages. It runs those checks for
  every registered page, and it fails when a function serves HTML without being
  registered.
- `docs/CONTRIBUTING.md` gets an "Adding a Public Page" section.

Visitors see no change. No page body changes, and #138's token and rule pins pass
unchanged.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #139 | A new page can reuse the CSP helper and the shared pieces | 1, 2 |

Both phases go into one pull request. It lands phase 2, the last phase in #139's row,
so it says `Closes #139`. #139 is the last open story of epic #136 (#137 and #138 are
closed), so the same pull request also says `Closes #136`.

The epic's own criteria, from its "Decided" section, apply here too:

- Visitors see no change. #138's pins and the byte-identical header pins (phase 1) cover
  this.
- The shared runtime pieces go in the existing common layer. That means no new layer, no
  deploy-role change and no admin redeploy.
- The photo page keeps its per-request nonce CSP and the kiln page keeps its hash CSP.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| 1 | [CSP helper, shared CSP checks and the header pins](phase-1-csp-helper-and-pins.md) | layer, lambda | M | [x] Complete |
| 2 | [Both pages use the helper; every page is checked; docs](phase-2-pages-use-csp-helper.md) | lambda, layer, docs | M | [ ] Pending |

## Dependencies

- **Satisfied (merged on `stage` 07b9b79):**
  - #137's `tests/page_style.py` (PR #147) and #148's parser tightening (PR #149).
  - #138's `common/brand.py`, its page markers, the per-page pins
    `tests/fixtures/pinned_tokens.json` and `pinned_rules.css`, and
    `tests/capture_page_pins.py` (PR #150).
  - Both functions already have `CommonLayer` (12 functions use it).
- No secret, SSM parameter, third-party setup or other plan is needed.
- Phase 2 depends on phase 1. It needs `common.csp`, `tests/page_csp.py`, and the header
  pins that show the switch changed nothing.

## Parallelism

There are two phases in sequence (phase 2 `depends_on: [1]`), so no pair can run in
parallel. They also share both page test files and `tests/test_page_csp.py`.

## Admin actions

None.

- There is no new named resource (function, layer, log group, SSM parameter, table or
  rule), so `template-cicd.yaml` doesn't change and no admin redeploy is needed.
- `csp.py` ships inside the existing `CommonLayer` (`ContentUri: layers/common/`).
  Publishing a new `common-layer-<stage>` version and updating the functions that use it
  needs only permissions the deploy role already uses on every layer change:
  - `lambda:PublishLayerVersion` and `lambda:GetLayerVersion` on `common-layer-<stage>`;
  - `lambda:UpdateFunctionConfiguration` on each function.
- No template, secret, webhook, Slack app setting or schedule changes.

**Risk for the pull request** (not an admin action): `layers/common/` changes, so the
stage deploy publishes a new `common-layer-stage` version and updates all 12 functions
that use `CommonLayer` in one deploy. Prod gets the same when `/promote` runs. Only the
two pages import `common.csp`. The other 10 functions get the new file but never load it.

## Related work

- **#138 / PR #150 (merged):** `common/brand.py`, the markers and the pins. Phase 2's
  docs describe `fill_brand` together with the CSP helper, and the pins must pass
  unchanged. Its plan is `.implementation_plans/shared-brand-tokens/`.
- **#137 / PR #147 and #148 / PR #149 (merged):** `tests/page_style.py`. The new
  `tests/page_csp.py` follows its shape: `*_problems` functions that return `[]` on a
  pass, test code only, never packaged.
- **#79 (open):** caller checks on the public routes. These two routes are unchanged here,
  as the epic's Out of scope says. The new docs section says a new page's route must
  check its caller.
- **PR #68 (open, `epowell/lint-templates`):** adds a lint step. It touches no file here.
- Known and unchanged: `CommonLayer` packages `layers/common/tests/`, so the new
  `test_csp.py` ships in the layer, as `test_brand.py` does (the shared-style-checks and
  shared-brand-tokens briefings flagged this follow-up).

## Out of scope

- Any change to what either page sends:
  - the directive lists and their order;
  - the hash or nonce scheme;
  - adding `Strict-Transport-Security`, `Referrer-Policy` to the kiln page, or any
    other header.
- Moving the other response headers (`Content-Type`, `X-Content-Type-Options`,
  `Cache-Control`, `Referrer-Policy`) into the helper. Story #139 asks for the CSP
  only. The headers differ between the pages today (the kiln page has no
  `Referrer-Policy`), and sharing them would change one page's headers.
- Making the two pages look alike, and the photo page's script, its Node harness and its
  API (the epic's Out of scope).
- Caller checks on these routes (#79).
- Editing `CLAUDE.md`. The new docs section points to its rules instead (Decision 10).
- Keeping `tests/` folders out of the Lambda and layer packages.

## Security

- **The policy doesn't get looser.** Each page's header string is pinned byte for byte in
  phase 1, before the switch, and phase 2 must keep those pins passing:
  - kiln: the existing `EXPECTED_HEADERS`, whose hash the test computes itself;
  - photo: a new literal pin for a fixed nonce, and one for the error pages' policy.
- **The helper can't be made to write a malformed or injected header.** `strict_policy` always
  starts with `default-src 'none'` and ends with `base-uri 'none'; form-action 'none';
  frame-ancestors 'none'`. A caller can't override those four directives, can't repeat a
  directive, and can't pass a source list that is empty or contains `;`, `,`, CR or LF.
  `nonce_policy` accepts only a base64 or base64url nonce. Each of these raises
  `ValueError`, and tests check every case.
  - The photo function already checks `STAFF_AUTH_DOMAIN` against `HOST_PATTERN` before
    it builds the policy, so no new error path is reachable from a request. (A value with
    a trailing newline still passes `HOST_PATTERN`; see phase 1's Hand-off.)
  - The helper checks syntax, not looseness: an `allow` source such as `'unsafe-inline'`
    or `*` is accepted. What keeps each page's policy strict is its byte pin and the
    `tests/page_csp.py` checks, which phase 2 runs for every registered page.
- **The nonce source is unchanged:** `secrets.token_urlsafe(16)`, now behind
  `csp.new_nonce()`. A new nonce for every request is tested at the header, on the
  `<style>` and on the `<script>`.
- **The test checks are independent of the code they check.** `tests/page_csp.py`
  computes the SHA-256 itself and doesn't import `common.csp`, so a bug in the helper
  can't hide in its own test.
- No route, authorizer, IAM statement, secret, log line or response body changes.

## Decisions

Made without asking, inside `/offshore`:

1. **Scope is story #139 only, with no new issues.** Its six criteria are the
   acceptance criteria. The epic's "Decided" items are treated as criteria too (see
   Stories). Alternative: run `/plan-product` first. Rejected, because the story already
   has testable criteria.
2. **Two phases: helper and pins first, then the switch and the docs.** Alternatives:
   - One L phase. Rejected, because a single commit can't show "before" and "after" for
     the header.
   - Three phases with docs alone. Rejected as over-phased.

   Phase 1 adds the helper and the shared checks, and pins today's header strings while
   both functions still build them by hand. Phase 2 switches both functions, and the pins
   must still pass. This is the same pins-then-switch shape as #138.
3. **The helper is `layers/common/python/common/csp.py`, standard library only, like
   `brand.py`.** Both functions already have `CommonLayer` (epic decision: no new layer).
   It imports `base64`, `hashlib`, `re`, `secrets` and `collections.abc`, and an AST test
   checks that every import is in `sys.stdlib_module_names`. Alternatives:
   - Add it to `brand.py`. Rejected: that mixes the look with security headers.
   - A function-local copy. Rejected: that is what the story removes.
4. **The API is one base and two shapes.**
   - `strict_policy(allow=())` writes `default-src 'none'`, then the `(directive, sources)`
     pairs in the order given, then `base-uri 'none'; form-action 'none';
     frame-ancestors 'none'`, joined with `"; "`.
   - `hash_policy(page)` is `strict_policy([("style-src", style_hash_source(page))])`.
   - `nonce_policy(nonce, allow=())` is `strict_policy([("script-src", "'nonce-N'"),
     ("style-src", "'nonce-N'"), *allow])`.

   All three of today's strings have that shape, so each comes out byte-identical:
   kiln 5 directives, photo 8, photo error 4. Alternative: a dict of directives. Rejected,
   because the call would have to spell out the fixed directives every time, and their
   order must stay as it is.
5. **The photo error pages' policy uses the helper too** (`csp.strict_policy()`). The
   story says "neither function builds its CSP string by hand", and that literal is a
   CSP string. Its value doesn't change, and a new literal pin checks it.
6. **`csp.new_nonce()` wraps `secrets.token_urlsafe(16)`,** so a new page gets the same
   128-bit nonce without choosing a length. The photo function drops `import secrets`.
   No test patches `secrets` today (checked), so nothing breaks.
7. **The kiln page's `_style_hash` goes, replaced by `csp.style_hash_source`.** The
   private name existed only to build the header. Its test,
   `test_style_hash_rejects_zero_or_two_style_blocks`, keeps its name and its three
   assertions, and phase 2 retargets it to `csp.style_hash_source`. The layer's
   `test_csp.py` covers the same cases on its own. Alternative: keep `_style_hash` as an
   alias. Rejected, because the code would keep a name that does nothing.
   `photo.response_headers(auth_domain, nonce)` stays, because the other headers are
   built there and the byte pin calls it.
8. **The shared test helpers are a new `tests/page_csp.py`, not part of
   `tests/page_style.py`.** `page_style` reads stylesheets; these read headers. It has
   the same contract: `*_problems` functions return `[]` on a pass, it is test code only,
   and it is never packaged. `tests/test_page_style.py`'s packaging test is extended to
   cover the new module rather than copied.
   - Its functions are `sha256_source`, `directives`, `nonce`, `style_hash_problems` and
     `nonce_problems`.
   - The kiln test file's and `tests/test_shared_brand.py`'s private `_sha256_source`
     copies, and the kiln file's `_directives`, are replaced by calls to it. No
     assertion changes.
9. **"Every page that uses the hash-based policy" is enforced by a registry.**
   `tests/test_page_csp.py` has `PUBLIC_PAGES`, mapping each page to its policy kind
   (`"hash"` or `"nonce"`) and a function that returns sample served responses. Two
   tests run the shared checks over it:
   - `test_hash_pages_allow_only_their_served_style` for the hash pages;
   - `test_nonce_pages_put_a_fresh_nonce_on_style_and_script` for the nonce pages.

   `test_every_html_page_is_registered` fails if a function folder has a `page.html`, or
   a `lambda_function.py` that sends `text/html`, without an entry. It also checks that
   the page is in `capture_page_pins.PAGES`, so a new page can't skip its checks or its
   pins.
10. **The docs section is "Adding a Public Page" in `docs/CONTRIBUTING.md`,** right after
    "Adding a New Lambda Function", which it builds on, and it gets a Table of Contents
    entry. `CLAUDE.md` isn't edited (orchestrator instruction): the section links to
    `CLAUDE.md`'s rules for the caller check, the log group and the deploy-role names,
    and doesn't restate them. The pull request may propose adding `csp` to CLAUDE.md's
    "Shared helpers" map row, for the person to decide.
11. **Byte-identical, checked two ways:**
    - The literal pins (photo) and the existing `EXPECTED_HEADERS` (kiln) must pass
      unchanged in phase 2.
    - Phase 2's Verification renders each header on `origin/stage` and on the branch and
      compares the strings.

    #138's pins, `test_csp_header` and `test_nonce_changes_per_request` are not edited.
12. **Closing keywords:** the final pull request says `Closes #139` and `Closes #136`.
    The epic's other stories are already closed (`sub-issues-completed: 2/3`).
