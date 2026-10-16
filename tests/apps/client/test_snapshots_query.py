"""Tests for offline snapshot retrieval and query engine."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.snapshots import query_filings_from_snapshot
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_query_filings_from_snapshot(tmp_path: Path) -> None:
    """Verify querying filings directly from published snapshot."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    assert len(res) == 1
    filing = res[0]
    assert filing.form == "10-K"
    assert filing.raw() == b"<html>Sample filing content</html>"

    df = res.to_df()
    assert len(df) == 1
    assert "accession" in df.columns


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
