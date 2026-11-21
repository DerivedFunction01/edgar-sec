"""Feed event model: provenance merging and the normalized accession key."""

from __future__ import annotations

from datetime import UTC, date, datetime

from edgar_sec.domain.feeds.models import FilingEvent
from edgar_sec.domain.identity import AccessionNumber, Cik


def _event() -> FilingEvent:
    return FilingEvent(
        accession=AccessionNumber.from_any("0001193125-26-452129"),
        cik=Cik.from_raw("0001425355"),
        form="10-Q",
        company_name="SUI Group Holdings Ltd.",
        filing_date=date(2026, 11, 6),
        acceptance_datetime=datetime(2026, 11, 6, 22, 30, 32, tzinfo=UTC),
        link="https://www.sec.gov/Archives/edgar/data/1425355/x-index.htm",
        sources=("usgaap",),
    )


def test_accession_normalized_is_the_unhyphenated_key() -> None:
    assert _event().accession_normalized == "000119312526452129"


def test_with_source_merges_provenance_without_duplicates() -> None:
    event = _event().with_source("all").with_source("usgaap")
    assert event.sources == ("usgaap", "all")
    assert _event().sources == ("usgaap",)
