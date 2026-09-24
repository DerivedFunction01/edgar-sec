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
from defs.text.signatures import (
    RE_CONFORMED_SIGNATURE,
    RE_SIGNATURE_LABEL_LINE,
    SIGNATURE_LABEL_PREFIXES,
)
from defs.text.tokens import ROMAN_NUMERAL_PATTERN

__all__ = [
    "CONTINUATION_PUNCTUATION",
    "PAGE_NUMBER_CORE",
    "RE_COLUMN_GAP",
    "RE_CONFORMED_SIGNATURE",
    "RE_DOT_LEADER",
    "RE_FILL_IN_RUN",
    "RE_GRAMMATICAL_COMMA",
    "RE_NON_ALNUM",
    "RE_PAGE_NUMBER_SUFFIX",
    "RE_SENTENCE_TERMINAL",
    "RE_SEPARATOR_LINE",
    "RE_SEPARATOR_RUN",
    "RE_SIGNATURE_LABEL_LINE",
    "RE_STRUCTURAL_SGML",
    "RE_TERMINAL_BOUNDARY",
    "RE_TRAILING_FILL_IN",
    "RE_WHITESPACE",
    "SIGNATURE_LABEL_PREFIXES",
]

# Dot-leader runs used by TOC and index rows.
RE_DOT_LEADER = re.compile(r"\.{3,}")

# Whitespace runs of two or more spaces/tabs that can separate layout
# columns. Gap-position detectors use this one compiled form so column
# semantics stay consistent across features.
RE_COLUMN_GAP = re.compile(r"[ \t]{2,}")

# Core "digits or roman numerals" page-number fragment. Page-marker, TOC,
# and layout detectors compose their positional variants from this core so
# the accepted number forms stay identical everywhere.
PAGE_NUMBER_CORE = rf"(?:\d+|{ROMAN_NUMERAL_PATTERN}\b)"

# Trailing page-number suffix with no surrounding context requirements.
RE_PAGE_NUMBER_SUFFIX = re.compile(rf"{PAGE_NUMBER_CORE}\s*$", re.IGNORECASE)

# Grammatical clause commas separating alpha words (e.g. "apples, oranges")
RE_GRAMMATICAL_COMMA = re.compile(r"[a-zA-Z],\s+[a-zA-Z]")

RE_SENTENCE_TERMINAL = re.compile(r"[.!?][\"\x27\u201d\u2019)]?\s*$")
RE_TERMINAL_BOUNDARY = re.compile(r"[.:;!?\"\x27\u201d\u2019)]\s*$")
CONTINUATION_PUNCTUATION = (".", ";", ":", "!", "?")

# Fill-in/divider runs (dashes, equals, underscores, asterisks) that mark
# separator or fill-in lines.
RE_SEPARATOR_RUN = re.compile(r"[-=_*]{4,}")
RE_SEPARATOR_LINE = re.compile(r"^\s*[-=_+]{2,}(?:\s+[-=_+]{2,})*\s*$")
RE_FILL_IN_RUN = re.compile(r"[-_=]{2,}")
RE_TRAILING_FILL_IN = re.compile(r"\s*[-_=]{2,}\s*$")
RE_WHITESPACE = re.compile(r"\s+")
RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Structural SGML markers that must never be treated as reflowable prose.
RE_STRUCTURAL_SGML = re.compile(
    rf"<(?:{build_alternation(('TABLE', 'S', 'C', 'PAGE', 'DOCUMENT', 'TEXT', 'TYPE', 'CAPTION'))})\b",
    re.IGNORECASE,
)
