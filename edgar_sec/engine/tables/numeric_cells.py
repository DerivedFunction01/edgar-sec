"""Shared financial numeric-cell vocabulary and predicates.
The grammar is a whole-cell match, not a search: `is_numeric_cell("1,234 widgets")` is False,
because a partial match would right-align prose.
"""

from __future__ import annotations

import re

from edgar_sec.domain.world.currencies import (
    ALL_CURRENCY_SYMBOLS,
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dashes import CELL_DASHES
from edgar_sec.foundation.text.patterns import GROUPED_AMOUNT_CORE

from .units import MEASUREMENT_UNITS

UNIT_SYMBOLS: set[str] = set()
for _unit_data in MEASUREMENT_UNITS.values():
    UNIT_SYMBOLS.update(_unit_data.get("symbols", []))

_EMPTY_NUMERIC_MARKERS = CELL_DASHES
FINANCIAL_PLACEHOLDERS = frozenset(
    {
        *(_EMPTY_NUMERIC_MARKERS | {"*"}),
        *(
            f"{symbol}{marker}"
            for symbol in ALL_CURRENCY_SYMBOLS
            for marker in _EMPTY_NUMERIC_MARKERS
        ),
        *(
            f"{marker}{suffix}"
            for marker in _EMPTY_NUMERIC_MARKERS
            for suffix in ("*", ")", "%")
        ),
        "na",
        "n/a",
        "none",
        "nil",
    }
)
_FINANCIAL_PLACEHOLDERS_CASEFOLD = frozenset(
    placeholder.casefold() for placeholder in FINANCIAL_PLACEHOLDERS
)

_CURRENCY_ALTERNATION = build_alternation(
    sorted(ALL_CURRENCY_SYMBOLS), auto_escape=True, sort_longest_first=True
)
_UNIT_ALTERNATION = build_alternation(
    sorted(UNIT_SYMBOLS), auto_escape=True, sort_longest_first=True
)
CURRENCY_TOKEN_RE = re.compile(rf"(?:{_CURRENCY_ALTERNATION})")
UNIT_TOKEN_RE = re.compile(rf"(?:{_UNIT_ALTERNATION})\b", re.IGNORECASE)
NUMERIC_CELL_RE = re.compile(
    rf"^(?:{_CURRENCY_ALTERNATION}\s*)?\(?\s*"
    rf"(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*(?:{_UNIT_ALTERNATION}|%))?"
    rf"(?:\s*[-/]\s*(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*(?:{_UNIT_ALTERNATION}|%))?)?"
    rf"\s*(?:{_CURRENCY_ALTERNATION})?\s*\)?\s*%?$"
)
_NUMERIC_STRIP_RE = re.compile(
    rf"(?:{_CURRENCY_ALTERNATION}|{_UNIT_ALTERNATION}|[%()\-,])"
)

# The strict seat grammar: an optional paren, dollar, and sign
# over a digit-comma core with one decimal tail — the extraction
# seats' whole-cell figure, narrower than NUMERIC_CELL_RE.
STRICT_NUMERIC_CELL_RE = re.compile(r"^\(?\$?-?[\d,]+(\.\d+)?\)?$")

# The in-text numeric core: a leading digit, comma-carrying digits, and one
# optional decimal tail. Form-schema recognizers compose from this token
# instead of re-deriving it.
NUMERIC_TOKEN_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")

# The strict-grouping integer grammar: plain digits, or a 1-3 digit head
# with comma triples. The schema decimal/integer recognizers compose from it.
GROUPED_INTEGER_RE = re.compile(r"[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+")

# The loose grouped-integer fragment: a digit/comma run in any arrangement,
# as running text carries it (the 13F value-total capture is the attested
# consumer). A string fragment — sites compose it in their own patterns.
GROUPED_INTEGER_FRAGMENT = r"[\d,]+"

# The Unicode-digit twin of the numeric token core, spelled with \d where
# the engine's other cores spell [0-9]: Form 144's currency capture admits
# any Unicode decimal digit; sites compose this fragment, never re-spell it.
UNICODE_NUMERIC_CORE = r"\d[\d,]*(?:\.\d+)?"

# The wrapped-cell grammar: an optional open paren, sign, and dollar
# around the Unicode numeric core, with up to two closing parens.
# The separator evidence reads compose this one export.
WRAPPED_NUMERIC_CELL_RE = re.compile(
    r"\(?-?\$?\s*" + UNICODE_NUMERIC_CORE + r"\s*\)?\)?"
)

# A single Unicode decimal digit, anywhere in the text.
DIGIT_RE = re.compile(r"\d")

# Comma-grouped and decimal figures as they appear inside a line of text.
# The figure variant is the two-or-more-places shape financial figures carry.
GROUPED_AMOUNT_RE = re.compile(GROUPED_AMOUNT_CORE)
DECIMAL_AMOUNT_RE = re.compile(r"\d+\.\d+")
DECIMAL_FIGURE_RE = re.compile(r"\d+\.\d{2,}")

# A comma acting as the decimal separator, at the end of a value.
EUROPEAN_COMMA_DECIMAL_RE = re.compile(r"\d+,\d{1,2}$")

# An amount as it appears inside a line of text: the numeric core token
# with an optional currency symbol on either side. Distinct from the
# whole-cell grammar above and from the bare core token.
AMOUNT_RE = re.compile(
    rf"(?:{_CURRENCY_ALTERNATION}\s*)?{NUMERIC_TOKEN_RE.pattern}"
    rf"(?:\s*(?:{_CURRENCY_ALTERNATION}))?"
)


def is_financial_placeholder(value: str) -> bool:
    """Return whether a cell is an exact configured financial placeholder.
    Placeholders fill a numeric column without contributing a value, so they count as numeric data.
    """
    return value.strip().casefold() in _FINANCIAL_PLACEHOLDERS_CASEFOLD


def is_numeric_cell(value: str) -> bool:
    """Recognize a numeric cell using registered currencies and placeholders."""
    value = value.strip()
    return bool(NUMERIC_CELL_RE.fullmatch(value) or is_financial_placeholder(value))


def is_strict_numeric_cell(value: str) -> bool:
    """Recognize a cell under the strict seat grammar.
    No stripping and no placeholder admission: the caller
    presents the cell exactly as the seats present theirs.
    """
    return bool(STRICT_NUMERIC_CELL_RE.match(value))


def is_numeric_start(value: str) -> bool:
    """Return whether a cell starts with a numeric value after token removal."""
    clean = CURRENCY_TOKEN_RE.sub("", value)
    clean = _NUMERIC_STRIP_RE.sub("", clean).replace(" ", "")
    return bool(clean) and (clean[0].isdigit() or clean.startswith(("-", ".")))


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "AMOUNT_RE",
    "CURRENCY_TOKEN_RE",
    "DECIMAL_AMOUNT_RE",
    "DECIMAL_FIGURE_RE",
    "DIGIT_RE",
    "EUROPEAN_COMMA_DECIMAL_RE",
    "FINANCIAL_PLACEHOLDERS",
    "GROUPED_AMOUNT_RE",
    "GROUPED_INTEGER_FRAGMENT",
    "GROUPED_INTEGER_RE",
    "NUMERIC_CELL_RE",
    "NUMERIC_TOKEN_RE",
    "PREFIX_SYMBOLS",
    "STRICT_NUMERIC_CELL_RE",
    "SUFFIX_SYMBOLS",
    "UNIT_SYMBOLS",
    "UNIT_TOKEN_RE",
    "WRAPPED_NUMERIC_CELL_RE",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_strict_numeric_cell",
]
