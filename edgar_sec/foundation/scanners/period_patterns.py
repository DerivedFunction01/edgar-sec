"""Scanner routing period, total, whitespace, and table-tag literals home.
Flags private copies outside their homes (foundation/text; typed_rows for
totals). Allows homed imports/compositions, the table-tag migration sources,
the joint date-capture caption shape, and the regex builder's space run.
"""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import Rule, finding, scan_text_rule

# A period-phrase recognizer spelled as pattern text: the ended alternation,
# a single ended phrase, or a reporting-period caption shape.
_PERIOD_RE = re.compile(
    r"(?:\(\?:period\|fiscal year(?:\|quarter)?\) ended"
    r"|period ended|fiscal year ended|quarter ended"
    r"|date of reporting period|reporting period[\s\\:]"
    r"|distribution period)",
    re.IGNORECASE,
)

# A full month-name date capture riding a period-ended shape: the jointly
# owned caption form, exempt from the period line.
_DATE_CAPTURE_RE = re.compile(r"\[A-Z\]\[a-z\]\+ \\d\{1,2\}, \\d\{4\}")

# The total-row recognizer spelled as pattern text: `^\s*total\b` and kin.
_TOTAL_RE = re.compile(r"\^\\s[*+]total\\b")

# A whitespace-collapse literal spelled as the whole compile argument.
_WHITESPACE_LITERAL = (
    r"\\s\+|\[ \\t\]\+|\[ \\t\]\{2,\}|\\s\{2,\}|\\t\+\|\\s\{2,\}|\\n\{3,\}"
)
_WHITESPACE_RE = re.compile(
    rf"re\.compile\(\s*r?f?\"(?:{_WHITESPACE_LITERAL})\""
    rf"|re\.compile\(\s*r?f?'(?:{_WHITESPACE_LITERAL})'"
)

# A table-tag recognizer spelled inside a compile call.
_TABLE_TAG_RE = re.compile(
    r"re\.compile\(.*<(?:table|TABLE)\b|re\.compile\(.*</?(?:table|TABLE)>"
)

# Sanctioned divergence (coordinator ruling, 2026-11-15), transcribed from
# the census register: the 11-K joint period-caption x month-name capture;
# every home composition widens its anchor or duplicates the date capture.
_SANCTIONED_SITES = (
    ("edgar_sec/engine/forms/form_11k/analysis.py", "_FISCAL_YEAR_END_RE"),
    ("edgar_sec/engine/forms/ownership/ascii_shape.py", "_TABLE_TAG_RE"),
    ("edgar_sec/engine/forms/ownership/ascii_tables.py", "_TABLE_TAG_RE"),
    ("edgar_sec/engine/forms/form_sd/analysis.py", "rule 13q-1"),
    ("edgar_sec/engine/forms/form_abs_reports/analysis.py", "distribution period from"),
    (
        "edgar_sec/engine/forms/form_abs_reports/analysis.py",
        "reporting period\\s+(?:from\\s+)?",
    ),
    ("edgar_sec/engine/forms/form_rega/analysis.py", "semiannual period ended"),
)

_PERIOD_HOME = "edgar_sec/foundation/text/dates.py"
_TOTAL_HOME = "edgar_sec/engine/tables/extraction/typed_rows.py"
_WHITESPACE_HOMES = (
    "edgar_sec/foundation/text/patterns.py",
    "edgar_sec/foundation/text/normalize.py",
    "edgar_sec/foundation/regex/builder.py",
)
_TABLE_HOMES = (
    "edgar_sec/foundation/text/patterns.py",
    "edgar_sec/engine/tables/patterns.py",
    "edgar_sec/engine/tables/protection/tags.py",
)

_PERIOD_HINT = (
    "compose the period phrase from PERIOD_ENDED_PAT, PERIOD_ENDED_RE, and the "
    "REPORTING_PERIOD recognizers in edgar_sec.foundation.text.dates instead "
    "of defining a private copy"
)

