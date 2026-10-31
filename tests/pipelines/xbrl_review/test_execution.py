"""Tests for XBRL projection work-order execution and snapshot publication."""

import json
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.xbrl_review.bundles import (
    load_filing,
    registry_filings,
    registry_row,
)
from edgar_sec.pipelines.xbrl_review.commands.project import project_xbrl_run
from edgar_sec.pipelines.xbrl_review.execution import execute_projection_run
from edgar_sec.pipelines.xbrl_review.paths import xbrl_paths, xbrl_run_paths


def _project_two_filings(tmp_path: Path) -> str:
    seeds = [s for s in registry_filings() if s.firm in ("MCD", "EOG")]
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps([registry_row(seed) for seed in seeds]), encoding="utf-8"
    )
    manifest = project_xbrl_run(
        dataset_path=dataset, artifacts_root=tmp_path, chunk_size=1
    )
    return str(manifest["run_id"])


def test_execute_projection_run_publishes_snapshot(tmp_path: Path) -> None:
    """Verify execution solves the work order and publishes a snapshot."""
    run_id = _project_two_filings(tmp_path)
    result = execute_projection_run(run_id, artifacts_root=tmp_path)

    assert result.filings == 2
    assert result.chunks == 2
    assert result.solved_count > 0

    paths = xbrl_paths(tmp_path)
    snapshot_dir = paths.snapshots_root / result.snapshot_id
    for relation in (
        "solved_nodes",
        "rule_trace",
        "quarantine",
        "hypotheses",
        "presentation_arcs",
        "calculation_arcs",
    ):
        assert (snapshot_dir / relation / "part-00000.parquet").is_file()

    seeds = [s for s in registry_filings() if s.firm in ("MCD", "EOG")]
    for relation, field in (
        ("presentation_arcs", "pres_arcs"),
        ("calculation_arcs", "calc_arcs"),
    ):
        table = pq.read_table(snapshot_dir / relation / "part-00000.parquet")
        expected = sum(len(getattr(load_filing(seed), field)) for seed in seeds)
        assert table.num_rows == expected
        assert set(table.column("accession").to_pylist()) == {
            str(seed.accession) for seed in seeds
        }

    catalog = DAGCatalog(paths.snapshots_root)
    pointer = catalog.read_pointer("main")
    assert pointer is not None
    assert pointer["snapshot_id"] == result.snapshot_id

    run_paths = xbrl_run_paths(tmp_path, run_id)
    for index in range(2):
        chunk_id = f"chunk-{index:04d}"
        assert run_paths.chunk_pointer_path(chunk_id).is_file()
        assert run_paths.attempt_solved_nodes_path(chunk_id, "1").is_file()

    run_manifest = json.loads(run_paths.run_manifest_path().read_text("utf-8"))
    assert run_manifest["status"] == "executed"
    assert run_manifest["snapshot_id"] == result.snapshot_id


def test_execute_projection_run_resumes_completed_chunks(tmp_path: Path) -> None:
    """Verify a second execution resumes chunks and publishes a delta."""
    run_id = _project_two_filings(tmp_path)
    first = execute_projection_run(run_id, artifacts_root=tmp_path)
    second = execute_projection_run(run_id, artifacts_root=tmp_path)

    assert second.snapshot_id != first.snapshot_id
    assert second.filings == first.filings
    assert second.solved_count == first.solved_count
    manifest = DAGCatalog(xbrl_paths(tmp_path).snapshots_root).get_manifest(
        second.snapshot_id
    )
    assert manifest is not None
    assert manifest.kind == "delta"
    assert manifest.parent_snapshot_id == first.snapshot_id
