"""ASCII layout and spacing evidence for page-label candidates."""

from __future__ import annotations

import re
from itertools import pairwise
from statistics import median

from defs.tables.tokens import ALL_CURRENCY_SYMBOLS, is_numeric_cell

from .models import PageCandidate

_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_NUMERIC_RE = re.compile(r"(?<![A-Za-z0-9])\d{1,4}(?![A-Za-z0-9])")
_DECIMAL_RE = re.compile(r"\d+\.\d{2,}")
_GROUPED_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_PROSE_END_RE = re.compile(r"[,;:]$")

_COLLAPSE_WS_RE = re.compile(r"\s+")
_ROMAN_NUMERAL_RE = re.compile(r"(?<![A-Za-z0-9])[ivxlcdm]{1,8}(?![A-Za-z0-9])")


def line_shape(line: str) -> dict[str, float | int | bool]:
    """Return reusable geometry features for one source line."""

    stripped = line.strip()
    leading = len(line) - len(line.lstrip())
    letters = [char for char in stripped if char.isalpha()]
    gaps = [len(match.group()) for match in _MULTI_SPACE_RE.finditer(line)]
    return {
        "all_caps": bool(letters) and all(char.isupper() for char in letters),
        "leading_column": leading,
        "right_edge": leading + len(stripped),
        "center_column": leading + len(stripped) / 2,
        "internal_gap": max(gaps, default=0),
        "prose_ending": bool(_PROSE_END_RE.search(stripped)),
    }


def candidate_template(text: str) -> str:
    """Normalize page values in a short label template."""

    normalized = _COLLAPSE_WS_RE.sub(" ", text.strip().casefold())
    normalized = _NUMERIC_RE.sub("#", normalized)
    return _ROMAN_NUMERAL_RE.sub("#", normalized)


def has_numeric_data_shape(line: str) -> bool:
    """Reject financial-looking lines from page-label promotion."""

    stripped = line.strip()
    if not stripped:
        return False
    if any(symbol in stripped for symbol in ALL_CURRENCY_SYMBOLS) or "%" in stripped:
        return True
    if _DECIMAL_RE.search(stripped) or _GROUPED_RE.search(stripped):
        return True
    numbers = _NUMERIC_RE.findall(stripped)
    if len(numbers) >= 2 and len(_MULTI_SPACE_RE.findall(line)) >= 1:
        return True
    return is_numeric_cell(stripped) and len(stripped) > 4


def cluster_is_table_like(candidates: list[PageCandidate]) -> bool:
    """Return whether candidate spacing resembles a dense table burst."""

    if len(candidates) < 3:
        return False
    if all(
        candidate.family == "inline_page_number" and "page" in candidate.text.casefold()
        for candidate in candidates
    ):
        return False
    ordered = sorted(candidates, key=lambda item: item.start_line)
    gaps = [right.start_line - left.start_line for left, right in pairwise(ordered)]
    if not gaps:
        return False
    gap_mean = sum(gaps) / len(gaps)
    gap_median = median(gaps)
    dense = sum(gap <= 3 for gap in gaps) / len(gaps)
    return gap_mean < 8 or dense >= 0.15 or gap_mean / gap_median < 0.5


__all__ = [
    "candidate_template",
    "cluster_is_table_like",
    "has_numeric_data_shape",
    "line_shape",
]
