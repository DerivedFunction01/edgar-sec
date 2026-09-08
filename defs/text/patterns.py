"""Domain-neutral line-shape regex primitives shared across detection modules.

These patterns describe SEC filing text shapes that appear in several
detectors: dot-leader rows, trailing page-number suffixes, conformed
signature lines, fill-in separator runs, and structural SGML markers.
Owning them here keeps one calibrated definition per shape; consumers
compose rather than re-declare.

Dependency direction: this module is text-level (``re`` and ``defs.regex``
only). Higher layers — ``defs.tables`` and ``defs.sec_forms`` — compose these
primitives; this module never imports them.
"""

from __future__ import annotations

import re

from defs.regex import build_alternation

__all__ = [
    "PAGE_NUMBER_CORE",
    "RE_COLUMN_GAP",
    "RE_CONFORMED_SIGNATURE",
    "RE_DOT_LEADER",
    "RE_PAGE_NUMBER_SUFFIX",
    "RE_SEPARATOR_RUN",
    "RE_SIGNATURE_LABEL_LINE",
    "RE_STRUCTURAL_SGML",
    "SIGNATURE_LABEL_PREFIXES",
    "roman_to_int",
]

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
    if not re.fullmatch(r"[ivxlcdm]{1,8}", text):
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


# Dot-leader runs used by TOC and index rows.
RE_DOT_LEADER = re.compile(r"\.{3,}")

# Whitespace runs of two or more spaces/tabs that can separate layout
# columns. Gap-position detectors use this one compiled form so column
# semantics stay consistent across features.
RE_COLUMN_GAP = re.compile(r"[ \t]{2,}")

# Core "digits or roman numerals" page-number fragment. Page-marker, TOC,
# and layout detectors compose their positional variants from this core so
# the accepted number forms stay identical everywhere.
PAGE_NUMBER_CORE = r"(?:\d+|[ivxlcdm]+\b)"

# Trailing page-number suffix with no surrounding context requirements.
RE_PAGE_NUMBER_SUFFIX = re.compile(rf"{PAGE_NUMBER_CORE}\s*$", re.IGNORECASE)

# Conformed signature line: an optional ``By:`` label followed by ``/s/``.
# Shared by closing-region detection and layout hard-preservation.
RE_CONFORMED_SIGNATURE = re.compile(r"^\s*(?:By\s*:\s*)?/s/\s")

# Signature/officer label prefixes that begin a signature-block line.
SIGNATURE_LABEL_PREFIXES: tuple[str, ...] = (
    "/s/ ",
    "By:",
    "Name:",
    "Title:",
    "Date:",
    "Signature:",
)
RE_SIGNATURE_LABEL_LINE = re.compile(
    rf"^\s*(?:{build_alternation(SIGNATURE_LABEL_PREFIXES, auto_escape=True)})\s*",
    re.IGNORECASE,
)

# Fill-in/divider runs (dashes, equals, underscores, asterisks) that mark
# separator or fill-in lines.
RE_SEPARATOR_RUN = re.compile(r"[-=_*]{4,}")

# Structural SGML markers that must never be treated as reflowable prose.
RE_STRUCTURAL_SGML = re.compile(
    rf"<(?:{build_alternation(('TABLE', 'S', 'C', 'PAGE', 'DOCUMENT', 'TEXT', 'TYPE', 'CAPTION'))})\b",
    re.IGNORECASE,
)
