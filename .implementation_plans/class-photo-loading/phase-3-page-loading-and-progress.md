---
phase_id: 3
title: Page busy state, progress, retry and timeout messages
epic: 114
implements: [117, 118]
depends_on: [1]
domain: [lambda, docs]
estimated_size: L
---

# Phase 3: Page busy state, progress, retry and timeout messages

> **Status:** [x] Complete — 2026-10-17 on branch feature/class-photo-loading

## Required reading

- This plan's README (Decisions 9, 11–17, 21; Security, "The page"). Decision 21 (owner,
  2026-10-16) adds the **Refresh class list** button below.
- #117 (all criteria) and #118 criteria 4, 5 and 6.
- `.implementation_plans/photo-upload-branding/README.md`, "Design rule" and Decisions
  10–13: every value is a token on `:root`, defined once, used by `var()`; no literal
  outside `:root`. The owner's rule carries over: **no token-test allowlist may grow**
  (`ALLOWED_VALUE_WORDS`, `GRID_AREAS`, `SVG_ATTRIBUTES`, `RESERVED_TOKENS`,
  `SHARED_LITERALS`, `TOKEN_VALUE`, `FONT_STACK`, `GLYPH_TOKEN` stay as they are).
- `functions/classes/class_photo_upload_page/page.html`: the markup of `#app` (lines
  294–316), `apiFetch()`, `loadClasses()`, `updateSubmit()`, `submit()`, `wire()`,
  `start()`, the `elements` id list and the `state` object.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: every test,
  especially `test_csp_header`, `test_page_messages_match_server_messages`,
  `test_page_uses_text_content_not_inner_html`, `test_page_has_one_inline_script_and_style`,
  `test_styles_use_tokens_only`, `test_every_token_is_used`, `test_tokens_are_defined_once`,
  `test_message_kinds_differ_beyond_colour`, `test_tap_targets_are_44px`,
  `test_disabled_controls_differ_beyond_colour`, `test_no_hidden_horizontal_overflow`
  (no `tabindex` anywhere), `test_served_page_is_small` (100 KB; the page is about 58 KB).
- `functions/classes/class_photo_upload_page/lambda_function.py`: the page config keys
  (`authDomain`, `clientId`, `pageUrl`, `dryRun`).
- Phase 1's hand-off (`refreshed_at`, `stale` and `refresh` in `/classes`;
  `GET /classes?refresh=1`) and phase 2's (the two GitHub messages; the page shows them
  as given).
- `functions/classes/class_photo_upload_api/tests/jpeg_builder.py` (`make_jpeg`), reused
  for a valid photo in the script tests.

## Prep amendments (2026-10-16, `/prep` inside `/offshore`)

These override the text below where they disagree.

1. **Focus fixup confirmed** (headless Chrome 155: a focused `<button>` that becomes
   `disabled` loses focus to `<body>` at the next rendering update; re-enabling doesn't
   restore it). So **Try again**, **Refresh class list** and, while a submission runs,
   **Submit** take `aria-disabled="true"` instead of `disabled` while busy, and their
   handlers ignore clicks by state (`state.loadingClasses`, `state.submitting`). The
   disabled look covers them: the `button:disabled` rule's selector list gains
   `button[aria-disabled="true"]`, and `(hover: hover)` gains
   `button[aria-disabled="true"]:hover` with the disabled colours (and `color:
   var(--text)`, for `test_light_tints_carry_dark_text`). Submit keeps native `disabled`
   when there's no class or photo, and is also disabled while the class list loads or
   refreshes. Scenarios assert "unavailable" (`disabled` or `aria-disabled="true"`), that
   focus stays, and that a click sends nothing.
2. **No `.busy[hidden]` rule**: `page.html` already has `[hidden] { display: none
   !important; }`. `test_busy_indicator_uses_tokens` checks that global rule instead.
3. **One place decides what can be used**: `updateSubmit()` becomes `updateControls()`,
   which sets the select, the progress bar, `aria-busy`, both class buttons, the photo
   input and Submit from `state` (`classesLoaded`, `loadingClasses`, `submitting`). The
   select stays disabled until a list has loaded (a failed first load leaves it disabled).
   Focus moves to the select before **Try again** is hidden.
