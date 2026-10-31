"""Tests for offline snapshot retrieval and query engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.snapshots import query_filings_from_snapshot
from edgar_sec.domain.filing_catalog.filters import DateRange
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_query_filings_from_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Verify querying filings directly from published snapshot."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    payload_loads = []

    def load_payload(*args):
        payload_loads.append(args[-1])
        return b"<html>Sample filing content</html>"

    monkeypatch.setattr(
        "edgar_sec.apps.client.snapshots._load_snapshot_payload", load_payload
    )
    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    assert len(res) == 1
    filing = res[0]
    assert filing.form == "10-K"
    assert res.first().accession == filing.accession
    assert res.latest().accession == filing.accession
    assert payload_loads == []
    assert filing.raw() == b"<html>Sample filing content</html>"
    assert payload_loads == [filing.primary_sha256]

    df = res.to_df()
    assert len(df) == 1
    assert "accession" in df.columns
    assert res.to_arrow().num_rows == 1
    assert res.sql("SELECT count(*) AS n FROM joined").limit(1).fetchall()[0][0] == 1
    assert len(res.attachments_df().columns) == 8
    assert len(res.exhibits().columns) == 7
    assert len(res.linkbases_df().columns) == 6
    assert len(res.staged_df().columns) == 8
    assert len(res.joined_df().columns) == 8
    assert len(res.exhibits("21").columns) == 7
    assert len(res.filter(form="10-Q")) == 0
    assert len(res.filter(date="2023")) == 0
    assert len(res.filter(limit=0)) == 0
    assert len(res.cofilers()) == 1

    empty = query_filings_from_snapshot(
        tmp_path, snapshot_id_or_tag="main", forms=("10-Q",)
    )
    assert len(empty) == 0
    assert list(empty.to_df().columns) == list(df.columns)
    with pytest.raises(IndexError):
        _ = empty[-1]
    assert (
        len(
            query_filings_from_snapshot(
                tmp_path, snapshot_id_or_tag="main", ciks=("0000000999",)
            )
        )
        == 0
    )
    assert (
        len(
            query_filings_from_snapshot(
                tmp_path, snapshot_id_or_tag="main", dates=DateRange.year(2023)
            )
        )
        == 0
    )
    assert (
        len(query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main", limit=0))
        == 0
    )


def test_facade_snapshot_access_and_tag(tmp_path: Path) -> None:
    """Verify Edgar.fetch(mode='snapshot') and Edgar.from_snapshot() via tags."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    edgar = Edgar(artifacts_root=tmp_path)
    edgar.snapshots.tag("prod-v1", pub.snapshot_id)

    res_main = edgar.fetch(mode="snapshot", snapshot="main")
    assert len(res_main) == 1
    assert res_main[0].form == "10-K"

    res_tag = edgar.from_snapshot("prod-v1")
    assert len(res_tag) == 1
    assert res_tag[0].raw() == b"<html>Sample filing content</html>"


def test_snapshot_session_caching(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    con1, views1 = session.connection()
    con2, views2 = session.connection()
    assert con1 is con2
    assert views1 == views2
    attachments = session.load_attachments("0000320193-23-000106")
    assert isinstance(attachments, tuple)
