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

# The module that owns the date vocabulary.
_ALLOWED_PREFIXES = ("edgar_sec/foundation/text/dates.py",)

_HINT = (
    "use MONTH_PATTERN, MONTH_NAMES, and parse_date from "
    "edgar_sec.foundation.text.dates instead of a private month table"
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
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
    """Flag private month tables and hand-crafted date patterns."""
    return scan_text_rule(rule=_rule, prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="date-patterns",
    description="scan for private month tables and hand-crafted date patterns",
    run=scan_date_patterns,
)
