"""Domain-neutral typographical tokens, bullet markers, and outline regexes."""

from __future__ import annotations

import re

from defs.regex import build_alternation

GLYPH_BULLET_MARKERS: frozenset[str] = frozenset({"•", "●", "·", "\x95", "○", "&#149;"})

BULLET_MARKERS: frozenset[str] = frozenset(
    {"o", "*", "-", "+", "•", "●", "·", "\x95", "○", "–", "—", "&#149;"}
)

BULLET_MARKER_RE: re.Pattern = re.compile(
    rf"^(?:{build_alternation(sorted(BULLET_MARKERS), auto_escape=True)}|\(?\d{{1,2}}[\.\)]?|\(?[a-zA-Z][\.\)]?)$"
)

_ORDERED_TOKEN_ALT = build_alternation(
    ["[ivxlcdm]+", r"\d{1,3}", "[a-zA-Z]"], auto_escape=False
)

# Delimited ordered markers: 1., 1), a., a), i., i), iv.
DELIMITED_ORDERED_MARKER_RE: re.Pattern = re.compile(
    rf"^(?:(?:{_ORDERED_TOKEN_ALT})\s*[.)])$", re.IGNORECASE
)

# Parenthesized / wrapped ordered markers: (1), (a), (i), (iv)
WRAPPED_ORDERED_MARKER_RE: re.Pattern = re.compile(
    rf"^\(\s*(?:{_ORDERED_TOKEN_ALT})\s*\)$", re.IGNORECASE
)


def is_list_or_bullet_marker(token: str) -> bool:
    """Return whether token is an explicit bullet or delimited list marker.

    Bare undelimited English words (e.g. 'a', 'I') return False.
    """
    cleaned = token.strip()
    if cleaned in BULLET_MARKERS:
        return True
    return bool(
        DELIMITED_ORDERED_MARKER_RE.match(cleaned)
        or WRAPPED_ORDERED_MARKER_RE.match(cleaned)
    )


FOOTNOTE_MARKERS: frozenset[str] = frozenset({"*", "+", "†", "‡", "§", "u"})
FOOTNOTE_MARKER_RE: re.Pattern = re.compile(r"^(?:[*+†‡§u]+)(?:\s+[*+†‡§u]+)*$")

__all__ = [
    "BULLET_MARKERS",
    "BULLET_MARKER_RE",
    "DELIMITED_ORDERED_MARKER_RE",
    "FOOTNOTE_MARKERS",
    "FOOTNOTE_MARKER_RE",
    "GLYPH_BULLET_MARKERS",
    "WRAPPED_ORDERED_MARKER_RE",
    "is_list_or_bullet_marker",
]
