"""Feed inventory publication through the acquisition snapshot DAG."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.feed_inventory import (
    FeedInventoryRecord,
)
from edgar_sec.pipelines.document_acquisition.feed_publish import (
    feed_tip,
    publish_inventory,
    published_archive_shas,
)
from edgar_sec.pipelines.document_acquisition.options import FEED_ARCHIVES_BRANCH
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.query import (
    query_snapshot_relation,
)

_NOW = datetime(2024, 1, 3, tzinfo=UTC)


def _record(accession: str, bundle_id: str) -> FeedInventoryRecord:
    return FeedInventoryRecord(
        accession=accession,
        cik="0000320193",
        form="10-K",
        filing_date=date(2024, 1, 2),
        feed_date=date(2024, 1, 2),
        bundle_id=bundle_id,
        archive_sha256="b" * 64,
    )


def test_publish_inventory_is_queryable_and_republish_is_noop(
    tmp_path: Path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    records = [
        _record("0000320193-24-000001", "20240102/a/0000320193-24-000001.txt"),
        _record("0000320193-24-000002", "20240102/b/0000320193-24-000002.txt"),
    ]
    result = publish_inventory(
        paths, records, branch=FEED_ARCHIVES_BRANCH, fetched_at=_NOW
    )
    assert result.published is True
    assert result.new_rows == 2
    assert result.total_rows == 2
    assert feed_tip(paths, FEED_ARCHIVES_BRANCH) == result.snapshot_id
    assert published_archive_shas(paths, FEED_ARCHIVES_BRANCH) == {"b" * 64}

    table = query_snapshot_relation(
        paths, "feed_inventory", branch_name=FEED_ARCHIVES_BRANCH
    )
    rows = sorted(table.to_pylist(), key=lambda row: row["accession"])
    assert [row["accession"] for row in rows] == [
        "0000320193-24-000001",
        "0000320193-24-000002",
    ]
    assert rows[0]["archive_sha256"] == "b" * 64
    assert rows[0]["filing_date"] == date(2024, 1, 2)
    # The run-publication branch is untouched by the source leg.
    assert feed_tip(paths, "main") is None

    republish = publish_inventory(
        paths, records, branch=FEED_ARCHIVES_BRANCH, fetched_at=_NOW
    )
    assert republish.published is False
    assert republish.new_rows == 0
    assert republish.total_rows == 2
    assert feed_tip(paths, FEED_ARCHIVES_BRANCH) == result.snapshot_id
