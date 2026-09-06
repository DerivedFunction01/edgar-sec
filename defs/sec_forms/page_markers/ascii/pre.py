"""Transport-wrapper discrimination for legacy ASCII carried in PRE."""

from __future__ import annotations

import re

from defs.regex import build_alternation

_RE_PRE_BLOCK = re.compile(r"(?is)<pre\b[^>]*>(?P<body>.*?)</pre\s*>")
_RE_TAG = re.compile(r"(?is)<[^>]+>")
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
    """Return the inner payload when PRE is only a transport wrapper."""

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
