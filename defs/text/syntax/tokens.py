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

# Bracketed ordered markers: [1], [a], [i], [iv]
BRACKETED_ORDERED_MARKER_RE: re.Pattern = re.compile(
    rf"^\[\s*(?:{_ORDERED_TOKEN_ALT})\s*\]$", re.IGNORECASE
)

ORDERED_MARKER_PREFIX_RE: re.Pattern = re.compile(
    r"^(?:(?P<number>\d{1,3})|(?P<roman>[ivxlcdm]+)|(?P<letter>[a-zA-Z]))\s*[.)]\s*",
    re.IGNORECASE,
)
WRAPPED_MARKER_PREFIX_RE: re.Pattern = re.compile(
    r"^\(\s*(?P<token>\d{1,3}|[ivxlcdm]+|[a-zA-Z])\s*\)\s*",
    re.IGNORECASE,
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
        or BRACKETED_ORDERED_MARKER_RE.match(cleaned)
    )


def is_bullet_line(line: str) -> bool:
    """Return whether a line starts with a marker followed by content."""
    parts = line.lstrip().split(maxsplit=1)
    return len(parts) == 2 and is_list_or_bullet_marker(parts[0])


def is_ordered_marker_prefix(value: str) -> bool:
    """Return whether text starts with a delimited ordered marker."""
    return bool(ORDERED_MARKER_PREFIX_RE.match(value.strip()))


def is_wrapped_marker_prefix(value: str) -> bool:
    """Return whether text starts with a parenthesized ordered marker."""
    return bool(WRAPPED_MARKER_PREFIX_RE.match(value.strip()))


FOOTNOTE_MARKERS: frozenset[str] = frozenset({"*", "+", "†", "‡", "§", "u"})
FOOTNOTE_MARKER_RE: re.Pattern = re.compile(r"^(?:[*+†‡§u]+)(?:\s+[*+†‡§u]+)*$")

# Roman numeral character-to-value mapping used by roman_to_int.
_ROMAN_VALUES = {
    "i": 1,
    "v": 5,
    "x": 10,
    "l": 50,
    "c": 100,
    "d": 500,
    "m": 1000,
}

ROMAN_NUMERAL_PATTERN: str = r"[ivxlcdm]{1,8}"
_RE_ROMAN = re.compile(rf"^{ROMAN_NUMERAL_PATTERN}$")

# Canonical numeral-value pairs ordered largest to smallest, used for
# validating that a roman numeral string is in canonical form.
_NUMERALS = (
    ("m", 1000),
    ("cm", 900),
    ("d", 500),
    ("cd", 400),
    ("c", 100),
    ("xc", 90),
    ("l", 50),
    ("xl", 40),
    ("x", 10),
    ("ix", 9),
    ("v", 5),
    ("iv", 4),
    ("i", 1),
)


def roman_to_int(value: str) -> int | None:
    """Parse a canonical bounded Roman numeral string to an integer.

    Returns ``None`` if ``value`` is not a valid canonical Roman numeral
    (e.g. non-canonical forms like ``iiiv`` or values exceeding 3000).
    """
    text = value.casefold()
    if not _RE_ROMAN.fullmatch(text):
        return None
    total = previous = 0
    for char in reversed(text):
        current = _ROMAN_VALUES[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    if not 0 < total <= 3000:
        return None
    remaining, canonical = total, ""
    for numeral, amount in _NUMERALS:
        count, remaining = divmod(remaining, amount)
        canonical += numeral * count
    return total if canonical == text else None


__all__ = [
    "BULLET_MARKERS",
    "BULLET_MARKER_RE",
    "DELIMITED_ORDERED_MARKER_RE",
    "FOOTNOTE_MARKERS",
    "FOOTNOTE_MARKER_RE",
    "GLYPH_BULLET_MARKERS",
    "ORDERED_MARKER_PREFIX_RE",
    "ROMAN_NUMERAL_PATTERN",
    "WRAPPED_MARKER_PREFIX_RE",
    "WRAPPED_ORDERED_MARKER_RE",
    "is_bullet_line",
    "is_list_or_bullet_marker",
    "is_ordered_marker_prefix",
    "is_wrapped_marker_prefix",
    "roman_to_int",
]
