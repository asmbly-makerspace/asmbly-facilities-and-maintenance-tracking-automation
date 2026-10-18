"""The Asmbly brand tokens and logo that the repository's HTML pages share.

The kiln drop-off viewer and the class photo upload page are the pages that use this
module. A page's `page.html` marks where the shared text goes: `/* __BRAND_TOKENS__ */`
inside its `:root` block and `<!-- __ASMBLY_LOGO__ -->` where the logo goes. The page's
function calls `fill_brand` when it reads `page.html`, before it fills its own
placeholders. Each page keeps its own tokens (its accent, its widths, what it uses a
colour for) in its own `page.html`.

A change here reaches every page that uses it on the next deploy: the deploy publishes a
new version of the common layer, which updates every function that uses that layer.

Keep this module to the Python standard library (today it imports nothing), so that a
page's function can use it with the common layer and no other: no `requests` layer, and
no boto3 loaded. `layers/common/tests/test_brand.py` checks this.
"""

BRAND_TOKENS_MARKER = "/* __BRAND_TOKENS__ */"
ASMBLY_LOGO_MARKER = "<!-- __ASMBLY_LOGO__ -->"

# The shared design tokens, as CSS declarations for a page's :root block. The first line has
# no indentation (the marker it replaces is indented), later lines four spaces, no trailing
# newline.
BRAND_TOKENS = """/* Shared brand tokens, from layers/common/python/common/brand.py. */

    /* Brand colours (Asmbly brand guide). */
    --asmbly-purple: #292D6A;
    --asmbly-white: #F2F4EF;
    --midnight-black: #171d1a;
    --ceramics: #b34a9a;
    --lasers: #D33E43;

    /* Derived, per sRGB channel, rounded: shade(p) = p × colour + (1 − p) × midnight-black;
       tint(p) = p × colour + (1 − p) × asmbly-white. A test recomputes each. */
    --lasers-shade: #ad373b;
    --lasers-20: #ecd0cd;

    /* Type: system stacks, no font file is fetched. PP Gosha Bold, the brand's heading
       face, isn't loaded until Asmbly confirms its web licence covers these pages. */
    --font-body: Roboto, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    --font-heading: "Helvetica Neue", "Segoe UI", Roboto, Arial, system-ui, sans-serif;
    --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --font-size-body: 1rem;
    --font-size-h1: 1.75rem;
    --font-size-h2: 1.25rem;
    --font-size-small: 0.875rem;
    --line-height: 1.5;
    --line-height-heading: 1.2;
    --weight-heading: 700;
    --weight-strong: 600;

    /* Space and size. */
    --space-1: 0.25rem;
    --space-2: 0.5rem;
    --space-3: 0.75rem;
    --space-4: 1rem;
    --space-5: 1.5rem;
    --space-6: 2rem;
    --gutter: var(--space-4);
    --radius: var(--space-2);
    --logo-height: 3.5rem;
    --border-width: 1px;
    --border-width-accent: 4px;
    --focus-width: 3px;
    --focus-offset: 2px;
    --tap-target: 2.75rem;"""