4. **Submit timing** (audit HIGH): the 35 s limit counts from the moment the photo has
   been sent (`upload.onload`), not from `send()`; while uploading, it restarts on each
   `upload.onprogress`, so only a stalled upload is given up. No `xhr.timeout`; the page
   calls `xhr.abort()`. A failure **before** the photo was sent (offline, stalled upload)
   is `PageError(NETWORK_MESSAGE)`: the API never ran. After it was sent: `onerror`,
   abort, 5xx without `error`, or an OK answer without JSON → `UnconfirmedError`.
   `submit()` checks `UnconfirmedError` before `PageError`. `UnconfirmedError` carries the
   caller's fallback message, so `/classes` still shows `NEON_ERROR`. New scenarios:
   `submit_failure_before_sending_is_network_error` (offline, and a stalled upload) and
   `submit_slow_upload_keeps_waiting` (progress every 10 s for 60 s, then an answer).
5. **A failed refresh never empties the list** (audit MED): with `refresh: "failed"` and
   no classes (Neon empty, nothing cached), the shown options and time stay; with a stale
   copy, the copy is listed and the stale sentence shows.
6. **Names**: `apiFetch` → `apiGet(path, fallbackMessage)`, `apiUpload` →
   `apiPost(path, json, fallbackMessage, onSent)`, sharing `readAnswer` and a
   `tokenOrSignIn()` helper. `STALE_HINT_TIME_OPTIONS` → `CLASS_LIST_TIME_OPTIONS` (used
   for every list time).
7. **Elapsed seconds** come from `Date.now() - start` and show "0 s" at once.
   `class-freshness` is emptied whenever it is hidden (`aria-describedby` reads hidden
   text).
8. **`class-status` is shared**: a load or refresh message replaces a chosen class's
   warning or problem text; Submit still follows the problem (accepted).
9. **Docs**: the API README already mentions "the page's refresh button" (line 41); its
   `?refresh=1` passages (lines 146-148) and `docs/README.md` lines 69-72 are renamed to
   **Refresh class list**. A throttled API call (reserved concurrency 3) answers 429 or a
   5xx without a message; the page README says what each shows.
10. **Size**: about 1,000 lines, most of them the harness and its scenarios. Not split:
    both stories share `readAnswer`, `updateControls` and the harness, so a split by story
    would rewrite them twice; phase 1 of this plan (2.4k lines) set the precedent.

## Goal

While the class list loads, the class field shows a native busy indicator and is marked
busy; "Loading classes…" is announced once and, after 5 s, "Still loading classes from
Neon…". A failed load shows the message and **Try again**, which reloads the list in
place. A loaded list says when it was read from Neon, and that it may be out of date when
the server marks it stale. A loaded list has a **Refresh class list** button that reads
the list from Neon again in place (owner Decision 21), with the same busy state, and says
when it was refreshed, when it was too soon to refresh again, or when Neon didn't answer.
While a submission runs, every input is disabled and the page
shows the step it is on (preparing, sending, waiting) with the seconds elapsed. A failure
keeps the class and photo for a one-click retry. An answer the page can't confirm says
plainly that a pull request may or may not have been opened (or, on a dry run, that
nothing was). The CSP, the design tokens, the 320px layout and every existing message stay.
The page's script gets automated tests through `node` (README Decision 12).

## Files to create

- `functions/classes/class_photo_upload_page/tests/page_script_harness.mjs`: runs the
  page's `<script>` in `node:vm` with a fake DOM, fake timers and scripted answers; one
  scenario per run.
- `functions/classes/class_photo_upload_page/tests/test_page_script.py`: pytest wrapper,
  one test per scenario.

## Files to modify

- `functions/classes/class_photo_upload_page/page.html`: markup, tokens and rules, script.
- `functions/classes/class_photo_upload_page/tests/test_lambda_function.py`: static tests
  for the new markup, messages and styles.
- `functions/classes/class_photo_upload_page/README.md`: "The Page", "How It Looks",
  "Testing".
- `docs/README.md` and `functions/classes/class_photo_upload_api/README.md`: name the
  **Refresh class list** button (see "docs").

## Implementation details

### lambda (the page)

**Markup** (inside `#app`; ids exact; no `style=`, no `tabindex`, no inline handlers):

