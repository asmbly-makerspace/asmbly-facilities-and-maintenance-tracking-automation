"""CSP checks shared by the tests of the repository's HTML pages.

A page's tests pass the Content-Security-Policy header it sent and the body it sent to
one of the checks here:

- `style_hash_problems` for a page whose policy allows its one inline `<style>` block by
  its hash (the kiln drop-off viewer);
- `nonce_problems` for a page whose policy allows its inline `<style>` and `<script>` by
  a per-request nonce (the class photo upload page).

Each `*_problems` check returns a list of messages; an empty list is a pass, so a test
writes `assert page_csp.nonce_problems(policy, body) == []` and pytest prints the list
when it fails. A policy the checks can't read (a repeated directive, no single nonce on
`script-src`) is reported as a message, not raised. The parsing helpers `directives` and
`nonce` raise `ValueError` on such a policy.

The checks compute every hash themselves and don't import `common.csp`, so a bug in the
helper can't hide in its own check (`tests/test_page_csp.py` checks this).

Test code only: nothing outside the tests imports this module, and no template packages
this folder (`tests/test_page_style.py` checks that).
"""
import base64
import hashlib
import re

# The one inline <style> block of a hash-policy page: a bare <style> tag, no attributes.
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
_TAG = re.compile(r"<(script|style)\b([^>]*)>", re.I)
_NONCE_ATTRIBUTE = re.compile(r'\bnonce="([^"]*)"')
_DATA_SCRIPT = re.compile(r'\btype="application/json"')
_NONCE_SOURCE = re.compile(r"'nonce-([^'\s]+)'")
# A <script> or <style> element: its opening tag (group 1), its text and its closing tag.
_ELEMENT = re.compile(r"(<(script|style)\b[^>]*>).*?</\2\s*>", re.I | re.S)
_MARKUP_TAG = re.compile(r"<[A-Za-z][^>]*>")
# Neither policy allows inline style attributes or event handlers; the browser drops them.
_INLINE_ATTRIBUTE = re.compile(r"\s(style|on[a-z]+)\s*=", re.I)
# A nonce allows a <script src=...> from any site, so a nonce page's scripts stay inline.
_SRC_ATTRIBUTE = re.compile(r"(?:^|\s)src\s*=", re.I)


def sha256_source(text: str) -> str:
    """The CSP hash source for this exact text: 'sha256-<base64 digest>'."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def directives(policy: str) -> dict[str, str]:
    """A Content-Security-Policy as {directive: sources}, "" for a directive with none.

    Raises ValueError on a repeated directive.
    """
    parsed: dict[str, str] = {}
    for part in policy.split(";"):
        name, _, value = part.strip().partition(" ")
        if name in parsed:
            raise ValueError(f"{name} is repeated")
        parsed[name] = value.strip()
    return parsed


def nonce(policy: str) -> str:
    """The N in the policy's `script-src 'nonce-N'`.

    Raises ValueError when script-src isn't exactly one nonce source.
    """
    match = _NONCE_SOURCE.fullmatch(directives(policy).get("script-src", ""))
    if match is None:
        raise ValueError("script-src must be exactly one nonce source")
    return match.group(1)


def _markup(body: str) -> str:
    """The body with the text of every <script> and <style> element removed, tags kept."""
    return _ELEMENT.sub(r"\1", body)


def _tags(body: str) -> list[tuple[str, str]]:
    """Each <script> and <style> tag in the markup, as (lower-case name, attributes)."""
    return [(match.group(1).lower(), match.group(2)) for match in _TAG.finditer(_markup(body))]


def _inline_attribute_problems(body: str) -> list[str]:
    problems = []
    for tag in _MARKUP_TAG.findall(_markup(body)):
        attribute = _INLINE_ATTRIBUTE.search(tag)
        if attribute:
            problems.append(f"a tag has an inline {attribute.group(1)}= attribute, which the policy blocks")
    return problems


def style_hash_problems(policy: str, body: str, style_block: re.Pattern[str] = STYLE_BLOCK) -> list[str]:
    """What is wrong with a hash policy for this body: [] when its style-src is exactly the
    hash of the body's one <style> block and it allows nothing else inline."""
    try:
        parsed = directives(policy)
    except ValueError as error:
        return [f"the policy can't be read: {error}"]
    problems = []
    if parsed.get("default-src") != "'none'":
        problems.append("default-src is not 'none'")
    if "'unsafe-inline'" in policy:
        problems.append("the policy has 'unsafe-inline'")
    if "script-src" in parsed:
        problems.append("a hash policy has a script-src")
    tags = _tags(body)
    style_tags = sum(1 for name, _ in tags if name == "style")
    blocks = style_block.findall(body)
    if style_tags != 1 or len(blocks) != 1:
        problems.append(
            f"the body must have exactly one <style> block that style_block reads, "
            f"found {style_tags} <style> tags and {len(blocks)} blocks"
        )
    elif parsed.get("style-src") != sha256_source(blocks[0]):
        problems.append("style-src is not the hash of the served <style> block")
    if any(name == "script" for name, _ in tags):
        problems.append("the body has a <script>, which a hash policy blocks")
    return problems + _inline_attribute_problems(body)


def nonce_problems(policy: str, body: str) -> list[str]:
    """What is wrong with a nonce policy for this body: [] when script-src and style-src are
    the same nonce, every <style> and executable <script> tag carries it, and no script
    is loaded with src=."""
    try:
        parsed = directives(policy)
        expected = nonce(policy)
    except ValueError as error:
        return [f"the policy can't be read: {error}"]
    problems = []
    if parsed.get("default-src") != "'none'":
        problems.append("default-src is not 'none'")
    if "'unsafe-inline'" in policy:
        problems.append("the policy has 'unsafe-inline'")
    if parsed.get("style-src") != f"'nonce-{expected}'":
        problems.append("style-src is not exactly script-src's nonce")
    if "__CSP_NONCE__" in body:
        problems.append("the body still has the __CSP_NONCE__ marker")
    # A <script type="application/json"> data block is never run, so it needs no nonce.
    checked = [
        (name, attributes)
        for name, attributes in _tags(body)
        if not (name == "script" and _DATA_SCRIPT.search(attributes))
    ]
    if not any(name == "style" for name, _ in checked):
        problems.append("the body has no <style> tag")
    if not any(name == "script" for name, _ in checked):
        problems.append("the body has no executable <script> tag")
    for name, attributes in checked:
        found = _NONCE_ATTRIBUTE.search(attributes)
        if found is None or found.group(1) != expected:
            problems.append(f"a <{name}> tag has no nonce or another nonce than the policy's")
        if name == "script" and _SRC_ATTRIBUTE.search(attributes):
            problems.append("a <script> tag has a src= attribute, which its nonce would allow from any site")
    return problems + _inline_attribute_problems(body)
