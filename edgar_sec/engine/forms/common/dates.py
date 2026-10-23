from __future__ import annotations

from collections.abc import Iterable

from edgar_sec.foundation.text.dates import (
    ParsedDate,
    parse_date,
)


def parse_schema_date(
    value: str | None,
    reference_year: int | None = None,
    *,
    allow_month_year: bool = False,
) -> ParsedDate | None:
    if not value:
        return None
    parsed = parse_date(value, reference_year=reference_year)
    if (
        parsed is None
        or parsed.ambiguous
        or (parsed.format_id.startswith("month_year") and not allow_month_year)
        or (reference_year is None and "2digit" in parsed.format_id)
    ):
        return None
    return parsed


def normalize_iso_date(
    value: str | None,
    reference_year: int | None = None,
    *,
    allow_month_year: bool = False,
) -> str | None:
    parsed = parse_schema_date(value, reference_year, allow_month_year=allow_month_year)
    return parsed.iso if parsed is not None else None


def reported_year(values: Iterable[str | None]) -> int | None:
    for value in values:
        parsed = parse_date(value) if value else None
        if (
            parsed is not None
            and not parsed.ambiguous
            and "2digit" not in parsed.format_id
        ):
            return parsed.components.year
    return None


def external_reference_year(
    report_date: str | None, filing_date: str | None
) -> int | None:
    return reported_year((report_date, filing_date))


def resolve_reference_year(
    report_date: str | None,
    filing_date: str | None,
    source_dates: Iterable[str | None] = (),
) -> int | None:
    return external_reference_year(report_date, filing_date) or reported_year(
        source_dates
    )


def format_iso_date(value: str | None, *, month_first: bool) -> str | None:
    parsed = parse_schema_date(value)
    if parsed is None or value != parsed.iso:
        return None
    if month_first:
        return (
            f"{parsed.components.month:02d}-{parsed.components.day:02d}-"
            f"{parsed.components.year:04d}"
        )
    return parsed.iso


__all__ = [
    "external_reference_year",
    "format_iso_date",
    "normalize_iso_date",
    "parse_schema_date",
    "reported_year",
    "resolve_reference_year",
]
