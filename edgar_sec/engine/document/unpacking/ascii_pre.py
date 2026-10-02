"""ASCII-PRE discrimination: when `<PRE>` is only a transport wrapper.

A large share of 1990s–2000s EDGAR filings are plain ASCII shipped inside an
HTML envelope whose entire visible content is one `<PRE>` block. Treating those
as HTML sends ASCII reflow and table rendering down a path that cannot help,
and loses the hard line breaks the source actually had. This module is the
discriminator: it returns the payload only when `<PRE>` is provably a wrapper
around otherwise-tag-free text, and `None` in every other case.

`None` is the common answer, and it is never an error.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

_RE_PRE_BLOCK = re.compile(r"(?is)<pre\b[^>]*>(?P<body>.*?)</pre\s*>")
_RE_TAG = re.compile(r"(?is)<[^>]+>")

# Tags whose presence inside the PRE payload means the document is genuinely
# HTML being rendered as markup, rather than ASCII wrapped in a transport tag.
_PRE_PAYLOAD_HTML_TAGS = build_alternation(
    [
        "div",
        "span",
        "font",
        "p",
        "br",
        "a",
        "hr",
        "img",
        "ul",
        "ol",
        "li",
        "tr",
        "td",
        "th",
    ],
    auto_escape=True,
)
_RE_PRE_PAYLOAD_HTML = re.compile(rf"(?is)</?(?:{_PRE_PAYLOAD_HTML_TAGS})\b[^>]*>")


def extract_ascii_pre(text: str) -> str | None:
    """Return the inner payload when PRE is only a transport wrapper.

    Returns `None` unless there is exactly one `<PRE>` block, nothing but tags
    outside it, and no layout markup inside it.
    """
    matches = list(_RE_PRE_BLOCK.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    outside = text[: match.start()] + text[match.end() :]
    if _RE_TAG.sub("", outside).strip():
        return None
    payload = match.group("body")
    if _RE_PRE_PAYLOAD_HTML.search(payload):
        return None
    return payload


__all__ = ["extract_ascii_pre"]
