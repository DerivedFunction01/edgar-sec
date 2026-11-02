from __future__ import annotations

import re
from collections.abc import Iterable

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    DateComponents,
    ParsedDate,
    parse_date,
)

_RE_CALENDAR_YEAR = re.compile(
    r"(?i)^\s*(?:calendar\s+year|year\s+ended(?:\s+december\s+31,?)?)\s*(\d{4})\s*$"
)
_ORDINAL_SUFFIX_ALT = build_alternation(
    ("st", "nd", "rd", "th"), auto_escape=True, compact=True
)
_RE_DAY_OF_MONTH = re.compile(
    rf"(?i)\b(\d{{1,2}})(?:{_ORDINAL_SUFFIX_ALT})?\s+day\s+of\s+([A-Za-z]+),?\s+(\d{{4}})\b"
)


def parse_schema_date(
    value: str | None,
    reference_year: int | None = None,
    *,
    allow_month_year: bool = False,
) -> ParsedDate | None:
    if not value:
        return None
    if m := _RE_CALENDAR_YEAR.match(value.strip()):
        year = int(m.group(1))
        return ParsedDate(
            format_id="calendar_year",
            source=value,
            components=DateComponents(year=year, month=12, day=31),
        )
    parsed = parse_date(value, reference_year=reference_year)
    if parsed is None or (
        parsed.format_id.startswith("month_year") and not allow_month_year
    ):
        if m := _RE_DAY_OF_MONTH.search(value):
            parsed = parse_date(
                f"{m.group(2)} {m.group(1)}, {m.group(3)}",
                reference_year=reference_year,
            )
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


def is_valid_schema_date_lexeme(
    iso_value: str | None,
    raw_value: str | None,
    *,
    month_first: bool,
) -> bool:
    """Validate raw date matches ISO date under MDY or YMD order."""
    if not iso_value or not raw_value:
        return False
    formatted = format_iso_date(iso_value, month_first=month_first)
    if formatted is None:
        return False
    normalized_raw = raw_value.strip().replace("/", "-")
    if normalized_raw == formatted:
        return True
    if month_first and (parsed := parse_schema_date(raw_value)):
        if parsed.iso == iso_value:
            expected = f"{parsed.components.month}-{parsed.components.day}-{parsed.components.year:04d}"
            return normalized_raw == expected
    return False


__all__ = [
    "external_reference_year",
    "format_iso_date",
    "is_valid_schema_date_lexeme",
    "normalize_iso_date",
    "parse_schema_date",
    "reported_year",
    "resolve_reference_year",
]
