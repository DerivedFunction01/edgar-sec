"""Scanner routing amount, scale, and percent recognition through its homes.

Flags a private money-amount recognizer (a loose amount core, a comma-grouped
figure, or a decimal figure spelled as pattern text) outside
`engine/tables/numeric_cells.py`, a private scale vocabulary (a scale-word
alternation or an `in <scale>` label spelled as pattern text) outside
`engine/tables/patterns.py`, and a private percent recognizer (a digit core
with a `%` tail, or a percent-sign alternation spelled as pattern text)
outside `engine/forms/common/numbers.py`. Allows imports and compositions
of the homed patterns anywhere; the homes themselves are exempt, as are
the sanctioned sites below (each carries its ruling).
"""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

# The loose amount core in either digit spelling, with its decimal tail:
# `[0-9][0-9,]*(?:\.[0-9]+)?`, `\d[\d,]*(\.\d+)?`, `[0-9][0-9,]{2,}...`.
_MONEY_CORE_RE = re.compile(
    r"(?:\[0-9\]|\\d)\[(?:0-9|\\d),\]*(?:\*|\{[\d,]+\})\(?(?:\?:)?\\."
)

# A comma-grouped figure: `\d{1,3}(?:,\d{3})+` in either digit spelling.
_MONEY_GROUPED_RE = re.compile(r"(?:\\d|\[0-9\])\{1,3\}\(\?:,(?:\\d|\[0-9\])\{3\}\)\+")

# A decimal figure: `\d+\.\d+` or `\d+\.\d{2,}` in either digit spelling.
_MONEY_DECIMAL_RE = re.compile(
    r"(?:\\d|\[0-9\])\+\\\.(?:\\d|\[0-9\])\+"
    r"|(?:\\d|\[0-9\])\+\\\.(?:\\d|\[0-9\])\{2,\}"
)

_SCALE_WORD = r"(?:thousands?|millions?|billions?|trillions?)"

# A scale-word alternation spelled with pattern bars: `thousand|million|...`.
_SCALE_PIPE_RE = re.compile(
    rf"(?:{_SCALE_WORD}\s*\||\|\s*{_SCALE_WORD})", re.IGNORECASE
)

# A scale-word alternation spelled as builder list items: 'billion', 'million'.
_SCALE_LIST_RE = re.compile(
    rf"[\"']{_SCALE_WORD}[\"']\s*,\s*[\"']{_SCALE_WORD}[\"']", re.IGNORECASE
)

# An `in <scale>` label spelled as a regex or as a plain string literal.
_SCALE_LABEL_RE = re.compile(
    rf"(?:in\\s\+{_SCALE_WORD}|[\"']in (?:{_SCALE_WORD}|hundreds?)[\"'])",
    re.IGNORECASE,
)

# A digit core carrying a `%` tail within a short span: `\d+(?:\.\d+)?%$`,
# `\d+(?:,\d{3})*(?:\.\d+)?%?`, `\d+(?:\.\d+)?)\s*([a-zA-Z%]*`.
_PERCENT_CORE_RE = re.compile(
    r"(?:\\d|\[0-9\])\+"
    r"(?:\(\?:\\\.\\d\+\)\??|\(\?:,\\d\{3\}\)\*(?:\(\?:\\\.\\d\+\)\??)?)?"
    r"[^%]{0,14}%"
)

# A digit (spelled `\d` or literal) followed by `\s*%`: `10\s*%\s*Owner`.
_PERCENT_LITERAL_RE = re.compile(r"(?:\\d|\d)\\s\*%")

# A percent-sign alternation spelled as a pair: `("%", r"percent\b")`,
# or as pattern text: `(?:%|percent\b)`.
_PERCENT_SIGN_ALT_RE = re.compile(
    r"(?:[\"']%[\"']\s*,\s*r?[\"']percent|\(\?:%\|percent)"
)

# The modules that own the two vocabularies, plus the sanctioned
# schema compositions built from the homed amount core.
_ALLOWED_PREFIXES = (
    "edgar_sec/engine/tables/numeric_cells.py",
    "edgar_sec/engine/tables/patterns.py",
    "edgar_sec/engine/forms/common/numbers.py",
    # The foundation fragment home under the layer-wall rule (b): the
    # minimal shared recognizer fragments (GROUPED_AMOUNT_CORE,
    # LOOSE_FIGURE_CLASS, FLOAT_SCALE_ALT) live there so layer-1 domain
    # consumers can compose them; their definition lines are homed, not
    # private copies.
    "edgar_sec/foundation/text/patterns.py",
)

