from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.query import (
    get_snapshot_status,
    list_snapshots,
    query_snapshot_relation,
)
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_get_snapshot_status_on_empty_branch(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    status = get_snapshot_status(paths, branch_name="main")
    assert not status["published"]
    assert status["snapshot_id"] is None


def test_query_snapshot_relation_unknown_name_raises(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    with pytest.raises(ValueError, match="unknown relation name"):
        query_snapshot_relation(paths, "non_existent_relation")


def test_query_snapshot_relation_on_published_run(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")
    assert pub.status == "published"

    status = get_snapshot_status(paths, branch_name="main")
    assert status["published"]
    assert status["snapshot_id"] == pub.snapshot_id
    assert status["relation_counts"]["target_results"] == 1

    table = query_snapshot_relation(paths, "target_results")
    assert table.num_rows == 1
    assert len(table.column("target_id").to_pylist()[0]) > 0
    assert table.column("outcome").to_pylist() == ["acquired"]

    limited = query_snapshot_relation(paths, "target_results", limit=1)
    assert limited.num_rows == 1

    snapshots = list_snapshots(paths)
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == pub.snapshot_id