```html
    <h2><label for="class-select">Class</label></h2>
    <select id="class-select" disabled aria-describedby="class-status class-freshness">
      <option value="">Choose a class…</option>
    </select>
    <progress id="class-progress" class="busy" aria-label="Loading classes" hidden></progress>
    <p id="class-status" class="message" role="status" aria-live="polite"></p>
    <button type="button" id="class-retry" hidden>Try again</button>
    <p id="class-freshness" class="message note" hidden></p>
    <button type="button" id="class-refresh" hidden>Refresh class list</button>
    ...
    <button type="button" id="submit" disabled>Submit</button>
    <progress id="submit-progress" class="busy" aria-label="Submitting" hidden></progress>
    <p id="submit-status" class="message" role="status" aria-live="polite"></p>
    <p id="submit-elapsed" class="message note" aria-hidden="true" hidden></p>
```

A `<progress>` without `value` is the browser's indeterminate bar (README Decision 13).
`class-status` and `submit-status` stay the page's live regions; `class-freshness` and
`submit-elapsed` are not live (Decision 14).

**Tokens** (add to `:root`, each used by a rule, none repeating an existing literal: they
refer to existing tokens):

```css
    --progress-height: var(--space-2);
    --progress-fill: var(--brand);
```

**Rules** (values are tokens, `0`, `100%` or words already in `ALLOWED_VALUE_WORDS`):

```css
  .busy { display: block; width: 100%; height: var(--progress-height); margin: var(--space-2) 0 0; accent-color: var(--progress-fill); }
  .message.note { font-size: var(--font-size-small); }
  .drop-zone input:disabled + label { background: var(--disabled-bg); color: var(--text); border-color: var(--control-border); border-style: dashed; cursor: not-allowed; }
```

