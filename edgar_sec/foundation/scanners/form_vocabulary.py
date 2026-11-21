"""Policy scanner banning private form vocabulary regexes outside canonical owners.

CUSIP regexes belong in common/entities, unit suffixes in common/numbers, and table
markup parsing in legacy ASCII unwrappers.
"""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import finding, matches_allowed, scan_text_rule

_CUSIP_PATTERN_RE = re.compile(r"\[[0-9A-Za-z*@#\-_]+\]\{[89]")
_TABLE_TAG_RE = re.compile(r"</?\??(?:table|tr|td|th)\b", re.IGNORECASE)
_UNIT_SUFFIX_RE = re.compile(
    r"['\"]\s*(?:shares of common(?: stock)?|common shares)\s*['\"]",
    re.IGNORECASE,
)

_ALLOWED_CUSIP_PREFIXES = ("edgar_sec/engine/forms/common/entities.py",)
_ALLOWED_UNIT_PREFIXES = ("edgar_sec/engine/forms/common/numbers.py",)
_ALLOWED_TABLE_PREFIXES = (
    "edgar_sec/engine/forms/cover/tables/",
    "edgar_sec/engine/forms/cover/toc/",
    "edgar_sec/engine/forms/cover/boundary/",
    "edgar_sec/engine/forms/cover/checkmarks/",
    "edgar_sec/engine/forms/ownership/ascii_tables.py",
    "edgar_sec/engine/forms/ownership/ascii_shape.py",
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if not path.startswith("edgar_sec/engine/forms/"):
        return None
    if _CUSIP_PATTERN_RE.search(line) and not matches_allowed(
        path, _ALLOWED_CUSIP_PREFIXES
    ):
        return finding(
            "form-vocabulary",
            path,
            number,
            "private CUSIP regex structure",
            "import is_valid_cusip, parse_cusip, or CUSIP_RE from common.entities",
        )
    if _TABLE_TAG_RE.search(line) and not matches_allowed(
        path, _ALLOWED_TABLE_PREFIXES
    ):
        return finding(
            "form-vocabulary",
            path,
            number,
            "DOM or HTML table markup regex",
            "operate on normalized text frames and use strip_markup_tags from common.tables",
        )
    if _UNIT_SUFFIX_RE.search(line) and not matches_allowed(
        path, _ALLOWED_UNIT_PREFIXES
    ):
        return finding(
            "form-vocabulary",
            path,
            number,
            "duplicate unit suffix literal",
            "use normalize_integer_stripping_units or _SCHEMA_UNIT_SUFFIX_ALT from common.numbers",
        )
    return None


def scan_form_vocabulary() -> list[ScannerFinding]:
    """Flag private CUSIP regexes, DOM table regexes, and duplicate unit suffixes."""
    return scan_text_rule(rule=_rule)


SCANNER = Scanner(
    name="form-vocabulary",
    description="flags private form vocabulary regexes and DOM markup checks outside common owners",
    run=scan_form_vocabulary,
)
