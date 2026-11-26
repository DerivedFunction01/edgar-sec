"""Year validation and extraction for SEC filing dates."""

from __future__ import annotations

from edgar_sec.foundation.text.date_patterns import (
    NUMERIC_YEAR_RE,
    TABLE_YEAR_RE,
    YEAR_TOKEN_RE,
)


REFERENCE_YEAR_LOOKBACK = 80
REFERENCE_YEAR_FORWARD = 50


def reference_year_window(reference_year: int) -> tuple[int, int]:
    """Return the validity window anchored on a known reference year."""
    return (
        reference_year - REFERENCE_YEAR_LOOKBACK,
        reference_year + REFERENCE_YEAR_FORWARD,
    )


def is_valid_year(year: int, reference_year: int) -> bool:
    """Return whether a year falls in the reference year's window."""
    low, high = reference_year_window(reference_year)
    return low <= year <= high


def is_year_token(value: str) -> bool:
    """Return whether a string is a standalone 4-digit year token."""
    v = value.strip()
    return len(v) == 4 and v.isdigit() and YEAR_TOKEN_RE.match(v) is not None


def expand_2digit_year(
    year: int,
    *,
    reference_year: int,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> int:
    """Expand a 1- or 2-digit year using a dynamic rolling window relative to a reference year."""
    if year >= 100:
        return year
    anchor = reference_year
    if century_pivot is not None:
        current_century = (anchor // 100) * 100
        prev_century = current_century - 100
        return (
            (current_century + year) if year < century_pivot else (prev_century + year)
        )

    base_year = anchor - lookback_years
    base_century = (base_year // 100) * 100
    candidate = base_century + year
    if candidate < base_year:
        candidate += 100
    return candidate


def parse_year_token(
    value: str,
    *,
    reference_year: int,
) -> int | None:
    """Parse a standalone numeric year token valid for the reference year."""
    match = YEAR_TOKEN_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if not is_valid_year(year, reference_year):
        return None
    return year


def extract_years(
    text: str,
    *,
    reference_year: int,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> list[int]:
    """Extract validated year integers from header-style text."""
    years: list[int] = []
    for match in TABLE_YEAR_RE.finditer(text):
        raw = next((g for g in match.groups() if g is not None), None)
        if not raw:
            continue
        year = int(raw)
        if len(raw) <= 2:
            year = expand_2digit_year(
                year,
                reference_year=reference_year,
                lookback_years=lookback_years,
                century_pivot=century_pivot,
            )
        if is_valid_year(year, reference_year):
            years.append(year)
    return years


def parse_numeric_year(
    value: str,
    *,
    reference_year: int,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> int | None:
    """Parse a one- to four-digit numeric year token with century expansion."""
    match = NUMERIC_YEAR_RE.search(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year = expand_2digit_year(
            year,
            reference_year=reference_year,
            lookback_years=lookback_years,
            century_pivot=century_pivot,
        )
    if not is_valid_year(year, reference_year):
        return None
    return year


__all__ = [
    "REFERENCE_YEAR_FORWARD",
    "REFERENCE_YEAR_LOOKBACK",
    "expand_2digit_year",
    "extract_years",
    "is_valid_year",
    "is_year_token",
    "parse_numeric_year",
    "parse_year_token",
    "reference_year_window",
]
