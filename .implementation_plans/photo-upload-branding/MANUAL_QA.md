# Manual QA: Photo upload branding

Acceptance steps for `feature/photo-upload-branding`, by story, so each check maps back to
#112 and #113 (epic #111).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`.

> Automated checks already passed on the branch: pytest 1550 passed, cfn-lint 4 W3005
> findings already on stage (no template changed), sam validate pass, sam build pass.
> The integration check also confirmed the page's `<script>` and `lambda_function.py`
> are byte-identical to `stage`, the CSP is unchanged, and the served page is 58 KB
> (limit 100 KB). These steps cover what a person should see in a browser: the tests
> can't render the page.

## Prerequisites

- An account in the staff sign-in pool (you sign in at `login.mcp.asmbly.org`). No admin
  actions: this change adds no resource, secret, parameter or route.
- The stage page: <https://4s626uu7q5.execute-api.us-east-2.amazonaws.com/stage/class-photo-upload>.
  Stage is a dry run: submitting opens nothing on GitHub.
- A desktop Chrome or Firefox with DevTools; a phone, or DevTools' device toolbar, for
  the touch and width steps.
- Test photos. Make them with the commands in the earlier plan's
  [MANUAL_QA.md, "Prerequisites", "Test files"](../class-photo-upload/MANUAL_QA.md#prerequisites)
  (`~/class-photo-qa/`): you need `good-3x2.jpg`, `gps.jpg`, `four-three.jpg`,
  `not-a-jpeg.jpg` and `big.jpg`.
- Optional, to compare looks: the brand guide screenshots in #111, and the WebAIM
  contrast checker (<https://webaim.org/resources/contrastchecker/>).

Keep DevTools → Console open for the whole walk-through. No third-party webhooks are
involved.

---

## #112: Class photo upload page: Asmbly logo, colours and type (phase 1)

1. In a fresh private window, open the stage page. **Expect:** while it signs in, the page
   already shows the full-width Asmbly Purple (`#292D6A`) header band with the official
   horizontal Asmbly logo in Asmbly White and "Class photo upload", then the colourful
   pattern strip under the band, then "Signing in…". Then the hosted sign-in at
   `login.mcp.asmbly.org`.
2. Sign in. **Expect:** back on the page, the band now also has **Sign out** on the right
   (an outline button in Asmbly White). Under the strip, the stage banner "Stage: dry run.
   Submitting checks the photo and shows what would happen; nothing is opened on GitHub."
   on a light yellow tint with a purple left edge and an "i" glyph.
3. Look closely at the logo. **Expect:** it matches the primary horizontal logo in the
   brand guide (#111): the mark and the "asmbly" wordmark, crisp, not blurry or
   stretched, at least 50px tall (it is 56px). Zoom the browser to 300%: it stays sharp
   (it is vector).
4. Look at the pattern strip. **Expect:** a row of simple geometric tiles in the
   sub-brand colours (woodwork yellow, metalwork blue, lasers red, textiles teal,
   electronics green, 3D-printing orange, ceramics magenta) with purple and Asmbly White,
   like the brand guide's strip. It is redrawn (no official vector exists; plan Decision
   8), so it resembles the guide rather than matching it tile for tile. It fills the
   full width with no gap at the right edge.
5. Look at the colours and type of the page body. **Expect:** the background is Asmbly
   White (`#F2F4EF`, a soft off-white, not pure white), text is Midnight Black
   (`#171d1a`, not pure black). Headings ("Class photo upload", "Class", "Photo") are a
   bold sans-serif (Helvetica Neue, Segoe UI or Roboto, by device: PP Gosha is not used,
   by the owner's decision). Body text is Roboto where the device has it, else the system
   sans-serif. The old ceramics magenta is gone from the controls.
6. DevTools → Elements → `<style>` → the `:root` block. **Expect:** the brand colours
   are tokens named after the guide (`--asmbly-purple`, `--asmbly-white`,
   `--midnight-black`, `--woodwork`, …), with the values in the page README's "Brand and
   Design Tokens" table. (The tests enforce that no rule outside `:root` writes a colour;
   this is only a look.)
7. DevTools → Console, after a full reload of the signed-in page. **Expect:** no
   Content-Security-Policy violations ("Refused to load…", "Refused to apply inline
   style…") and no other errors. DevTools → Network: only the page itself, the
   `classes` request and the sign-in host; no font file, image or request to
   `asmbly.org` or any other host.
8. Contrast spot checks with the WebAIM checker (the tests compute these too; this
   confirms what you see): Asmbly White `#F2F4EF` on Asmbly Purple `#292D6A` (the band
   text) and Midnight Black `#171d1a` on Asmbly White (body text). **Expect:** both
   above 4.5:1 (both are above 10:1).

## #113: Class photo upload page: branded, readable controls, messages and result (phase 2)

Every text below is word for word what the page showed before the branding: only its
look changed. If any wording, order or behaviour differs from the earlier plan's
[MANUAL_QA.md](../class-photo-upload/MANUAL_QA.md) steps 1–15 and 21–27, that is a bug
(the script is byte-identical to `stage`).

### Every state

9. Signed in, before the classes load. **Expect:** "Loading classes…" in plain text (no
   edge, no glyph), and the **Class** list dashed and tinted while disabled. Then the
   list is solid with a 60% purple border.
10. Choose a class with the longest name you can find. **Expect:** the list cuts the
    name short with no sideways scrolling of the page. **Submit** is disabled: a light
    purple tint with a dashed border, dark text, and a "not allowed" cursor over it
    (different from the enabled button by more than colour).
11. Drag `good-3x2.jpg` over the photo box and hold it there. **Expect:** while dragged
    over, the box is tinted and its dashed border turns solid purple. Drop it.
    **Expect:** the preview, its size, and "This photo can be used." in green with a
    green left edge and a "✓"; **Submit** turns Asmbly Purple with Asmbly White text.
    Directly above Submit: the public-on-GitHub warning ("When you submit, this photo
    becomes public on GitHub right away, …") in bold dark text on a light red tint, with
    a red left edge and a "!".
12. Choose `gps.jpg`. **Expect:** as step 11, plus "Location data was removed from this
    photo." styled as a success (green edge, "✓").
13. Choose each bad photo in turn: `not-a-jpeg.jpg`, `four-three.jpg`, `big.jpg`.
    **Expect:** each shows its error ("This file isn't a JPEG photo. …", "This photo is
    2000×1500, which is 4:3. …", "This photo is <n.n> MB. …") in bold dark red text with
    a red left edge and a "✕", and **Submit** goes back to its disabled look.
14. Choose `good-3x2.jpg` again and click **Submit**. **Expect:** "Submitting…" in plain
    text, then the dry-run result: a card with a purple top edge and a thin border, its
    first line "Dry run: nothing was opened" as a success (green edge, "✓"), then "Would
    add" or "Would replace" `app/src/lib/images/<file>`, "Files it would remove:", the
    title, and the description in a tinted monospace block. Long file names and the
    description wrap inside the card.
15. Error result: DevTools → Network → set throttling to **Offline**, then click
    **Submit**. **Expect:** "Couldn't reach the server. Check your connection and try
    again." as an error (red edge, "✕"). Set throttling back to **No throttling**.
16. Class list error: DevTools → Network → right-click the `classes` request → **Block
    request URL**, then reload. **Expect:** "Couldn't load the class list. Try again in a
    minute." as an error (red edge, "✕"), with the band and strip above it. Remove the
    block (Network → Network request blocking → untick it) and reload.
17. Sign-in error: open the stage page's address with `?code=x&state=y` added.
    **Expect:** the band and strip, then "Sign-in didn't finish. Sign in again." as an
    error (red edge, "✕") with a **Sign in again** button in Asmbly Purple. Click it:
    it goes to the hosted sign-in, and after signing in the page works.
18. If a class in the list has a `problem` or a `warning` (earlier plan's steps 4 and 5),
    choose it. **Expect:** the problem shows as an error (red edge, "✕") and keeps Submit
    disabled; a `warning` stays plain text (no edge, no glyph).

### Keyboard

19. Reload the signed-in page, click on the page background, then press Tab repeatedly.
    **Expect:** focus moves in this order: **Sign out**, the **Class** list, **Choose a
    photo**, **Submit** (once enabled), then the result's link if there is one. Each
    shows a clear 3px ring: woodwork yellow on **Sign out** (on the purple band), Asmbly
    Purple everywhere else. The hidden file input shows its ring around **Choose a
    photo**. Shift+Tab goes back in reverse. (In Safari, turn on Settings → Advanced →
    "Press Tab to highlight each item" first.)
20. With the keyboard only: choose a class (arrow keys), open the file chooser (Space or
    Enter on **Choose a photo**), choose `good-3x2.jpg`, and press Enter on **Submit**.
    **Expect:** the same result as step 14, with no mouse.

### Hover

21. On a desktop with a mouse or trackpad, point at each control. **Expect:** **Submit**,
    **Choose a photo** and **Sign in again** turn the lighter 80% purple; **Sign out**
    fills with Asmbly White and its text turns purple; the class list's and the photo
    box's borders turn Asmbly Purple; the result's link gets a thicker underline. Disabled
    **Submit** doesn't change.
22. On a phone (or DevTools device toolbar with a touch device such as "iPhone 12 Pro",
    then reload), tap **Choose a photo** and cancel, tap the **Class** list and close it,
    and tap the photo box and cancel. **Expect:** no control stays in its hover look
    (lighter purple, or a darker border) after the tap.

### Width and zoom

23. DevTools device toolbar → Responsive, width **320**. Go through steps 10, 11 and 14
    (longest class name, a photo, the dry-run result). **Expect:** no horizontal scroll
    bar and nothing cut off on the right except the pattern strip, which is cropped by
    design; the header wraps (the logo, title and **Sign out** stack as needed); every
    text wraps.
24. Back at a normal desktop width (about 1280px), zoom the browser to **200%** and repeat
    step 23. **Expect:** the same: no sideways scroll, readable, the page one column up to
    760px wide.

### Contrast spot checks

25. With the WebAIM checker (the tests compute these; this confirms them):
    error text `#ad373b` on Asmbly White `#F2F4EF`, success text `#057a5d` on Asmbly
    White, Asmbly White on Asmbly Purple (buttons), Midnight Black `#171d1a` on the
    warning tint `#ecd0cd` and on the banner tint `#f2e8c5`. **Expect:** each 4.5:1 or
    more (error about 5.6:1, success about 4.8:1). If anything else looks faint to you,
    pick its colours in DevTools and check it the same way.
26. DevTools → Console, after steps 9–24. **Expect:** still no CSP violations or errors.

### Unchanged behaviour

27. Compare with the earlier plan's checklist: sign in, the class list, each photo
    message, location removal and the dry-run result read exactly as its steps 1–15 and
    21–27 describe. Click **Sign out**. **Expect:** straight back to the hosted sign-in
    (no "signed out" screen; that is expected).

---

## Known limits

- **Safari's class list height.** Safari may draw the native `select` at its own height
  rather than 44px. Not checked during the build (no Safari available). In Safari, note
  whether the **Class** list is visibly shorter than the buttons; a short list is a known
  limit, not a blocker.
- **Message glyphs on older browsers.** Safari before 17.4 and Firefox before 128 show no
  "✕", "✓", "!" or "i"; the left edge, the background and the weight still tell the
  message kinds apart. On such a browser, check that only the glyph is missing.
- **Heading font.** Headings use a bold system font, not PP Gosha, by the owner's
  decision (plan Decision 5): PP Gosha's web licence for this site is unconfirmed. Not a
  defect.
- **The pattern strip is redrawn**, not the official file (plan Decision 8).
- **Drag flicker.** The photo box's drag look can flicker as the photo passes over its
  text; the fix needs a script change and belongs with #114.
- Loading, progress and retry behaviour are unchanged here; they belong to #114.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
