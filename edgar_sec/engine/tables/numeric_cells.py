"""Shared financial numeric-cell vocabulary and predicates.
The grammar is a whole-cell match, not a search: `is_numeric_cell("1,234 widgets")` is False,
because a partial match would right-align prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.domain.world.currencies import (
    ALL_CURRENCY_SYMBOLS,
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dashes import CELL_DASHES, is_blank_or_dash
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

# The wrapped grouped-cell grammar: an optional paren and dollar
# over the loose grouped fragment with one decimal tail. The grid
# and separator value parses gate on this one export.
GROUPED_CELL_RE = re.compile(rf"^\(?\$?{GROUPED_INTEGER_FRAGMENT}(?:\.\d+)?\)?$")

# The signed-token cell grammar: the homed numeric token under an
# optional paren, dollar, sign, and percent tail, matched against
# the original cell. The lease value parse gates on this export.
SIGNED_NUMERIC_CELL_RE = re.compile(
    r"^\(?\$?\s*-?" + NUMERIC_TOKEN_RE.pattern + r"\s*\)?%?$"
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


# Cell tokens carrying no value in the grid and separator parses:
# the homed cell dashes plus the blank and star markers.
_NO_VALUE_TOKENS = CELL_DASHES | {"", "*"}


@dataclass(frozen=True, slots=True)
class CellValuePolicy:
    """One consumer's value-parse projection, as data: its percent
    handling, dash handling, gate, paren handling, space handling."""

    percent: str
    dash: str
    gate: str
    paren: str
    spaces: bool


@dataclass(frozen=True, slots=True)
class CellValue:
    """One cell's parse under a policy: the value (None when the
    policy prices no value), the token facts, and whether a
    numeric value was parsed from the cell's digits."""

    value: float | None
    is_dash: bool
    is_percent: bool
    is_zero_token: bool
    is_numeric: bool


EPS_VALUE_POLICY = CellValuePolicy(
    percent="exclude",
    dash="zero_flagged",
    gate="float_free",
    paren="single_pair",
    spaces=True,
)
INCOME_VALUE_POLICY = CellValuePolicy(
    percent="strip_all",
    dash="absent",
    gate="float_free",
    paren="strip_chars",
    spaces=False,
)
ROLLFORWARD_VALUE_POLICY = CellValuePolicy(
    percent="rstrip",
    dash="none_value",
    gate="grouped_core",
    paren="strip_chars",
    spaces=False,
)
TAX_VALUE_POLICY = CellValuePolicy(
    percent="schema",
    dash="not_numeric",
    gate="grouped_core",
    paren="strip_chars",
    spaces=False,
)
LEASE_VALUE_POLICY = CellValuePolicy(
    percent="strip_all",
    dash="absent",
    gate="numeric_token",
    paren="strip_chars",
    spaces=False,
)


def _policy_substrate(
    token: str, policy: CellValuePolicy, schema_re: re.Pattern[str] | None
) -> str | None:
    """The policy's float substrate for a token, or None when the
    policy's gate rejects the token before the float read."""
    if policy.gate == "grouped_core":
        if policy.percent == "rstrip":
            core = token.rstrip("%").strip()
        else:
            if schema_re is None:
                raise ValueError("schema percent policy requires schema_re")
            core = schema_re.sub("", token).strip()
        return core if GROUPED_CELL_RE.match(core) else None
    if policy.gate == "numeric_token":
        if not SIGNED_NUMERIC_CELL_RE.match(token):
            return None
        return token.replace("$", "").replace(",", "").replace("%", "")
    substrate = token.replace("$", "").replace(",", "")
    if policy.percent == "strip_all":
        substrate = substrate.replace("%", "").strip()
    if policy.spaces:
        substrate = substrate.replace(" ", "")
    return substrate


def parse_cell_value(
    cell: str, policy: CellValuePolicy, schema_re: re.Pattern[str] | None = None
) -> CellValue:
    """The one cell value parse: the token's facts read once, the
    policy's projection applied. The schema percent pattern is
    passed by its consumer — its home imports this module."""
    token = (cell or "").strip()
    is_dash = is_blank_or_dash(token)
    is_zero_token = token in _NO_VALUE_TOKENS
    is_percent = "%" in token
    if policy.dash == "zero_flagged" and is_dash:
        return CellValue(0.0, is_dash, is_percent, is_zero_token, False)
    if policy.dash in ("none_value", "not_numeric") and is_zero_token:
        return CellValue(None, is_dash, is_percent, is_zero_token, False)
    if policy.percent == "exclude" and is_percent:
        return CellValue(None, is_dash, is_percent, is_zero_token, False)
    substrate = _policy_substrate(token, policy, schema_re)
    if substrate is None:
        return CellValue(None, is_dash, is_percent, is_zero_token, False)
    negative = substrate.startswith("(") and substrate.endswith(")")
    if policy.gate == "grouped_core":
        digits = substrate.strip("()$").replace(",", "")
    elif policy.paren == "single_pair":
        digits = substrate[1:-1] if negative else substrate
    else:
        digits = substrate.strip("()$")
    try:
        value = float(digits)
    except ValueError:
        return CellValue(None, is_dash, is_percent, is_zero_token, False)
    return CellValue(
        -value if negative else value, is_dash, is_percent, is_zero_token, True
    )


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "AMOUNT_RE",
    "CURRENCY_TOKEN_RE",
    "CellValue",
    "CellValuePolicy",
    "DECIMAL_AMOUNT_RE",
    "DECIMAL_FIGURE_RE",
    "DIGIT_RE",
    "EPS_VALUE_POLICY",
    "EUROPEAN_COMMA_DECIMAL_RE",
    "FINANCIAL_PLACEHOLDERS",
    "GROUPED_AMOUNT_RE",
    "GROUPED_CELL_RE",
    "GROUPED_INTEGER_FRAGMENT",
    "GROUPED_INTEGER_RE",
    "INCOME_VALUE_POLICY",
    "LEASE_VALUE_POLICY",
    "NUMERIC_CELL_RE",
    "NUMERIC_TOKEN_RE",
    "PREFIX_SYMBOLS",
    "ROLLFORWARD_VALUE_POLICY",
    "SIGNED_NUMERIC_CELL_RE",
    "STRICT_NUMERIC_CELL_RE",
    "SUFFIX_SYMBOLS",
    "TAX_VALUE_POLICY",
    "UNIT_SYMBOLS",
    "UNIT_TOKEN_RE",
    "WRAPPED_NUMERIC_CELL_RE",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_strict_numeric_cell",
    "parse_cell_value",
]
