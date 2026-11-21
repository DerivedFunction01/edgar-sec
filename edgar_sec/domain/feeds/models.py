"""One filing event as served by an SEC feed, before any canonical merge.

Fields are as served: an event names a filing, it is never a submissions row.
Acceptance datetimes are timezone-aware UTC when the feed serves one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from edgar_sec.domain.identity import AccessionNumber, Cik

SOURCE_CURRENT_FILINGS = "current_filings"
SOURCE_MONTHLY_ARCHIVE = "monthly_archive"
STRUCTURED_FEED_SOURCES: tuple[str, ...] = ("usgaap", "risk_return", "inline", "all")


@dataclass(frozen=True, slots=True)
class FilingEvent:
    """A single feed entry, deduped by accession with provenance in ``sources``."""

    accession: AccessionNumber
    cik: Cik
    form: str
    company_name: str
    filing_date: date
    acceptance_datetime: datetime | None
    link: str
    sources: tuple[str, ...]

    @property
    def accession_normalized(self) -> str:
        """The unhyphenated accession, the dedupe and join key for events."""
        return self.accession.normalized

    def with_source(self, source: str) -> FilingEvent:
        """Return this event with ``source`` added to its provenance."""
        if source in self.sources:
            return self
        return replace(self, sources=(*self.sources, source))


@dataclass(frozen=True, slots=True)
class FeedParseFailure:
    """One feed entry that could not be parsed, recorded rather than raised."""

    source: str
    entry_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class FeedParseOutcome:
    """The result of parsing one feed payload: events plus per-entry failures."""

    source: str
    events: tuple[FilingEvent, ...]
    failures: tuple[FeedParseFailure, ...]
    payload_sha256: str
    parser_fingerprint: str


__all__ = [
    "SOURCE_CURRENT_FILINGS",
    "SOURCE_MONTHLY_ARCHIVE",
    "STRUCTURED_FEED_SOURCES",
    "FeedParseFailure",
    "FeedParseOutcome",
    "FilingEvent",
]
