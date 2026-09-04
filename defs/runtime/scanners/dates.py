"""Policy scanner detecting ad-hoc date parsing, month lists, and date regexes."""

from __future__ import annotations

import os
import re

from defs.regex import build_alternation
from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = (
    r"(?i)january|february|march|april|june|july|august|september|october|november|december"
    r"|\b(?:jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b"
    r"|\\d\{[1-4]\}\s*[/\\-]\s*\\d\{[1-4]\}"
    r"|month_name|month_map|month_dict|month_list"
)

# 1. Month names / abbreviations in sequence (lists, tuples, dicts, sets)
_MONTH_TOKENS = [
    r"january",
    r"february",
    r"march",
    r"april",
    r"may",
    r"june",
    r"july",
    r"august",
    r"september",
    r"october",
    r"november",
    r"december",
    r"jan",
    r"feb",
    r"mar",
    r"apr",
    r"jun",
    r"jul",
    r"aug",
    r"sep",
    r"sept",
    r"oct",
    r"nov",
    r"dec",
]
_MONTH_ALT = build_alternation(_MONTH_TOKENS, auto_escape=True)

# Matches 2+ month literals in a sequence, e.g. ["jan", "feb"] or {"january": 1, ...}
_MONTH_SEQUENCE_RE = re.compile(
    rf"""(?i)["']\b(?:{_MONTH_ALT})[.,]?["']\s*[,:]\s*["']\b(?:{_MONTH_ALT})[.,]?["']"""
)

# 2. Raw month alternations in regexes, e.g. (?:january|february|...) or jan|feb|mar
_MONTH_REGEX_ALT_RE = re.compile(
    rf"""(?i)\b(?:{_MONTH_ALT})\s*\|\s*(?:{_MONTH_ALT})\b"""
)

# 3. Ad-hoc date separator regexes, e.g. \d{1,2}/\d{1,2}/\d{2,4} or \d{4}-\d{2}-\d{2}
_DATE_SEPARATOR_REGEX_RE = re.compile(
    r"""\\d\{[1-4]\}\s*[/\\-]\s*\\d\{[1-4]\}\s*[/\\-]\s*\\d\{[1-4]\}"""
)

# 4. Month dictionary / variable name indicators
_MONTH_VAR_RE = re.compile(
    r"""\b(?:MONTH_NAMES|MONTH_MAP|MONTH_DICT|MONTH_LIST|MONTH_ALIASES)\s*="""
)

_ALLOWED_PATHS = (
    "defs/text/dates.py",
    "defs/runtime/scanners/",
    "old-webpage.py",
    "old-webpage.py.txt",
    "roadmap/",
    "scratch/",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    stripped = text.strip()
    if stripped.startswith(("#", "//", "/*", "*")):
        return []

    findings: list[ScannerFinding] = []
    if (
        _MONTH_SEQUENCE_RE.search(text)
        or _MONTH_REGEX_ALT_RE.search(text)
        or _DATE_SEPARATOR_REGEX_RE.search(text)
        or _MONTH_VAR_RE.search(text)
    ):
        findings.append(
            ScannerFinding(
                scanner="date-patterns",
                source=source,
                path=path,
                line=line_number,
                message="ad-hoc month list, month regex alternation, or date regex literal",
                hint="import MONTH_NAMES, MONTH_ALIASES, MONTH_RE, TABLE_YEAR_RE, or parse_date from defs.text.dates instead of recreating date parsing",
            )
        )
    return findings


def scan_date_patterns(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for ad-hoc month lists and date regexes."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        candidate_flags=re.IGNORECASE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_date_patterns"]
