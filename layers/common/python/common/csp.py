"""The Content-Security-Policy headers of the repository's HTML pages.

Every policy has the same frame: `default-src 'none'` first, and `base-uri 'none';
form-action 'none'; frame-ancestors 'none'` last. A page names only what it needs in
between:

- `hash_policy(page)` is for a page with no script and one fixed inline `<style>` block,
  allowed by its hash. The kiln drop-off viewer uses it.
- `nonce_policy(new_nonce(), allow)` is for a page with an inline script. It allows the
  page's `<script>` and `<style>` by a nonce that is new on every request. The class photo
  upload page uses it, with `img-src` and `connect-src` in `allow`.
- `strict_policy()` is for a plain error page that needs nothing at all.

The helper checks that the header is well formed: no caller can drop or repeat a
directive or write a `;`, `,` or line break into it. It does not judge what the sources
allow: `'unsafe-inline'` or `*` in `allow` would be written as given. What keeps each
page's policy strict is its pinned header in its tests and the checks in
`tests/page_csp.py`.

Keep this module to the Python standard library, like `brand.py`, so that a page's
function can use it with the common layer and no other.
`layers/common/tests/test_csp.py` checks this.
"""
import base64
import hashlib
import re
import secrets
from collections.abc import Iterable

# The one inline <style> block of a hash-policy page: a bare <style> tag, no attributes.
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
# Every policy starts and ends with these; a caller can't set them.
FIRST: tuple[str, str] = ("default-src", "'none'")
LAST: tuple[tuple[str, str], ...] = (
    ("base-uri", "'none'"),
    ("form-action", "'none'"),
    ("frame-ancestors", "'none'"),
)
_FIXED = frozenset({FIRST[0], *(name for name, _ in LAST)})
# Checked with fullmatch: `$` would also match before a trailing newline.
_DIRECTIVE_NAME = re.compile(r"[a-z]+(?:-[a-z]+)*")
# A ';' would end the directive, a ',' would start a second policy, CR or LF a new header.
_UNSAFE_IN_SOURCES = re.compile(r"[;,\r\n]")
# base64 or base64url, as secrets.token_urlsafe makes it.
_NONCE = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")


def sha256_source(text: str) -> str:
    """The CSP hash source for this exact text: 'sha256-<base64 digest>'. Nothing is stripped."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def style_hash_source(page: str) -> str:
    """The hash source for the page's one inline <style> block.

    Raises ValueError when the page has no bare <style> block or more than one.
    """
    blocks = STYLE_BLOCK.findall(page)
    if len(blocks) != 1:
        raise ValueError(f"page must have exactly one <style> block, found {len(blocks)}")
    # The browser hashes the element's text exactly as written.
    return sha256_source(blocks[0])


def strict_policy(allow: Iterable[tuple[str, str]] = ()) -> str:
    """default-src 'none', then each (directive, sources) in order, then base-uri,
    form-action and frame-ancestors 'none', joined with "; ".

    Raises ValueError for one of the four fixed directives, a repeated directive, a name
    that isn't lower-case words joined by '-', or sources that are blank or contain ';',
    ',', CR or LF.
    """
    seen: set[str] = set()
    parts = [f"{FIRST[0]} {FIRST[1]}"]
    for name, sources in allow:
        if not _DIRECTIVE_NAME.fullmatch(name):
            raise ValueError("directive name must be lower-case words joined by '-'")
        if name in _FIXED:
            raise ValueError(f"{name} is fixed by the policy and can't be set")
        if name in seen:
            raise ValueError(f"{name} is given more than once")
        if not sources.strip() or _UNSAFE_IN_SOURCES.search(sources):
            raise ValueError(f"{name} sources must be non-blank, with no ';', ',', CR or LF")
        seen.add(name)
        parts.append(f"{name} {sources}")
    parts += [f"{name} {sources}" for name, sources in LAST]
    return "; ".join(parts)


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
    if not _NONCE.fullmatch(nonce):
        raise ValueError("nonce must be base64 or base64url")
    source = f"'nonce-{nonce}'"
    return strict_policy([("script-src", source), ("style-src", source), *allow])
