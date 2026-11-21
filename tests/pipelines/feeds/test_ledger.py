"""Ledger publication: anti-join dedupe, provenance rows, tip movement."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from edgar_sec.domain.feeds.models import FilingEvent
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.pipelines.feeds.ledger import (
    ledger_stats,
    ledger_tip,
    publish_events,
)
from edgar_sec.pipelines.feeds.paths import resolve_feeds_paths

_FETCHED = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _event(accession: str, *sources: str) -> FilingEvent:
    return FilingEvent(
        accession=AccessionNumber.from_any(accession),
        cik=Cik.from_raw(12345),
        form="10-K",
        company_name="Example Corp",
        filing_date=date(2026, 11, 6),
        acceptance_datetime=datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
        link="https://example.invalid/filing",
        sources=sources,
    )


def test_ledger_is_absent_before_any_publish(tmp_path: Path) -> None:
    paths = resolve_feeds_paths(tmp_path)
    assert ledger_tip(paths) is None
    assert ledger_stats(paths) is None


def test_publish_expands_one_row_per_accession_and_source(
    tmp_path: Path,
) -> None:
    paths = resolve_feeds_paths(tmp_path)
    events = [
        _event("0001193125-26-452129", "usgaap", "inline", "all"),
        _event("0001493152-26-050546", "usgaap"),
    ]
    result = publish_events(paths, events, command="run", fetched_at=_FETCHED)
    assert result.published is True
    assert result.new_rows == 4
    assert result.total_rows == 4
    assert result.per_source_new == {"usgaap": 2, "inline": 1, "all": 1}
    stats = ledger_stats(paths)
    assert stats is not None
    assert stats.tip_snapshot_id == result.snapshot_id
    assert stats.total_rows == 4
    assert stats.distinct_accessions == 2
    assert {row.source: row.row_count for row in stats.per_source} == {
        "usgaap": 2,
        "inline": 1,
        "all": 1,
    }
    assert all(row.latest_fetched_at is not None for row in stats.per_source)


def test_republish_of_the_same_events_is_a_noop(tmp_path: Path) -> None:
    paths = resolve_feeds_paths(tmp_path)
    events = [_event("0001193125-26-452129", "usgaap")]
    first = publish_events(paths, events, command="run", fetched_at=_FETCHED)
    second = publish_events(paths, events, command="run", fetched_at=_FETCHED)
    assert first.published is True
    assert second.published is False
    assert second.new_rows == 0
    assert second.total_rows == 1
    assert ledger_tip(paths) == first.snapshot_id


def test_second_publish_adds_only_new_accession_source_rows(
    tmp_path: Path,
) -> None:
    paths = resolve_feeds_paths(tmp_path)
    publish_events(
        paths,
        [_event("0001193125-26-452129", "usgaap")],
        command="run",
        fetched_at=_FETCHED,
    )
    result = publish_events(
        paths,
        [
            _event("0001193125-26-452129", "usgaap", "all"),
            _event("0001493152-26-050546", "monthly_archive"),
        ],
        command="backfill:2026-10",
        fetched_at=_FETCHED,
    )
    assert result.published is True
    assert result.new_rows == 2
    assert result.total_rows == 3
    stats = ledger_stats(paths)
    assert stats is not None
    assert stats.distinct_accessions == 2
    assert {row.source: row.row_count for row in stats.per_source} == {
        "usgaap": 1,
        "all": 1,
        "monthly_archive": 1,
    }


def test_publish_touches_only_the_feeds_store(tmp_path: Path) -> None:
    paths = resolve_feeds_paths(tmp_path)
    publish_events(
        paths,
        [_event("0001193125-26-452129", "usgaap")],
        command="run",
        fetched_at=_FETCHED,
    )
    names = {entry.name for entry in tmp_path.iterdir()}
    assert "metadata" not in names
    assert (tmp_path / "feeds" / "snapshots").is_dir()
