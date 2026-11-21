"""Scanner routing date handling through the shared date parser.

``foundation.text.dates`` owns month tables and SEC formats; a module keeping its own month
list yields a second, drifting answer to "what year is this fiscal period in".
"""

from __future__ import annotations

import re

from edgar_sec.foundation.text.dates import MONTH_PATTERN

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

# Two or more month literals in a sequence, e.g. ["jan", "feb"] or {"january": 1}
_MONTH_SEQUENCE_RE = re.compile(
    rf"[\"']\b(?:{MONTH_PATTERN})[.,]?[\"']\s*[,:]\s*[\"']\b(?:{MONTH_PATTERN})[.,]?[\"']",
    re.IGNORECASE,
)

# A raw month alternation inside a regex, e.g. (?:january|february|...)
_MONTH_REGEX_ALT_RE = re.compile(
    rf"\b(?:{MONTH_PATTERN})\s*\|\s*(?:{MONTH_PATTERN})\b",
    re.IGNORECASE,
)

# An ad-hoc date separator pattern, e.g. \d{1,2}/\d{1,2}/\d{2,4}. The quantifier
# accepts both {4} and {1,2}, so the canonical day/month case matches too.
_DATE_SEPARATOR_REGEX_RE = re.compile(
    r"\\d\{[1-4](?:,[1-4])?\}\s*[/\\-]\s*\\d\{[1-4](?:,[1-4])?\}"
    r"\s*[/\\-]\s*\\d\{[1-4](?:,[1-4])?\}"
)

# Names that signal a private month table.
_MONTH_VAR_RE = re.compile(
    r"\b(?:MONTH_NAMES|MONTH_MAP|MONTH_DICT|MONTH_LIST|MONTH_ALIASES)\s*="
)

# The two-digit tail of a four-digit year pattern, in its common spellings.
_YEAR_TAIL = r"(?:\\d\{2\}|\\d\\d|\[0-9\]\{2\}|\[0-9\]\[0-9\])"

# A narrowed year: a (19|20) century alternation, a 19xx|20xx year
# alternation, or the same pair as alternation-builder list items.
_NARROWED_CENTURY_RE = re.compile(r"\((?:\?:)?(?:19|20)\s*\|\s*(?:19|20)\)")
_NARROWED_YEAR_ALT_RE = re.compile(
    rf"(?:19|20){_YEAR_TAIL}\s*\|\s*(?:19|20){_YEAR_TAIL}"
)
_NARROWED_YEAR_LIST_RE = re.compile(
    rf"(?:19|20){_YEAR_TAIL}[\"']\s*,\s*(?:[A-Za-z]{{0,2}}[\"'])"
    rf"(?:19|20){_YEAR_TAIL}"
)

# The module that owns the date vocabulary.
_HOME = "edgar_sec/foundation/text/dates.py"

# The one sanctioned narrowing: the frozen Step 3 instrument's strict
# variant, homed in dates.py under exactly these two names. Any other
# narrowed-year definition — any other name, any other file — flags.
_SANCTIONED_NARROWED_RE = re.compile(
    r"^(?:STRICT_MONTH_PATTERN|STRICT_YEAR_TOKEN_PATTERN)\s*(?::[^=\n]+)?="
)

_HINT = (
    "use MONTH_PATTERN, MONTH_NAMES, and parse_date from "
    "edgar_sec.foundation.text.dates instead of a private month table"
)

_YEAR_HINT = (
    "use YEAR_TOKEN_PATTERN, YEAR_TOKEN_RE, and YEAR_TOKEN_SEARCH_RE from "
    "edgar_sec.foundation.text.dates instead of a narrowed year pattern; "
    "the foundation year patterns span the full 1900-9999 range"
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if (
        _NARROWED_CENTURY_RE.search(line)
        or _NARROWED_YEAR_ALT_RE.search(line)
        or _NARROWED_YEAR_LIST_RE.search(line)
    ):
        if path == _HOME and _SANCTIONED_NARROWED_RE.match(line):
            return None
        return finding(
            "date-patterns",
            path,
            number,
            "narrowed year alternation in a regex",
            _YEAR_HINT,
        )
    if path == _HOME:
        return None
    if _MONTH_VAR_RE.search(line):
        return finding("date-patterns", path, number, "private month table", _HINT)
    if _MONTH_SEQUENCE_RE.search(line):
        return finding(
            "date-patterns", path, number, "inline month sequence literal", _HINT
        )
    if _MONTH_REGEX_ALT_RE.search(line):
        return finding(
            "date-patterns",
            path,
            number,
            "hand-crafted month alternation in a regex",
            _HINT,
        )
    if _DATE_SEPARATOR_REGEX_RE.search(line):
        return finding(
            "date-patterns",
            path,
            number,
            "hand-crafted date separator pattern",
            f"{_HINT}; the ordered SEC formats live in SEC_DATE_FORMATS",
        )
    return None


def scan_date_patterns() -> list[ScannerFinding]:
    """Flag private month tables, hand-crafted date patterns, narrowed years."""
    return scan_text_rule(rule=_rule)


SCANNER = Scanner(
    name="date-patterns",
    description=(
        "scan for private month tables, hand-crafted date patterns, "
        "and narrowed-year patterns"
    ),
    run=scan_date_patterns,
)
