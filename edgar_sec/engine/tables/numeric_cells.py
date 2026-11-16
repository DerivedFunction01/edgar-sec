"""Shared financial numeric-cell vocabulary and predicates.
The grammar is a whole-cell match, not a search: `is_numeric_cell("1,234 widgets")` is False,
because a partial match would right-align prose.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.patterns import GROUPED_AMOUNT_CORE

from .currencies import MAJOR_CURRENCIES
from .units import MEASUREMENT_UNITS

PREFIX_SYMBOLS = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("prefix")
    for symbol in data.get("symbols", [])
)
SUFFIX_SYMBOLS = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("suffix")
    for symbol in data.get("symbols", [])
)
ALL_CURRENCY_SYMBOLS = PREFIX_SYMBOLS | SUFFIX_SYMBOLS

UNIT_SYMBOLS: set[str] = set()
for _unit_data in MEASUREMENT_UNITS.values():
    UNIT_SYMBOLS.update(_unit_data.get("symbols", []))

_EMPTY_NUMERIC_MARKERS = frozenset({"—", "-", "–"})
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

# The in-text numeric core: a leading digit, comma-carrying digits, and one
# optional decimal tail. Form-schema recognizers compose from this token
# instead of re-deriving it.
NUMERIC_TOKEN_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")

# The strict-grouping integer grammar: plain digits, or a 1-3 digit head
# with comma triples. The schema decimal/integer recognizers compose from it.
GROUPED_INTEGER_RE = re.compile(r"[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+")

# The loose grouped-integer fragment: a digit/comma run in any arrangement,
# as running text actually carries it (the 13F value-total capture is the
# attested consumer). A string fragment, not a compiled recognizer — sites
# compose it inside their own anchored patterns.
GROUPED_INTEGER_FRAGMENT = r"[\d,]+"

# The Unicode-digit twin of the numeric token core: a leading digit,
# comma-carrying digits, and one optional decimal tail, spelled with \d
# where the engine's other cores spell [0-9]. Form 144's currency capture
# admits any Unicode decimal digit; sites compose this fragment instead
# of re-spelling it.
UNICODE_NUMERIC_CORE = r"\d[\d,]*(?:\.\d+)?"

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
    "EUROPEAN_COMMA_DECIMAL_RE",
    "FINANCIAL_PLACEHOLDERS",
    "GROUPED_AMOUNT_RE",
    "GROUPED_INTEGER_FRAGMENT",
    "GROUPED_INTEGER_RE",
    "NUMERIC_CELL_RE",
    "NUMERIC_TOKEN_RE",
    "PREFIX_SYMBOLS",
    "SUFFIX_SYMBOLS",
    "UNIT_SYMBOLS",
    "UNIT_TOKEN_RE",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
]
