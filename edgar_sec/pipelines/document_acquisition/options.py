"""The typed options model for the Feed-archives ingest command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .paths import AcquisitionPaths, resolve_acquisition_paths

FEED_ARCHIVES_BRANCH = "feed_archives"


def parse_day(text: str) -> date:
    """Parse an ISO ``YYYY-MM-DD`` day reference; anything else is refused."""
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError as exc:
        raise ValueError(f"day must be YYYY-MM-DD, got {text!r}") from exc


def iter_days(start: date, end: date) -> tuple[date, ...]:
    """Every day from ``start`` to ``end`` inclusive, in order."""
    if start > end:
        raise ValueError(f"range start {start} is after end {end}")
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


@dataclass(frozen=True, slots=True)
class FeedIngestOptions:
    """Everything one Feed-archives ingest invocation needs."""

    start: date
    end: date
    artifacts_root: Path | None = None
    branch: str = FEED_ARCHIVES_BRANCH
    json_output: bool = False

    def acquisition_paths(self) -> AcquisitionPaths:
        """Acquisition layout this invocation reads or writes."""
        return resolve_acquisition_paths(artifacts_root=self.artifacts_root)


def feed_ingest_options(
    *,
    start: date,
    end: date,
    artifacts_root: str | Path | None = None,
    branch: str = FEED_ARCHIVES_BRANCH,
    json_output: bool = False,
) -> FeedIngestOptions:
    """Build Feed-ingest options from raw values."""
    iter_days(start, end)
    return FeedIngestOptions(
        start=start,
        end=end,
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        branch=branch or FEED_ARCHIVES_BRANCH,
        json_output=json_output,
    )


__all__ = [
    "FEED_ARCHIVES_BRANCH",
    "FeedIngestOptions",
    "feed_ingest_options",
    "iter_days",
    "parse_day",
]
