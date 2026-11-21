"""Facade read surface over the feeds ledger: filters, provenance, absence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.domain.feeds.models import FilingEvent
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.pipelines.feeds.ledger import ledger_tip, publish_events
from edgar_sec.pipelines.feeds.paths import resolve_feeds_paths

_FETCHED = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _event(accession: str, form: str, filed: date, *sources: str) -> FilingEvent:
    return FilingEvent(
        accession=AccessionNumber.from_any(accession),
        cik=Cik.from_raw(12345),
        form=form,
        company_name="Example Corp",
        filing_date=filed,
        acceptance_datetime=datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
        link="https://example.invalid/filing",
        sources=sources,
    )


def _stored_ledger(tmp_path: Path) -> str:
    paths = resolve_feeds_paths(tmp_path)
    publish_events(
        paths,
        [
            _event(
                "0001193125-26-452129",
                "10-K",
                date(2026, 11, 6),
                "usgaap",
                "inline",
                "all",
            ),
            _event("0001493152-26-050546", "10-Q", date(2026, 10, 2), "usgaap"),
        ],
        command="run",
        fetched_at=_FETCHED,
    )
    publish_events(
        paths,
        [
            _event(
                "0001193125-26-452129",
                "10-K",
                date(2026, 11, 6),
                "monthly_archive",
            )
        ],
        command="backfill:2026-10",
        fetched_at=_FETCHED,
    )
    tip = ledger_tip(paths)
    assert tip is not None
    return tip


def test_feed_events_reads_the_tip_with_provenance(tmp_path: Path) -> None:
    tip = _stored_ledger(tmp_path)
    result = Edgar(artifacts_root=tmp_path).feed_events()
    assert result.ledger_present is True
    assert result.snapshot_id == tip
    assert len(result.events) == 2
    first = result.events[0]
    assert first.accession == "0001193125-26-452129"
    assert first.cik == "0000012345"
    assert first.form == "10-K"
    assert first.filing_date == date(2026, 11, 6)
    assert first.acceptance_datetime == datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
    assert first.sources == ("all", "inline", "monthly_archive", "usgaap")
    assert first.fetched_at == _FETCHED.isoformat()


def test_feed_events_filters_by_form_source_and_date_range(
    tmp_path: Path,
) -> None:
    _stored_ledger(tmp_path)
    edgar = Edgar(artifacts_root=tmp_path)
    by_form = edgar.feed_events(forms="10-Q")
    assert [event.accession for event in by_form.events] == ["0001493152-26-050546"]
    by_source = edgar.feed_events(sources=("monthly_archive",))
    assert [event.accession for event in by_source.events] == ["0001193125-26-452129"]
    # A source filter selects the event; its full provenance still rides.
    assert "usgaap" in by_source.events[0].sources
    by_range = edgar.feed_events(
        filed_from=date(2026, 10, 1), filed_to=date(2026, 10, 31)
    )
    assert [event.accession for event in by_range.events] == ["0001493152-26-050546"]
    limited = edgar.feed_events(limit=1)
    assert len(limited.events) == 1


def test_unstored_ledger_is_honest_absence_and_never_fetches(
    tmp_path: Path,
) -> None:
    edgar = Edgar(artifacts_root=tmp_path, sec_client=object())  # type: ignore[arg-type]
    result = edgar.feed_events()
    assert result.ledger_present is False
    assert result.snapshot_id is None
    assert result.events == ()
