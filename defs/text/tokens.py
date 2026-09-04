"""Domain-neutral typographical tokens, bullet markers, and outline regexes."""

from __future__ import annotations

import re

from defs.regex import build_alternation

BULLET_MARKERS: frozenset[str] = frozenset(
    {"o", "*", "-", "+", "•", "·", "\x95", "–", "—", "&#149;"}
)

BULLET_MARKER_RE: re.Pattern = re.compile(
    rf"^(?:{build_alternation(sorted(BULLET_MARKERS), auto_escape=True)}|\(?\d{{1,2}}[\.\)]?|\(?[a-zA-Z][\.\)]?)$"
)

FOOTNOTE_MARKERS: frozenset[str] = frozenset({"*", "+", "†", "‡", "§", "u"})
FOOTNOTE_MARKER_RE: re.Pattern = re.compile(r"^(?:[*+†‡§u]+)(?:\s+[*+†‡§u]+)*$")

RE_BULLET_PREFIX = BULLET_MARKER_RE

__all__ = [
    "BULLET_MARKERS",
    "BULLET_MARKER_RE",
    "FOOTNOTE_MARKERS",
    "FOOTNOTE_MARKER_RE",
    "RE_BULLET_PREFIX",
]