`[hidden]` must still hide `.busy` (`display: block` would override the user-agent
`hidden` style): the global `[hidden] { display: none !important; }` already wins (prep amendment 2). The `**Try again**` button uses the
existing `button` rules (44px, focus ring, hover, disabled look). The `.drop-zone.dragging`
look is not applied while submitting. Check `test_every_token_is_used` and
`test_tokens_are_defined_once` pass with the two tokens; if `accent-color` changes the
contrast pairs `test_brand_colour_pairs_meet_contrast` checks, add the pair there (the
fill is Asmbly Purple on the browser's light track).

**Script: constants** (next to the existing messages; the existing messages are unchanged
and stay word for word):

```js
  const CLASS_SLOW_MS = 5000;          // "Still loading…" after this
  const REQUEST_TIMEOUT_MS = 35000;    // the page gives up (API Gateway answers at 29 s)
  const ELAPSED_TICK_MS = 1000;
  const STALE_HINT_TIME_OPTIONS = { hour: "2-digit", minute: "2-digit" };

  const LOADING_CLASSES_MESSAGE = "Loading classes…";
  const STILL_LOADING_CLASSES_MESSAGE = "Still loading classes from Neon…";
  const CLASS_LIST_TIME_MESSAGE = "Class list from Neon at {time}.";
  const STALE_LIST_MESSAGE = "Neon didn't answer the last refresh, so this list may be out of date.";
  const PREPARING_MESSAGE = "Preparing the photo…";
  const SENDING_MESSAGE = "Sending the photo…";
  const WAITING_MESSAGE = "Waiting for the server to check it and open the pull request…";
  const WAITING_DRY_RUN_MESSAGE = "Waiting for the server to check it and plan the pull request…";
  const ELAPSED_MESSAGE = "{seconds} s";
  const UNCONFIRMED_MESSAGE = "The server didn't confirm the result in time. A pull request may or may not have been opened on GitHub. Submitting the same class again is safe: it updates the same pull request instead of opening a second one.";
  const DRY_RUN_TIMEOUT_MESSAGE = "The server didn't answer in time. This is a dry run, so nothing was opened on GitHub. Try again.";
  const REFRESHING_CLASSES_MESSAGE = "Refreshing the class list from Neon…";
  const REFRESHED_MESSAGE = "Class list refreshed from Neon.";
  const REFRESH_TOO_SOON_MESSAGE = "The class list was refreshed less than a minute ago, so this is that list. Try again in a minute.";
  const REFRESH_FAILED_MESSAGE = "Neon didn't answer, so the class list wasn't refreshed. The list shown is the last one read.";
```

"Submitting…" is replaced by the three steps (README Decision 11); it is pinned by no test
(only comments in the CSS and in `test_message_kinds_differ_beyond_colour` mention it;
update both comments).

**Script: requests.** Split today's `apiFetch` so both transports share one reading of the
answer:

- `function readAnswer(status, text, fallbackMessage)`: today's logic after the `fetch`
  (401 → `reauthenticate()` and `null`; clears `STORAGE.reauthenticated` otherwise; JSON
  body when ok; 403 → `FORBIDDEN_ERROR`; a JSON `error` string → that message; 429 →
  `TOO_MANY_REQUESTS_MESSAGE`; else `fallbackMessage`). It throws `PageError` as today.
  Add `class UnconfirmedError extends PageError {}`: thrown instead of the fallback when
  `status >= 500` and the body has no `error` string (API Gateway's 502 and 504).
- `apiFetch(path, options, fallbackMessage)` (the class list): as today, plus an
  `AbortController` aborted after `REQUEST_TIMEOUT_MS`; an abort or network failure throws
  `PageError(NETWORK_MESSAGE)` as today; the body is read as text and passed to
  `readAnswer`.
- `apiUpload(path, jsonText, onSent)` (the submission): an `XMLHttpRequest` `POST` to
  `config.pageUrl + path` with `Authorization` and `Content-Type: application/json`,
  `timeout = REQUEST_TIMEOUT_MS`, `withCredentials = false`. `xhr.upload.onload` calls
  `onSent()`. `onload` → `readAnswer(xhr.status, xhr.responseText, GENERIC_ERROR)`.
  `onerror`, `ontimeout` and `onabort` → `UnconfirmedError` (the request may have reached
  the server). No token → `reauthenticate()` and `null`, as `apiFetch`. Same origin, so
  `connect-src 'self'` covers it and the CSP doesn't change.

**Script: loading the class list** (`loadClasses()`):

1. Busy on: `select.disabled = true`, `select.setAttribute("aria-busy", "true")`,
   `class-progress` shown, `class-freshness` hidden, `class-retry` shown only if it was
   already showing (a retry) and then `disabled = true`; `setMessage(class-status,
   LOADING_CLASSES_MESSAGE)`.
2. Start a timer: after `CLASS_SLOW_MS`, if still loading, `setMessage(class-status,
   STILL_LOADING_CLASSES_MESSAGE)` (a live-region change, announced once).
3. On failure: clear the timer, busy off (`aria-busy` removed, progress hidden), show the
   error message (`error` kind) as today, show `class-retry` enabled. Focus stays where it
   is (on **Try again** after a retry, README Decision 17).
4. On success: clear the timer, busy off, fill the options as today (a retry first removes
   the options added by an earlier attempt, keeping the placeholder, and clears
   `state.classes`), `select.disabled = false`, `class-status` cleared, `class-retry`
   hidden; if focus was on `class-retry`, move it to the select. `class-freshness` shows
   `CLASS_LIST_TIME_MESSAGE` with `new Date(body.refreshed_at).toLocaleTimeString([],
   STALE_HINT_TIME_OPTIONS)` when `refreshed_at` parses, and adds `" " +
   STALE_LIST_MESSAGE` when `body.stale === true`; hidden when `refreshed_at` is missing or
   doesn't parse.
5. A second `loadClasses()` while one is running does nothing (`state.loadingClasses`).

`wire()` adds `class-retry` → `loadClasses` and `class-refresh` → `refreshClasses`.

**Script: refreshing the class list** (`refreshClasses()`, owner Decision 21):

1. Shown (`class-refresh.hidden = false`) only after a list has loaded; hidden while the
   first load runs or after it failed (**Try again** covers that). Its accessible name is
   its visible text, "Refresh class list" (no `aria-label`).
2. Ignored while a load, a refresh or a submission runs (`state.loadingClasses`,
   `state.submitting`); `setBusy(true)` disables it during a submission.
3. Busy on, as a load: the select disabled with `aria-busy="true"`, `class-progress` shown,
   the button disabled; `setMessage(class-status, REFRESHING_CLASSES_MESSAGE)`. Same
   `CLASS_SLOW_MS` "still loading" timer and `REQUEST_TIMEOUT_MS` abort.
4. `apiFetch("/classes?refresh=1", …, NEON_ERROR)`.
5. A 200: re-fill the options as a load does, **keeping the chosen class** when it is still
   in the new list (otherwise the placeholder, and `updateSubmit()`); update
   `class-freshness`; then by `body.refresh`: `"refreshed"` → `REFRESHED_MESSAGE`;
   `"too_soon"` → `REFRESH_TOO_SOON_MESSAGE`; `"failed"` → `REFRESH_FAILED_MESSAGE` with
   the `error` kind (the stale sentence also shows in `class-freshness`). Each is one
   live-region change.
6. An error answer or no answer: the message (`error` kind) as a load shows it, **the
   existing options stay** (a failed refresh never empties a working list), the select and
   the button enabled again.
7. Busy off in every case; focus stays on the button (see Accessibility).

**Script: submitting** (`submit()`):

1. As today, return unless a class, a photo and not `state.submitting`.
2. `setBusy(true)`: `state.submitting = true`; disable `submit`, `class-select`,
   `photo-input` (which disables **Choose a photo**); `result.setAttribute("aria-busy",
   "true")`; hide the result; show `submit-progress` and `submit-elapsed`; start an
   interval of `ELAPSED_TICK_MS` writing `ELAPSED_MESSAGE` into `submit-elapsed` (not a
   live region).
3. `setMessage(submit-status, PREPARING_MESSAGE)`; `await toBase64(...)`.
4. `setMessage(submit-status, SENDING_MESSAGE)`; `apiUpload("/submit", json, onSent)`,
   where `onSent` sets `WAITING_DRY_RUN_MESSAGE` when `config.dryRun`, else
   `WAITING_MESSAGE`. Each step is one live-region change.
5. Success: `renderResult(body)` as today. `PageError`: `renderError(message)` as today.
   `UnconfirmedError`: `renderError(config.dryRun ? DRY_RUN_TIMEOUT_MESSAGE :
   UNCONFIRMED_MESSAGE)`.
6. `finally`: `setBusy(false)` (clear the interval, hide progress and elapsed, remove
   `aria-busy`, re-enable the select and the photo input), clear `submit-status`,
   `updateSubmit()`. `state.photo` and the select's value are never cleared on failure, so
   **Submit** is enabled again with the same class and photo (#118 AC5).
7. While submitting, `onFile()` and the drop handler return at once, and
   `onClassChange()` can't fire (the select is disabled); a second click is ignored by
   `state.submitting` and the disabled button (#118 AC4).

**Accessibility**: `aria-busy` on the select while loading or refreshing and on `#result`
while submitting; the two `role="status"` regions announce each step once; elapsed seconds are
`aria-hidden`; every new control is a native `button` or `progress` (no `tabindex`);
**Try again** and **Refresh class list** have the 3px focus ring of every button.
**Focus while busy** (prep for this phase must check): HTML's focus fixup rule moves focus
to `<body>` when a focused button becomes `disabled` in current browsers. If that is so,
**Try again** and **Refresh class list** use `aria-disabled="true"` while busy (clicks
ignored by the script) instead of `disabled`, with the same disabled look and no new
allowlist word, so focus is never lost (Decision 17).

### Script tests (README Decision 12)

**`tests/page_script_harness.mjs`** (Node ≥ 20, standard library only):

- Reads `page.html`, takes the body of `<script nonce="__CSP_NONCE__">…</script>`, and
  runs it with `vm.runInContext` in a context holding fakes:
  - `document`: `getElementById` for every `id="…"` in the markup (found with a regex) plus
    `page-config` (its `textContent` is the JSON config: `authDomain`, `clientId`,
    `pageUrl: "https://facilities.example/class-photo-upload"`, `dryRun` from the
    scenario); `createElement`; `addEventListener`; `activeElement`. Fake elements keep
    `textContent`, `hidden`, `disabled`, `value`, attributes, `classList`, children
    (`appendChild`, `replaceChildren`, `querySelectorAll("option")` if the script needs it),
    listeners (`addEventListener`, a `dispatch(type, event)` helper), `focus()` (sets
    `document.activeElement`), and `files` for the input.
  - `sessionStorage` (a `Map`) seeded with a token and an expiry an hour after the fake
    clock; `window.location` (`search: ""`, `href`, `assign` recording the URL).
  - A fake clock: `Date.now`, `setTimeout`, `clearTimeout`, `setInterval`,
    `clearInterval`, advanced by the scenario (`await clock.advance(5000)`).
  - `fetch` and `XMLHttpRequest` scripted per scenario (status, body, delay, or "never
    answers", "network error"; the XHR fake calls `upload.onload` when the scenario says
    the upload finished). They record every request (method, URL, headers, body length).
  - `FileReader` (`readAsDataURL` from a `Blob`'s bytes), `Blob`, `URL.createObjectURL`,
    `TextDecoder`, `TextEncoder`, `atob`, `btoa`, `crypto` from Node.
- `node page_script_harness.mjs <scenario> <jpeg path>` runs one scenario and exits 0, or
  prints the failed assertion and exits 1. The JPEG (a valid 1500×1000 file) comes from
  pytest so the photo checks pass for real.
- A choose-photo helper dispatches `change` on `photo-input` with a fake `File` whose
  `arrayBuffer()` returns the JPEG's bytes and whose `size` is its length; a choose-class
  helper sets the select's `value` and dispatches `change`.

**Scenarios** (each name is one pytest test; what it asserts):

| Scenario | Asserts |
| --- | --- |
| `classes_busy_while_loading` | Before `/classes` answers: select disabled with `aria-busy="true"`, `class-progress` shown, `class-status` "Loading classes…", `class-retry` hidden (#117 AC1) |
| `classes_still_loading_after_5s` | At 4.9 s the status is "Loading classes…"; at 5 s "Still loading classes from Neon…"; progress still shown (#117 AC2) |
| `classes_failure_shows_try_again` | A 502 with `{"error": NEON_ERROR}`: progress hidden, `aria-busy` removed, status is the message with the `error` kind, `class-retry` shown and enabled (#117 AC3) |
| `classes_no_answer_shows_try_again` | `/classes` never answers: at 35 s the status is "Couldn't reach the server. Check your connection and try again." and **Try again** shows (#117 AC3) |
| `classes_try_again_reloads_in_place` | After a failure, clicking **Try again**: a second `GET /classes`, no navigation, busy state again and the button disabled; on success the options are listed once, the button hidden, focus on the select (#117 AC3, AC4) |
| `classes_loaded_shows_time` | `refreshed_at` given: `class-freshness` starts "Class list from Neon at " and has no stale text; the select is enabled (#117 AC4) |
| `classes_stale_list_says_out_of_date` | `stale: true`: `class-freshness` also has the stale message (#117 AC4) |
| `submit_disables_controls_and_shows_steps` | During a submission: submit, select and photo input disabled, `#result` `aria-busy`, status "Preparing the photo…" then "Sending the photo…" then, after the upload finishes, "Waiting for the server to check it and open the pull request…"; `submit-elapsed` reads "3 s" after 3 s; the status changed exactly three times (#118 AC4) |
| `submit_dry_run_waiting_step` | `dryRun: true`: the waiting step is the dry-run text |
| `submit_double_click_sends_once` | Two clicks and a dropped photo during a submission: one `POST`; the photo unchanged (#118 AC4) |
| `submit_failure_keeps_class_and_photo` | A 502 with a JSON `error`: that message in the result, the select keeps its value, Submit enabled, a second click sends a second `POST` with the same class and the same photo length (#118 AC5) |
| `submit_gateway_timeout_is_unconfirmed` | A 504 with `{"message": "Endpoint request timed out"}`: the result is `UNCONFIRMED_MESSAGE` (#118 AC6) |
| `submit_network_error_is_unconfirmed` | XHR `onerror` after the upload: `UNCONFIRMED_MESSAGE` (#118 AC6) |
| `submit_timeout_on_dry_run_says_nothing_opened` | `dryRun: true`, no answer: at 35 s the result is `DRY_RUN_TIMEOUT_MESSAGE` (#118 AC6) |
| `submit_server_says_nothing_changed` | A 502 with phase 2's "Nothing was changed on GitHub" message: shown as given (#118 AC6) |
| `submit_success_shows_result` | A 200 `opened` answer: "Opened pull request #12" with the link; busy state gone (no regression) |
| `classes_refresh_button_shown_after_load` | Hidden while loading and after a failure; shown once the list loads; its text is "Refresh class list" |
| `classes_refresh_reloads_from_neon` | Clicking it: `GET /classes?refresh=1`, busy state (select `aria-busy`, progress, button disabled), then `REFRESHED_MESSAGE` and the new time; no navigation |
| `classes_refresh_too_soon_says_so` | `refresh: "too_soon"`: `REFRESH_TOO_SOON_MESSAGE`; the list is the answer's |
| `classes_refresh_failed_keeps_list` | `refresh: "failed"`, `stale: true`: `REFRESH_FAILED_MESSAGE` (`error` kind) and the stale sentence; a 502 with `NEON_ERROR` instead: the message, and the earlier options still listed and selectable |
| `classes_refresh_keeps_chosen_class` | A class chosen before the refresh stays chosen when it is in the new list; a class gone from it resets to the placeholder and Submit is disabled |
| `submit_disables_refresh` | During a submission the Refresh button is disabled and a click sends nothing |

**`tests/test_page_script.py`**:

- A module fixture finds `node` (`shutil.which("node")`). Missing: `pytest.skip("node is not
  installed")` unless the environment has `CI` set, in which case `pytest.fail` (so CI
  can't pass by skipping). GitHub's `ubuntu-latest` runner has Node preinstalled; the
  workflow is not changed.
- A fixture writes `make_jpeg(1500, 1000)` to `tmp_path / "photo.jpg"`.
- `@pytest.mark.parametrize("scenario", SCENARIOS)` →
  `subprocess.run(["node", HARNESS, scenario, str(photo)], capture_output=True, text=True,
  timeout=60)`; assert `returncode == 0`, showing stdout and stderr on failure.
- `test_harness_lists_exactly_these_scenarios`: `node HARNESS --list` prints the scenario
  names; they equal `SCENARIOS`, so a scenario can't be added to one side only.

### Static tests (`tests/test_lambda_function.py`)

- `test_class_field_has_busy_indicator_and_retry`: the markup has
  `<progress id="class-progress"` with an `aria-label` and `hidden`, `id="class-retry"`
  as a `<button type="button"` with the text "Try again", and `class-freshness` not a live
  region.
- `test_submit_has_progress_and_silent_elapsed`: `submit-progress` (`<progress`, labelled,
  hidden) and `submit-elapsed` with `aria-hidden="true"`; `submit-status` keeps
  `role="status"`.
- `test_loading_and_progress_messages_are_in_the_page` (parametrized over the fifteen new
  constants): each appears as `"<text>"` in the script.
- `test_class_field_has_refresh_button`: `<button type="button" id="class-refresh"` with
  the text "Refresh class list", `hidden`, and no `aria-label`.
- `test_busy_indicator_uses_tokens`: `.busy` uses `var(--progress-height)` and
  `accent-color: var(--progress-fill)`; the global `[hidden]` rule has `display: none !important`.
- `test_disabled_photo_button_differs_beyond_colour`: `.drop-zone input:disabled + label`
  has `border-style: dashed` and `cursor: not-allowed`.
- `test_page_sends_submission_to_its_own_origin`: the script's `XMLHttpRequest` URL is
  `config.pageUrl + path` (no other host), and `withCredentials = false`.
- No existing test is weakened or deleted; `test_csp_header` is not edited; the token
  tests' allowlists are not edited.

### docs

Page `README.md`:

- "The Page", item 2: the busy indicator, "Loading classes…", "Still loading classes from
  Neon…" after 5 s, **Try again**, the "Class list from Neon at HH:MM." line (with the
  stale sentence), and **Refresh class list** (what it does, its three outcomes, the
  once-a-minute guard).
- Item 5: the three steps with elapsed seconds, the controls disabled while it runs, and
  the class and photo kept after a failure.
- Item 6: the unconfirmed message (prod) and the dry-run message, and when each shows;
  phase 2's two GitHub messages are shown as given.
- "How It Looks": the native progress bar in Asmbly Purple, the small note text, the
  disabled **Choose a photo**; remove "(loading behaviour belongs to #114)".
- "Testing": the script tests (`test_page_script.py` runs `page_script_harness.mjs` with
  Node; skipped without Node locally, required in CI), and what they cover. Replace #73's
  statement that the page's JavaScript has no automated tests.

Once the button exists (the docs name it only as `?refresh=1` today; prep amendment 9):

- `docs/README.md`, Class Photo Upload entry: "when staff ask for a refresh
  (`GET /class-photo-upload/classes?refresh=1` …)" and "ask for a refresh with
  `?refresh=1`" become "when staff press **Refresh class list** on the page (…)".
- API `README.md`: the `?refresh=1` row and "Emptying it by hand" name the page's
  **Refresh class list** button.

## Acceptance criteria

1. While the class list loads, the select is disabled with `aria-busy="true"`, the native
   progress bar shows, and "Loading classes…" is set once in the live region (#117 AC1).
2. After 5 s without an answer the live region reads "Still loading classes from Neon…"
   (#117 AC2).
3. A failed load shows the message and an enabled **Try again**; pressing it reloads the
   list in place, with the busy state, without navigating (#117 AC3).
4. A loaded list hides the busy state and **Try again**, enables the select, and shows
   "Class list from Neon at HH:MM." plus the stale sentence when `stale` (#117 AC4).
5. While submitting, Submit, the class list and the photo input are disabled; the live
   region goes "Preparing the photo…", "Sending the photo…", then the waiting step, each
   once; elapsed seconds show and aren't announced (#118 AC4).
6. After any failure the class and photo stay and one click resubmits (#118 AC5).
7. A 502/504 without a message, a dropped connection or the 35 s timeout shows
   `UNCONFIRMED_MESSAGE` on prod and `DRY_RUN_TIMEOUT_MESSAGE` on a dry run (#118 AC6).
8. `test_csp_header` and every token test pass unedited, with the two new tokens; the
   page stays under 100 KB; no `style=`, `innerHTML` or `tabindex` (#117 AC5, AC6).
9. Every scenario in the table passes under `node`, run by pytest.
10. A loaded list has **Refresh class list** (accessible name = its text): it reloads the
    list from Neon in place with the busy state, keeps the chosen class when it is still
    listed, says "Class list refreshed from Neon.", the too-soon message, or the Neon
    failure message, and a failed refresh never empties the list (owner Decision 21, #117
    AC7).

## Verification

```bash
.venv/bin/python -m pytest functions/classes/class_photo_upload_page
.venv/bin/python -m pytest
node --version   # the script tests need it; CI's ubuntu-latest has it
```

No template change, so `cfn-lint`, `sam validate` and `sam build` aren't required (run
them if phase 1 is in the same pull request).

After the stage deploy, in a desktop browser and on a phone (or a 320px-wide window):

- Load the page with the cache empty (right after deploy, or after deleting the item):
  the progress bar shows under the class field, "Loading classes…", and after 5 s "Still
  loading classes from Neon…"; then the list and "Class list from Neon at HH:MM.".
- With the browser's network tools set to offline after sign-in, reload: the error and
  **Try again**; go back online and press it: the list loads, focus lands on the list.
- Submit a 3:2 JPEG: the steps change, the seconds count, and the class list, **Choose a
  photo** and **Submit** are disabled until the dry-run result shows.
- Press **Refresh class list**: the busy state, then "Class list refreshed from Neon." and
  a new time; press it again within a minute: the too-soon message. Keyboard only: Tab to
  it, press Enter; focus stays on it.
- With a screen reader (VoiceOver), each step is read once and the seconds aren't read.
- At 320px and 200% zoom nothing scrolls sideways.

## Admin actions

None.

## Hand-off

Done. The page's loading, progress, retry and timeout behaviour is complete; `/offshore`'s
manual QA doc can use the stage checks above by story (#117: the first two and the
Refresh check; #118: the last three). No template, deploy-role or admin change.

As built (with the prep amendments): the script's API calls are `apiGet(path,
fallbackMessage)` (fetch with an `AbortController` at 35 s) and `apiPost(path, json,
fallbackMessage, onSent)` (XMLHttpRequest; the 35 s limit restarts on each upload
progress event and counts from the end of the upload), both reading answers through
`readAnswer`. `UnconfirmedError extends PageError` covers an answer that can't confirm
the result (a 5xx without `error`, an OK answer without JSON) and, on the XHR, an error,
abort or timeout after the photo was sent; one before it is `NETWORK_MESSAGE`. A 200
with no classes (Neon empty, nothing cached) shows an empty list without a message, as
before this phase (review cycle 3, deferred). `updateControls()` (replacing `updateSubmit()`)
sets every control from `state` (`classesLoaded`, `loadingClasses`, `submitting`); **Try
again**, **Refresh class list** and **Submit** use `aria-disabled` while busy so they keep
focus (Chrome 155 drops focus from a focused button that becomes disabled). Submit is also
disabled while the class list loads or refreshes. `REFRESH_OUTCOMES` is a `Map`, so an
unknown `refresh` value shows nothing. The harness has 26 scenarios (the table's 22 plus
`submit_failure_before_sending_is_network_error`, `submit_slow_upload_keeps_waiting`,
`classes_401_signs_in_again` and `submit_401_signs_in_again`); the submission's result
is rendered after `aria-busy` comes off `#result`;
its fake DOM applies the focus fixup rule and ignores clicks on `disabled` controls only.

**Manual QA notes:** besides the stage checks above, keyboard-only: Enter on **Refresh
class list** and on **Submit** keeps the focus on the button through the busy state; a
refresh leaves a chosen class's warning replaced by the refresh message (prep amendment
8, expected). Verified in headless Chrome with the real CSP at 1280px, 320px and 640px
at 2x (200% zoom): no sideways scroll, no CSP or script errors.
