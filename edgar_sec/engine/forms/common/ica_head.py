"""Shared ICA cover-head extraction for the fund report analyzers."""

from __future__ import annotations

import re
from typing import Any

from edgar_sec.engine.forms.common.entities import NAME_FORM_TOKENS
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity

FILE_NUMBER_RE = re.compile(
    r"Investment Company Act file number\s*:?\s*([0-9][0-9-]*)", re.IGNORECASE
)
_PERIOD_ENDED_RE = re.compile(
    r"(?:period|fiscal year) ended\s+([A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE
)
_DASHES_RE = re.compile(r"^[-_=.\s]+$")


def ica_cover_fields(lines: list[str]) -> dict[str, Any]:
    """Extract file number, registrant name, and period from a cover."""
    head_text = "\n".join(lines[:40])
    file_number = None
    match = FILE_NUMBER_RE.search(head_text)
    if match:
        file_number = match.group(1)
    period = None
    match = _PERIOD_ENDED_RE.search(head_text)
    if match:
        period = match.group(1)
    name = None
    for idx, line in enumerate(lines[:40]):
        if "(exact name of registrant" in line.lower():
            for back in range(idx - 1, max(idx - 4, -1), -1):
                candidate = lines[back].strip()
                if not candidate or _DASHES_RE.match(candidate):
                    continue
                if "<" in candidate or ">" in candidate:
                    continue
                if candidate.lower().startswith("investment company act"):
                    continue
                identity = parse_registrant_identity(candidate)
                if identity.name:
                    name = candidate
                break
            break
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
