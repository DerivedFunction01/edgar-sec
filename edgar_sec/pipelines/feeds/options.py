"""The one typed options model shared by the feeds CLI and operator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.feeds.models import STRUCTURED_FEED_SOURCES

from .paths import FeedsPaths, resolve_feeds_paths

Month = tuple[int, int]


def parse_month(text: str) -> Month:
    """Parse a ``YYYY-MM`` month reference; anything else is refused."""
    parts = str(text).strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"month must be YYYY-MM, got {text!r}")
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"month must be YYYY-MM, got {text!r}") from exc
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12, got {text!r}")
    return (year, month)


def format_month(month: Month) -> str:
    """Render a month reference as ``YYYY-MM``."""
    return f"{month[0]:04d}-{month[1]:02d}"


def iter_months(start: Month, end: Month) -> tuple[Month, ...]:
    """Every month from ``start`` to ``end`` inclusive, in order."""
    if start > end:
        raise ValueError(
            f"backfill start {format_month(start)} is after end {format_month(end)}"
        )
    months: list[Month] = []
    year, month = start
    while (year, month) <= end:
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tuple(months)


@dataclass(frozen=True, slots=True)
class FeedsOptions:
    """Everything one feeds command invocation needs."""

    artifacts_root: Path | None = None
    feeds: tuple[str, ...] = STRUCTURED_FEED_SOURCES
    start: Month | None = None
    end: Month | None = None
    branch: str = "main"

    def feeds_paths(self) -> FeedsPaths:
        """Feeds layout this invocation reads or writes."""
        return resolve_feeds_paths(self.artifacts_root)


def feeds_options(
    *,
    artifacts_root: str | Path | None = None,
    feeds: tuple[str, ...] = STRUCTURED_FEED_SOURCES,
    start: Month | None = None,
    end: Month | None = None,
    branch: str = "main",
) -> FeedsOptions:
    """Build feeds options from raw values."""
    return FeedsOptions(
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        feeds=tuple(feeds),
        start=start,
        end=end,
        branch=branch,
    )


__all__ = [
    "FeedsOptions",
    "Month",
    "feeds_options",
    "format_month",
    "iter_months",
    "parse_month",
]
