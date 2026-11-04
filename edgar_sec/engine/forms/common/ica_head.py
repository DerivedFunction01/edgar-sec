"""Shared ICA cover-head extraction for the fund report analyzers."""

from __future__ import annotations

import re
from typing import Any

from edgar_sec.engine.forms.common.entities import NAME_FORM_TOKENS
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import MONTH_PATTERN, NUMERIC_DATE_RE

_FILE_CAPTIONS: tuple[str, ...] = (
    "investment company act file number",
    "file number",
    "file no.",
    "file no",
)
FILE_NUMBER_RE = re.compile(
    rf"(?:{build_alternation(list(_FILE_CAPTIONS), auto_escape=True)})"
    r"\s*:?\s*([0-9][0-9\u2011\- ]*[0-9]|[0-9])",
    re.IGNORECASE,
)
_NAMED_DATE_RE = re.compile(rf"(?:{MONTH_PATTERN}) \d{{1,2}}, \d{{4}}", re.IGNORECASE)
_PERIOD_ENDED_RE = re.compile(r"(?:period|fiscal year) ended\s+", re.IGNORECASE)
_REPORTING_PERIOD_RE = re.compile(r"date of reporting period\s*:?\s*", re.IGNORECASE)
_DASHES_RE = re.compile(r"^[-_=.\s]+$")
_NAME_LOOKBACK_LINES = 12


def _normalize_file_number(raw: str) -> str:
    return raw.replace("\u2011", "-").replace(" ", "")


def _date_value_at(text: str, start: int, *, last: bool = False) -> str | None:
    window = text[start : start + 48]
    matches = [
        match
        for pattern in (_NAMED_DATE_RE, NUMERIC_DATE_RE)
        for match in pattern.finditer(window)
    ]
    if not matches:
        return None
    chosen = (
        max(matches, key=lambda match: match.start())
        if last
        else min(matches, key=lambda match: match.start())
    )
    return chosen.group(0)


def _report_period(head_lines: list[str]) -> str | None:
    """The reporting-period date: the facing sheet's own caption first
    (a caption naming a range resolves to its last date, the period
    end), then an "ended"-phrased mention in the head.
    """
    for line in head_lines:
        caption = _REPORTING_PERIOD_RE.search(line)
        if caption:
            value = _date_value_at(line, caption.end(), last=True)
            if value:
                return value
    head_text = "\n".join(head_lines)
    ended = _PERIOD_ENDED_RE.search(head_text)
    if ended:
        return _date_value_at(head_text, ended.end())
    return None


def _registrant_name(lines: list[str]) -> str | None:
    """The name printed above the "(exact name of registrant" caption;
    blank-doubled renders interleave furniture lines, so the look-back
    skips them instead of counting raw lines.
    """
    for idx, line in enumerate(lines[:40]):
        if "(exact name of registrant" not in line.lower():
            continue
        for back in range(idx - 1, max(idx - _NAME_LOOKBACK_LINES - 1, -1), -1):
            candidate = lines[back].strip()
            if not candidate or _DASHES_RE.match(candidate):
                continue
            if "<" in candidate or ">" in candidate:
                continue
            if candidate.lower().startswith("investment company act"):
                continue
            if FILE_NUMBER_RE.search(candidate):
                continue
            identity = parse_registrant_identity(candidate)
            return candidate if identity.name else None
        return None
    return None


def ica_cover_fields(lines: list[str]) -> dict[str, Any]:
    """Extract file number, registrant name, and period from a cover."""
    head_text = "\n".join(lines[:40])
    file_number = None
    match = FILE_NUMBER_RE.search(head_text)
    if match:
        file_number = _normalize_file_number(match.group(1))
    period = _report_period(lines[:40])
    name = _registrant_name(lines)
    if name is None:
        for line in lines[:12]:
            stripped = line.strip()
            if not 3 <= len(stripped) <= 80 or not stripped[0].isalpha():
                continue
            lowered = stripped.lower()
            if any(token in lowered for token in NAME_FORM_TOKENS):
                identity = parse_registrant_identity(stripped)
                if identity.name:
                    name = stripped
                    break
    return {
        "registrant_name": name,
        "file_number": file_number,
        "report_period": period,
    }


__all__ = ["FILE_NUMBER_RE", "ica_cover_fields"]
