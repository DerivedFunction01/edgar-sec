"""Period keys over gate text lines.

The extraction evidence gates' shared line-level period vocabulary.
"""

from __future__ import annotations

from edgar_sec.foundation.text.date_patterns import (
    MONTH_NAME_WORD_RE,
    NUMERIC_DATE_RE,
    YEAR_TOKEN_SEARCH_RE,
)


def priced_years(line: str) -> list[str]:
    """The line's year tokens, the foundation's full-range shape."""
    return YEAR_TOKEN_SEARCH_RE.findall(line)


def numeric_dates(line: str) -> list[str]:
    """The line's numeric dates in the priced shape (slash only)."""
    return [
        match.group(0)
        for match in NUMERIC_DATE_RE.finditer(line)
        if len(match.group(0).split("/")) == 3
    ]


def period_keys(line: str) -> set:
    """Distinct period keys of one line: years, months, dates."""
    keys = set()
    for year in priced_years(line):
        keys.add(("y", year))
    for month in MONTH_NAME_WORD_RE.findall(line):
        keys.add(("m", month.lower()))
    for date in numeric_dates(line):
        keys.add(("d", date))
    return keys


def starts_with_numeric_date(stripped: str) -> bool:
    """A stripped line opening with a slash-separated numeric date."""
    date = NUMERIC_DATE_RE.match(stripped)
    return date is not None and len(date.group(0).split("/")) == 3


def starts_with_period(line: str) -> bool:
    """A bare line opening with a month, a year, or a date."""
    stripped = line.strip(" |")
    if MONTH_NAME_WORD_RE.match(stripped):
        return True
    if YEAR_TOKEN_SEARCH_RE.match(stripped):
        return True
    return starts_with_numeric_date(stripped)
