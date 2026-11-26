"""Date parsing for SEC filings: the parse core."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from edgar_sec.foundation.text.date_formats import (
    ALL_SEC_DATE_FORMATS,
    SEC_DATE_FORMATS,
    DateFormat,
    _ALL_SEC_DATE_FORMATS_ORDERED,
)
from edgar_sec.foundation.text.date_patterns import (
    MONTH_RE,
    NUMERIC_DATE_RE,
    NUMERIC_YEAR_RE,
    ORDINAL_SUFFIX_RE,
    month_name_to_index,
)
from edgar_sec.foundation.text.date_years import (
    expand_2digit_year,
    is_valid_year,
    is_year_token,
)
from edgar_sec.foundation.text.patterns import RE_WHITESPACE


@dataclass(frozen=True, slots=True)
class DateComponents:
    year: int
    month: int
    day: int

    def to_iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def valid(self) -> bool:
        try:
            date(self.year, self.month, self.day)
            return True
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class ParsedDate:
    format_id: str
    source: str
    components: DateComponents
    ambiguous: bool = False

    @property
    def iso(self) -> str:
        return self.components.to_iso()

    @property
    def display(self) -> str:
        return self.source


def _parse_date_with_formats(
    normalized: str,
    ordered: Sequence[DateFormat],
    reference_year: int | None,
) -> ParsedDate | None:
    for fmt in ordered:
        match = fmt.pattern.search(normalized)
        if not match:
            continue
        group_dict = match.groupdict()
        year_str = group_dict.get("year")
        month_str = group_dict.get("month")
        day_str = group_dict.get("day")
        if not (year_str and month_str):
            continue
        year = int(year_str)
        if len(year_str) <= 2:
            if reference_year is None:
                continue
            year = expand_2digit_year(year, reference_year=reference_year)
        if not is_year_token(str(year)):
            continue
        if reference_year is not None and not is_valid_year(year, reference_year):
            continue
        month = month_name_to_index(month_str)
        if month is None:
            try:
                month = int(month_str)
            except ValueError:
                continue
            if not 1 <= month <= 12:
                continue
        day = int(ORDINAL_SUFFIX_RE.sub("", day_str)) if day_str else 1
        if not 1 <= day <= 31:
            continue
        components = DateComponents(year=year, month=month, day=day)
        if not components.valid():
            continue
        source = match.group(0).strip()
        return ParsedDate(format_id=fmt.id, source=source, components=components)
    return None


@lru_cache(maxsize=4096)
def _parse_date_default_cached(normalized: str) -> ParsedDate | None:
    return _parse_date_with_formats(normalized, _ALL_SEC_DATE_FORMATS_ORDERED, None)


def parse_date(
    text: str,
    *,
    formats: Sequence[DateFormat] = ALL_SEC_DATE_FORMATS,
    reference_year: int | None = None,
) -> ParsedDate | None:
    """Parse a complete date string against known formats."""
    normalized = RE_WHITESPACE.sub(" ", text).strip()
    if not normalized:
        return None
    if formats is ALL_SEC_DATE_FORMATS and reference_year is None:
        return _parse_date_default_cached(normalized)
    ordered = (
        _ALL_SEC_DATE_FORMATS_ORDERED
        if formats is ALL_SEC_DATE_FORMATS
        else sorted(formats, key=lambda fmt: fmt.priority, reverse=True)
    )
    return _parse_date_with_formats(normalized, ordered, reference_year)


def contains_date(text: str, *, include_partial: bool = False) -> bool:
    """Return whether text contains a recognizable SEC date."""
    normalized = RE_WHITESPACE.sub(" ", text).strip()
    if not normalized:
        return False
    if any(fmt.pattern.search(normalized) for fmt in SEC_DATE_FORMATS):
        return True
    if include_partial:
        return bool(
            NUMERIC_DATE_RE.search(normalized)
            or (MONTH_RE.search(normalized) and NUMERIC_YEAR_RE.search(normalized))
        )
    return False


__all__ = [
    "DateComponents",
    "ParsedDate",
    "contains_date",
    "parse_date",
]
