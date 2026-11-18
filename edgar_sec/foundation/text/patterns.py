"""Domain-neutral line-shape regex primitives shared across detection modules."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN

RE_DOT_LEADER = re.compile(r"\.{3,}")
RE_COLUMN_GAP = re.compile(r"[ \t]{2,}")
PAGE_NUMBER_CORE = rf"(?:\d+|{ROMAN_NUMERAL_PATTERN}\b)"
RE_PAGE_NUMBER_SUFFIX = re.compile(rf"{PAGE_NUMBER_CORE}\s*$", re.IGNORECASE)
RE_PAGE_REFERENCE = re.compile(r"\bpage\s*(?:no\.?\s*)?[A-Z]?-?\d+", re.IGNORECASE)

# Amount fragments shared across layers (the layer wall bars domain ->
# engine imports): a comma-grouped figure, a 1-3 digit head with triples.
GROUPED_AMOUNT_CORE = r"\d{1,3}(?:,\d{3})+"
# The digit/comma/dot class of a loose figure run; a run is one head digit
# plus a quantified tail of this class.
LOOSE_FIGURE_CLASS = r"[\d,.]"
# The full-word scale vocabulary of a float value ("500 million dollars"):
# singular thousand/million/billion only — no plurals, no abbreviations.
# Suffix tokens and scale labels are wider vocabularies, homed in the engine.
FLOAT_SCALE_ALT = build_alternation(
    ["billion", "million", "thousand"], auto_escape=True
)
# The section-reference keyword terms, spelled as the foundation line
# healer uses them: the full Item term, and the Part keyword prefix —
# each wider consumer (the toc home) keeps its own numeral grammar.
ITEM_REFERENCE_CORE = r"Item\s+\d+"
PART_REFERENCE_CORE = r"Part\s+"
RE_GRAMMATICAL_COMMA = re.compile(r"[a-zA-Z],\s+[a-zA-Z]")
RE_SENTENCE_TERMINAL = re.compile(r"[.!?][\"\x27\u201d\u2019)]?\s*$")
RE_TERMINAL_BOUNDARY = re.compile(r"[.:;!?\"\x27\u201d\u2019)]\s*$")
CONTINUATION_PUNCTUATION = (".", ";", ":", "!", "?")

RE_SEPARATOR_RUN = re.compile(r"[-=_*]{4,}")

_SEPARATOR_CHARS = frozenset("-=_+~*—–―")


def is_separator_line(line: str) -> bool:
    """Whether a line is only a rule: separator characters and whitespace."""
    stripped = line.strip()
    return bool(stripped) and all(
        char in _SEPARATOR_CHARS or char.isspace() for char in stripped
    )


RE_FILL_IN_RUN = re.compile(r"[-_=]{2,}")
RE_TRAILING_FILL_IN = re.compile(r"\s*[-_=]{2,}\s*$")
RE_WHITESPACE = re.compile(r"\s+")
RE_WHITESPACE_GAP = re.compile(r"\s{2,}")
RE_WHITESPACE_SPLIT = re.compile(r"\t+|\s{2,}")
RE_NUMERIC_ENTITY = re.compile(r"&#\d+;")
RE_NAMED_ENTITY = re.compile(r"&[a-z]+;")
RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
RE_TABLE_OPEN = re.compile(r"<table\b", re.IGNORECASE)
RE_TABLE_CLOSE = re.compile(r"</table\s*>", re.IGNORECASE)
RE_TABLE_SPAN = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)

RE_STRUCTURAL_SGML = re.compile(
    rf"<(?:{build_alternation(('TABLE', 'S', 'C', 'PAGE', 'DOCUMENT', 'TEXT', 'TYPE', 'CAPTION'))})\b",
    re.IGNORECASE,
)

__all__ = [
    "CONTINUATION_PUNCTUATION",
    "FLOAT_SCALE_ALT",
    "GROUPED_AMOUNT_CORE",
    "ITEM_REFERENCE_CORE",
    "LOOSE_FIGURE_CLASS",
    "PAGE_NUMBER_CORE",
    "PART_REFERENCE_CORE",
    "RE_COLUMN_GAP",
    "RE_DOT_LEADER",
    "RE_FILL_IN_RUN",
    "RE_GRAMMATICAL_COMMA",
    "RE_NAMED_ENTITY",
    "RE_NON_ALNUM",
    "RE_NUMERIC_ENTITY",
    "RE_PAGE_NUMBER_SUFFIX",
    "RE_PAGE_REFERENCE",
    "RE_SENTENCE_TERMINAL",
    "RE_SEPARATOR_RUN",
    "RE_STRUCTURAL_SGML",
    "RE_TABLE_CLOSE",
    "RE_TABLE_OPEN",
    "RE_TABLE_SPAN",
    "RE_TERMINAL_BOUNDARY",
    "RE_TRAILING_FILL_IN",
    "RE_WHITESPACE",
    "RE_WHITESPACE_GAP",
    "RE_WHITESPACE_SPLIT",
    "is_separator_line",
]