# The official Asmbly logo (asmbly-makerspace/asmbly-classes,
# app/src/lib/components/logo.svelte at 9a534a6c538df1e602fead183e30d93d97c247b4), inline.
# Its colour comes from the page's CSS (.logo { fill: currentColor; }). The first line has no
# indentation (the marker it replaces is indented four spaces), the paths six, `</svg>` four.
ASMBLY_LOGO = """<svg class="logo" role="img" aria-label="Asmbly Makerspace" viewBox="0 0 443.61 122.16" focusable="false">
      <path d="m183.67,64.46c0-3.96,2.59-7.96,8.14-7.96,3.55,0,5.32,1.14,6.32,2.73v-5.23h-12.15v-5.82h18.74v17.51h3.09v6.28h-9.69v-2.27c-1,1.59-2.78,2.73-6.32,2.73-5.55,0-8.14-4-8.14-7.96Zm14.47,0c0-1.41-.96-2.64-3.91-2.64s-3.96,1.23-3.96,2.64.96,2.64,3.96,2.64,3.91-1.23,3.91-2.64Z"/>
      <path d="m211.92,69.51v-6.64c4.14,2.59,7.64,3.41,11.01,3.41,1.77,0,2.64-.64,2.64-1.68,0-1.14-.68-1.68-4-2.14-7.51-.87-9.64-4.05-9.64-7.69,0-5.14,4.28-7.05,9.14-7.05,3.05,0,7.05.82,9.28,2.37v6.14c-3.32-1.64-7.23-2.37-9.74-2.37-1.32,0-2.09.41-2.09,1.46s.59,1.55,4.14,2.18c6.87,1.18,9.51,2.68,9.51,7.32,0,5.1-4.59,7.6-9.92,7.6-3.55,0-7.01-.68-10.33-2.91Z"/>
      <path d="m243.4,54.32v17.65h-6.6v-23.79h34.12v23.79h-6.6v-17.65h-7.14v17.65h-6.6v-17.65h-7.19Z"/>
      <path d="m299.49,60.1c0,6.69-3.27,12.33-10.14,12.33-2.64,0-4.96-.91-6.6-3.37v2.91h-6.6v-31.84h6.6v10.96c1.64-2.46,3.96-3.37,6.6-3.37,6.87,0,10.14,5.69,10.14,12.37Zm-6.6,0c0-4.28-1.64-6.23-5.05-6.23s-5.1,1.96-5.1,6.23,1.64,6.19,5.1,6.19,5.05-1.96,5.05-6.19Z"/>
      <path d="m309.82,40.12v31.84h-6.6v-31.84h6.6Z"/>
      <path d="m338.02,48.18v31.07h-20.02v-6.14h13.42v-5.6c-1.36,1.5-3.59,2.41-6.32,2.41-7.23,0-10.19-4-10.19-10.46v-11.28h6.6v10.92c0,3.18,1.64,4.69,4.96,4.69s4.96-1.5,4.96-4.69v-10.92h6.6Z"/>
      <path d="m191.18,95.26v17.65h-6.6v-23.79h34.12v23.79h-6.6v-17.65h-7.14v17.65h-6.6v-17.65h-7.19Z"/>
      <path d="m222.88,105.4c0-3.96,2.59-7.96,8.14-7.96,3.55,0,5.32,1.14,6.32,2.73v-5.23h-12.15v-5.82h18.74v17.51h3.09v6.28h-9.69v-2.27c-1,1.59-2.77,2.73-6.32,2.73-5.55,0-8.14-4-8.14-7.96Zm14.47,0c0-1.41-.95-2.64-3.91-2.64s-3.96,1.23-3.96,2.64.96,2.64,3.96,2.64,3.91-1.23,3.91-2.64Z"/>
      <path d="m257.82,104.13v8.78h-6.6v-31.85h6.6v16.92h3.23l6-8.87h7.92l-8.23,11.97,8.23,11.83h-7.92l-6-8.78h-3.23Z"/>
      <path d="m275.74,101.08c0-6.87,2.82-12.42,10.6-12.42s10.42,5.19,10.42,11.92v2.64h-14.19c.45,2.68,1.91,4,6.1,4,1.14,0,3.32,0,6.55-.64v6.05c-3.55.73-5.51.73-7.23.73-10.6,0-12.24-7.42-12.24-12.28Zm14.38-2.27c-.18-2.82-1.32-4-3.87-4s-3.64,1.27-3.87,4h7.73Z"/>
      <path d="m307.54,95.26v17.65h-6.6v-23.79h15.33v6.14h-8.73Z"/>
      <path d="m319.91,110.45v-6.64c4.14,2.59,7.64,3.41,11.01,3.41,1.77,0,2.64-.64,2.64-1.68,0-1.14-.68-1.68-4-2.14-7.51-.86-9.64-4.05-9.64-7.69,0-5.14,4.28-7.05,9.14-7.05,3.05,0,7.05.82,9.28,2.37v6.14c-3.32-1.64-7.23-2.37-9.74-2.37-1.32,0-2.09.41-2.09,1.46s.59,1.55,4.14,2.18c6.87,1.18,9.51,2.68,9.51,7.32,0,5.1-4.59,7.6-9.92,7.6-3.55,0-7.01-.68-10.33-2.91Z"/>
      <path d="m368.14,101.04c0,6.69-3.27,12.33-10.14,12.33-2.64,0-4.96-.91-6.6-3.37v10.19h-6.6v-31.07h6.6v2.91c1.64-2.46,3.96-3.37,6.6-3.37,6.87,0,10.14,5.69,10.14,12.37Zm-6.6,0c0-4.28-1.64-6.23-5.05-6.23s-5.1,1.96-5.1,6.23,1.64,6.19,5.1,6.19,5.05-1.96,5.05-6.19Z"/>
      <path d="m371.09,105.4c0-3.96,2.59-7.96,8.14-7.96,3.55,0,5.32,1.14,6.32,2.73v-5.23h-12.15v-5.82h18.74v17.51h3.09v6.28h-9.69v-2.27c-1,1.59-2.77,2.73-6.32,2.73-5.55,0-8.14-4-8.14-7.96Zm14.47,0c0-1.41-.96-2.64-3.91-2.64s-3.96,1.23-3.96,2.64.96,2.64,3.96,2.64,3.91-1.23,3.91-2.64Z"/>
      <path d="m397.61,101.04c0-7.14,3.5-12.37,11.06-12.37,7.14,0,10.65,5.05,10.65,10.46h-6.6c-.18-2.46-.77-4.32-4-4.32-3.87,0-4.5,2.37-4.5,6.23s.64,6.19,4.5,6.19c3.23,0,3.82-1.86,4-4.32h6.6c0,5.41-3.5,10.46-10.65,10.46-7.55,0-11.06-5.19-11.06-12.33Z"/>
      <path d="m422.59,101.08c0-6.87,2.82-12.42,10.6-12.42s10.42,5.19,10.42,11.92v2.64h-14.19c.45,2.68,1.91,4,6.1,4,1.14,0,3.32,0,6.55-.64v6.05c-3.55.73-5.51.73-7.23.73-10.6,0-12.24-7.42-12.24-12.28Zm14.38-2.27c-.18-2.82-1.32-4-3.87-4s-3.64,1.27-3.87,4h7.73Z"/>
      <path d="m122.16,77.71V0H0v44.44h20.85C9.16,51.21,1.05,63.5.1,77.71h-.1v5.59h.1c1.38,20.74,18.01,37.37,38.75,38.75v.1h5.59v-.1c14.22-.95,26.5-9.06,33.27-20.75v20.85h83.3v-44.44h-38.86Zm-5.59,0h-33.27v-33.27h33.27v33.27ZM44.44,44.44h33.27v33.27h-33.27v-33.27ZM83.3,5.59h33.27v33.27h-33.27V5.59Zm-38.86,0h33.27v33.27h-33.27V5.59Zm-38.86,0h33.27v33.27H5.59V5.59Zm33.27,38.96v33.16H5.69c1.36-17.66,15.5-31.81,33.16-33.16ZM5.69,83.3h33.16v33.16c-17.66-1.36-31.81-15.5-33.16-33.16Zm38.75,33.16v-33.16h33.16c-1.36,17.66-15.5,31.81-33.16,33.16Zm72.13.11h-33.27v-33.27h33.27v33.27Zm38.86,0h-33.27v-33.27h33.27v33.27Z"/>
    </svg>"""


def fill_brand(page: str) -> str:
    """`page` with BRAND_TOKENS in place of its token marker and ASMBLY_LOGO in place of its logo marker.

    The token marker must appear exactly once; the logo marker at most once (a page may
    have no logo). Raises ValueError otherwise, naming the marker and the count. Reads
    BRAND_TOKENS and ASMBLY_LOGO when called, so a changed value reaches every page that
    fills itself afterwards.
    """
    tokens = page.count(BRAND_TOKENS_MARKER)
    if tokens != 1:
        raise ValueError(f"page must have exactly one {BRAND_TOKENS_MARKER} marker, found {tokens}")
    logos = page.count(ASMBLY_LOGO_MARKER)
    if logos > 1:
        raise ValueError(f"page must have at most one {ASMBLY_LOGO_MARKER} marker, found {logos}")
    return page.replace(BRAND_TOKENS_MARKER, BRAND_TOKENS).replace(ASMBLY_LOGO_MARKER, ASMBLY_LOGO)