# Sanctioned sites: a flagged shape that is not an amount/percent
# recognizer, exempted by file and content fragment, with its ruling.
_SANCTIONED_SITES = (
    # Beneficial-ownership loose-figure recognizers: no homed fragment
    # reproduces their verdicts ("1,23", "5.5" count), and the narrative
    # sibling diverges from numbers.py's surface on both sides — each
    # side holds members the other lacks (coordinator ruling,
    # 2026-11-15, Wave 2 priced stops F10 + narrative sibling).
    (
        "edgar_sec/engine/forms/beneficial_ownership/analysis/xml_audit.py",
        "_MULTI_CLASS_VALUE_RE",
    ),
    (
        "edgar_sec/engine/forms/beneficial_ownership/analysis/xml_audit.py",
        "_RE_NARRATIVE_NUMERIC",
    ),
    (
        "edgar_sec/engine/forms/beneficial_ownership/cover_value_diagnostics.py",
        "_NUMERIC_FOOTNOTE_RE",
    ),
    # Proposal numbers ("1.1", "2.3"), not amounts — the decimal core
    # trips on the shape; allowlisted, the money rule is not narrowed
    # (coordinator ruling, 2026-11-15).
    ("edgar_sec/engine/forms/form_npx/ascii_parser.py", "_PROPOSAL_NO_RE"),
    # Literal percent-mark membership data (a tuple tested with `in`),
    # not a recognizer definition (parent classification on the
    # evidence, coordinator ruling, 2026-11-15).
    (
        "edgar_sec/engine/tables/extraction/percentage_form.py",
        'in ("%", "percent")',
    ),
    # Ruling 3 (coordinator, 2026-11-15): the probe-priced verdict-change
    # sites stand as sanctioned divergences, transcribed from the census
    # register; a sweep reads zero unexpected findings against this list.
    ("edgar_sec/engine/document/page_markers/content_lines.py", "_has_amount_figures"),
    ("edgar_sec/engine/tables/extraction/grouping.py", "in thousands"),
    ("edgar_sec/engine/forms/form144/sale_parser.py", "_CURRENCY_CODE_PREFIX_RE"),
    ("edgar_sec/engine/forms/common/numbers.py", "_SCALED_NUMERIC_RE"),
    ("edgar_sec/engine/forms/form_424b/analysis.py", "_AMOUNT_RE"),
    ("edgar_sec/engine/forms/ownership/ascii_tables.py", "_RE_STANZA_AMT"),
    ("edgar_sec/engine/forms/ownership/table_common.py", "_COMPOSITE_UNDERLYING_RE"),
    ("edgar_sec/engine/document/page_markers/eligibility.py", "_RE_BARE_PERCENT"),
    (
        "edgar_sec/engine/forms/beneficial_ownership/cover_parser.py",
        "_RE_LABEL_PERCENT",
    ),
    (
        "edgar_sec/engine/forms/beneficial_ownership/item_subsections.py",
        "percentOfClass",
    ),
    (
        "edgar_sec/engine/forms/beneficial_ownership/item_subsections.py",
        "ownershipMoreThan5Percent",
    ),
    (
        "edgar_sec/engine/forms/beneficial_ownership/item_subsections.py",
        "_RE_PERCENT_OF_CLASS",
    ),
    ("edgar_sec/engine/forms/ownership/relationship_box.py", "_TEN_PERCENT_OWNER_RE"),
    ("edgar_sec/engine/tables/ascii_html/cell.py", "_UNIT_RE"),
    ("edgar_sec/foundation/text/grammar.py", "RE_WORD_TOKEN"),
    ("edgar_sec/engine/forms/form144/patterns.py", "BOX_3C_UNITS_RE"),
    ("edgar_sec/engine/forms/form_424b/analysis.py", "_SHARES_RE"),
)

_MONEY_HINT = (
    "compose the amount recognizer from NUMERIC_TOKEN_RE, GROUPED_AMOUNT_RE, "
    "DECIMAL_AMOUNT_RE, and DECIMAL_FIGURE_RE in "
    "edgar_sec.engine.tables.numeric_cells instead of defining a private copy"
)

_SCALE_HINT = (
    "use SCALE_PATTERNS, UNITS_LABEL_RE, and SCALE_SUFFIX_ALT from "
    "edgar_sec.engine.tables.patterns instead of a private scale vocabulary"
)

_PERCENT_HINT = (
    "use SCHEMA_PERCENT_RE, SCHEMA_LEADING_PERCENT_RE, and "
    "SCHEMA_CLOSING_PERCENT_RE from edgar_sec.engine.forms.common.numbers "
    "instead of defining a private copy"
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if any(path == site and fragment in line for site, fragment in _SANCTIONED_SITES):
        return None
    if (
        _MONEY_CORE_RE.search(line)
        or _MONEY_GROUPED_RE.search(line)
        or _MONEY_DECIMAL_RE.search(line)
    ):
        return finding(
            "money-patterns",
            path,
            number,
            "private money-amount recognizer outside its home",
            _MONEY_HINT,
        )
    if (
        _SCALE_PIPE_RE.search(line)
        or _SCALE_LIST_RE.search(line)
        or _SCALE_LABEL_RE.search(line)
    ):
        return finding(
            "money-patterns",
            path,
            number,
            "private scale vocabulary outside its home",
            _SCALE_HINT,
        )
    if (
        _PERCENT_CORE_RE.search(line)
        or _PERCENT_LITERAL_RE.search(line)
        or _PERCENT_SIGN_ALT_RE.search(line)
    ):
        return finding(
            "money-patterns",
            path,
            number,
            "private percent recognizer outside its home",
            _PERCENT_HINT,
        )
    return None


def scan_money_patterns() -> list[ScannerFinding]:
    """Flag private money, scale, and percent recognizers outside their homes."""
    return scan_text_rule(rule=_rule, prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="money-patterns",
    description=(
        "scan for private money-amount recognizers outside numeric_cells, "
        "private scale vocabularies outside tables/patterns, and private "
        "percent recognizers outside forms/common/numbers"
    ),
    run=scan_money_patterns,
)