_TOTAL_HINT = (
    "use TOTAL_ROW_RE from edgar_sec.engine.tables.extraction.typed_rows "
    "instead of defining a private copy"
)

_WHITESPACE_HINT = (
    "use RE_WHITESPACE, RE_WHITESPACE_GAP, RE_WHITESPACE_SPLIT, and "
    "RE_COLUMN_GAP from edgar_sec.foundation.text.patterns, or the collapse "
    "functions in edgar_sec.foundation.text.normalize, instead of defining "
    "a private copy"
)

_TABLE_HINT = (
    "use RE_TABLE_OPEN, RE_TABLE_CLOSE, and RE_TABLE_SPAN from "
    "edgar_sec.foundation.text.patterns instead of defining a private copy"
)


_DEF_START_RE = re.compile(r"^\s*[A-Za-z_]\w*\s*(?::[^=\n]+)?=(?!=)")


class _DefinitionLines:
    """The nearest preceding definition line in each scanned file.

    Sanctions name a definition, so a flagged core spelled on a
    continuation line is tested against its definition's line too.
    """

    def __init__(self) -> None:
        self._path = ""
        self._definition = ""

    def current(self, path: str, line: str) -> str:
        if path != self._path:
            self._path = path
            self._definition = ""
        if _DEF_START_RE.match(line):
            self._definition = line
        elif line.strip() and not line[:1].isspace():
            self._definition = ""
        return self._definition


def _rule(
    path: str, number: int, line: str, definition: str = ""
) -> ScannerFinding | None:
    if any(
        path == site_path and (fragment in line or fragment in definition)
        for site_path, fragment in _SANCTIONED_SITES
    ):
        return None
    if path != _PERIOD_HOME and _PERIOD_RE.search(line):
        stripped = line.lstrip()
        is_pattern_text = (
            "re.compile" in line
            or '= r"' in line
            or "= rf" in line
            or "= r'" in line
            or stripped.startswith('r"')
            or stripped.startswith("r'")
            or stripped.startswith('rf"')
        )
        if is_pattern_text:
            if not _DATE_CAPTURE_RE.search(line):
                return finding(
                    "period-patterns",
                    path,
                    number,
                    "private period-phrase recognizer outside its home",
                    _PERIOD_HINT,
                )
    if path != _TOTAL_HOME and _TOTAL_RE.search(line) and "re.compile" in line:
        return finding(
            "total-patterns",
            path,
            number,
            "private total-row recognizer outside its home",
            _TOTAL_HINT,
        )
    # A literal feeding .join( is a construction separator, not a
    # private collapse recognizer.
    whitespace = _WHITESPACE_RE.search(line)
    if (
        path not in _WHITESPACE_HOMES
        and whitespace is not None
        and not line[whitespace.end() :].startswith(".join(")
    ):
        return finding(
            "whitespace-patterns",
            path,
            number,
            "private whitespace-collapse literal outside its home",
            _WHITESPACE_HINT,
        )
    if path not in _TABLE_HOMES and _TABLE_TAG_RE.search(line):
        return finding(
            "table-tag-patterns",
            path,
            number,
            "private table-tag recognizer outside its home",
            _TABLE_HINT,
        )
    return None


def _make_rule() -> Rule:
    definitions = _DefinitionLines()

    def rule(path: str, number: int, line: str) -> ScannerFinding | None:
        return _rule(path, number, line, definitions.current(path, line))

    return rule


def scan_period_patterns() -> list[ScannerFinding]:
    """Flag private period, total, whitespace, and table-tag recognizers."""
    return scan_text_rule(rule=_make_rule())


SCANNER = Scanner(
    name="period-patterns",
    description=(
        "scan for private period-phrase recognizers outside text/dates, "
        "private total-row recognizers outside extraction/typed_rows, "
        "private whitespace-collapse literals outside text/patterns and "
        "text/normalize, and private table-tag recognizers outside "
        "text/patterns"
    ),
    run=scan_period_patterns,
)
