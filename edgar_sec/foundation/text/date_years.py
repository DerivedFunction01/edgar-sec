"""Year validation and extraction for SEC filing dates."""

from __future__ import annotations

from datetime import UTC, datetime

from edgar_sec.foundation.text.date_patterns import (
    NUMERIC_YEAR_RE,
    TABLE_YEAR_RE,
    YEAR_TOKEN_RE,
)


DEFAULT_YEAR_UPPER_BOUND = max(2100, datetime.now(UTC).year + 50)


YEAR_RANGE = (1900, DEFAULT_YEAR_UPPER_BOUND)


def is_valid_year(year: int, valid_range: tuple[int, int] = YEAR_RANGE) -> bool:
    """Return whether an integer year falls within the valid range."""
    return valid_range[0] <= year <= valid_range[1]


def is_year_token(value: str, valid_range: tuple[int, int] = YEAR_RANGE) -> bool:
    """Return whether a string represents a standalone 4-digit calendar year."""
    v = value.strip()
    return (
        len(v) == 4 and v.isdigit() and is_valid_year(int(v), valid_range=valid_range)
    )


def expand_2digit_year(
    year: int,
    *,
    reference_year: int | None = None,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> int:
    """Expand a 1- or 2-digit year using a dynamic rolling window relative to a reference year."""
    if year >= 100:
        return year
    anchor = datetime.now(UTC).year if reference_year is None else reference_year
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
    valid_range: tuple[int, int] = YEAR_RANGE,
) -> int | None:
    """Parse a standalone numeric year token within the valid range."""
    match = YEAR_TOKEN_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if not is_valid_year(year, valid_range=valid_range):
        return None
    return year


def extract_years(
    text: str,
    *,
    reference_year: int | None = None,
    valid_range: tuple[int, int] = YEAR_RANGE,
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
        if is_valid_year(year, valid_range=valid_range):
            years.append(year)
    return years


def parse_numeric_year(
    value: str,
    *,
    reference_year: int | None = None,
    valid_range: tuple[int, int] = YEAR_RANGE,
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
    if not is_valid_year(year, valid_range=valid_range):
        return None
    return year


__all__ = [
    "DEFAULT_YEAR_UPPER_BOUND",
    "YEAR_RANGE",
    "expand_2digit_year",
    "extract_years",
    "is_valid_year",
    "is_year_token",
    "parse_numeric_year",
    "parse_year_token",
]
