"""Domain-neutral line-shape regex primitives shared across detection modules."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN

RE_DOT_LEADER = re.compile(r"\.{3,}")
RE_COLUMN_GAP = re.compile(r"[ \t]{2,}")
PAGE_NUMBER_CORE = rf"(?:\d+|{ROMAN_NUMERAL_PATTERN}\b)"
RE_PAGE_NUMBER_SUFFIX = re.compile(rf"{PAGE_NUMBER_CORE}\s*$", re.IGNORECASE)
RE_GRAMMATICAL_COMMA = re.compile(r"[a-zA-Z],\s+[a-zA-Z]")
RE_SENTENCE_TERMINAL = re.compile(r"[.!?][\"\x27\u201d\u2019)]?\s*$")
RE_TERMINAL_BOUNDARY = re.compile(r"[.:;!?\"\x27\u201d\u2019)]\s*$")
CONTINUATION_PUNCTUATION = (".", ";", ":", "!", "?")

RE_SEPARATOR_RUN = re.compile(r"[-=_*]{4,}")
RE_SEPARATOR_LINE = re.compile(r"^\s*[-=_+]{2,}(?:\s+[-=_+]{2,})*\s*$")
RE_FILL_IN_RUN = re.compile(r"[-_=]{2,}")
RE_TRAILING_FILL_IN = re.compile(r"\s*[-_=]{2,}\s*$")
RE_WHITESPACE = re.compile(r"\s+")
RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")

RE_STRUCTURAL_SGML = re.compile(
    rf"<(?:{build_alternation(('TABLE', 'S', 'C', 'PAGE', 'DOCUMENT', 'TEXT', 'TYPE', 'CAPTION'))})\b",
    re.IGNORECASE,
)

__all__ = [
    "CONTINUATION_PUNCTUATION",
    "PAGE_NUMBER_CORE",
    "RE_COLUMN_GAP",
    "RE_DOT_LEADER",
    "RE_FILL_IN_RUN",
    "RE_GRAMMATICAL_COMMA",
    "RE_NON_ALNUM",
    "RE_PAGE_NUMBER_SUFFIX",
    "RE_SENTENCE_TERMINAL",
    "RE_SEPARATOR_LINE",
    "RE_SEPARATOR_RUN",
    "RE_STRUCTURAL_SGML",
    "RE_TERMINAL_BOUNDARY",
    "RE_TRAILING_FILL_IN",
    "RE_WHITESPACE",
]
