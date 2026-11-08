"""SEC full-index and daily-index file URL construction.

Quarterly full-index files and per-day daily-index files under the EDGAR
base; the flavour and extension vocabularies are pinned here.
"""

from __future__ import annotations

from datetime import date, datetime

from edgar_sec.domain.sec_urls import SEC_EDGAR_BASE


FULL_INDEX_FLAVOURS: tuple[str, ...] = (
    "master",
    "company",
    "form",
    "crawler",
    "xbrl",
)
DAILY_INDEX_FLAVOURS: tuple[str, ...] = ("master", "company", "form", "crawler")
_INDEX_EXTENSIONS: tuple[str, ...] = ("idx", "gz", "zip", "Z")


def _index_quarter(year: int, quarter: int) -> str:
    if not 1 <= int(quarter) <= 4:
        raise ValueError(f"quarter must be in 1..4, got {quarter!r}")
    return f"{int(year):04d}/QTR{int(quarter)}"


def full_index_url(
    year: int, quarter: int, flavour: str, extension: str = "idx"
) -> str:
    """Return one quarterly full-index file URL for a flavour.

    The crawler flavour is served only uncompressed; the other flavours
    are also served as ``gz`` / ``zip`` / ``Z`` archives of the same rows.
    """
    key = str(flavour).strip()
    if key not in FULL_INDEX_FLAVOURS:
        raise ValueError(f"unknown full-index flavour: {flavour!r}")
    if extension not in _INDEX_EXTENSIONS:
        raise ValueError(f"unknown index extension: {extension!r}")
    if key == "crawler" and extension != "idx":
        raise ValueError("the crawler index is served only as .idx")
    return (
        f"{SEC_EDGAR_BASE}/full-index/{_index_quarter(year, quarter)}/{key}.{extension}"
    )


def daily_index_url(day: date | str, flavour: str = "master") -> str:
    """Return one daily-index file URL; the quarter derives from ``day``.

    Daily files are per-day (``{flavour}.{YYYYMMDD}.idx``) and served only
    uncompressed, so the day is the builder's primary input.
    """
    key = str(flavour).strip()
    if key not in DAILY_INDEX_FLAVOURS:
        raise ValueError(f"unknown daily-index flavour: {flavour!r}")
    when = _coerce_index_day(day)
    quarter = (when.month - 1) // 3 + 1
    return (
        f"{SEC_EDGAR_BASE}/daily-index/{_index_quarter(when.year, quarter)}"
        f"/{key}.{when:%Y%m%d}.idx"
    )


def _coerce_index_day(day: date | str) -> date:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    text = str(day).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"day must be a date or ISO/YYYYMMDD string, got {day!r}")


__all__ = [
    "DAILY_INDEX_FLAVOURS",
    "FULL_INDEX_FLAVOURS",
    "daily_index_url",
    "full_index_url",
]
