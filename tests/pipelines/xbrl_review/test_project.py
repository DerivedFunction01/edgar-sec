"""Tests for XBRL review dataset projection command."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.pipelines.xbrl_review.commands.project import project_xbrl_run
from edgar_sec.pipelines.xbrl_review.paths import xbrl_paths, xbrl_run_paths

_ROWS = [
    {
        "accession": "0000950170-24-000001",
        "form": "10-K",
        "filing_date": "2024-02-15",
        "cik": 789019,
        "period": "2023-12-31",
    },
    {
        "accession": "0000950170-24-000002",
        "form": "10-K",
        "filing_date": "2024-02-16",
        "cik": 320193,
        "period": "2023-12-31",
    },
]


def _write_dataset(tmp_path: Path) -> Path:
    dataset_file = tmp_path / "dataset.json"
    dataset_file.write_text(json.dumps(_ROWS), encoding="utf-8")
    return dataset_file


def test_project_dataset_writes_manifest_and_work_order(tmp_path: Path) -> None:
    """Verify dataset projection records manifest fields and work rows."""
    dataset_file = _write_dataset(tmp_path)
    manifest = project_xbrl_run(dataset_path=dataset_file, artifacts_root=tmp_path)
    assert manifest["source_type"] == "dataset"
    assert manifest["source_ref"] == str(dataset_file)
    assert manifest["cohort_accession_rows"] == 2
    assert manifest["work_order_rows"] == 2
    assert manifest["base_snapshot_id"] is None
    assert manifest["branch"] == "main"
    assert manifest["solver_fingerprint"]
    assert manifest["chunk_size"]

    run_paths = xbrl_run_paths(tmp_path, manifest["run_id"])
    on_disk = json.loads(
        run_paths.projection_manifest_path().read_text(encoding="utf-8")
    )
    assert on_disk == manifest
    rows = pq.read_table(run_paths.work_order_path()).to_pylist()
    assert len(rows) == 2
    assert {row["accession"] for row in rows} == {
        "0000950170-24-000001",
        "0000950170-24-000002",
    }


def test_project_dataset_excludes_base_snapshot_accessions(
    tmp_path: Path,
) -> None:
    """Verify base snapshot solved nodes shrink the work order."""
    dataset_file = _write_dataset(tmp_path)
    snapshot_id = "snapshot-base1"
    relation_dir = xbrl_paths(tmp_path).snapshots_root / snapshot_id / "solved_nodes"
    relation_dir.mkdir(parents=True)
    pq.write_table(
        pa.table({"accession": ["0000950170-24-000001"]}),
        relation_dir / "part-00000.parquet",
    )
    manifest = project_xbrl_run(
        dataset_path=dataset_file,
        artifacts_root=tmp_path,
        base_snapshot_id=snapshot_id,
    )
    assert manifest["base_snapshot_id"] == snapshot_id
    assert manifest["cohort_accession_rows"] == 2
    assert manifest["work_order_rows"] == 1
    run_paths = xbrl_run_paths(tmp_path, manifest["run_id"])
    rows = pq.read_table(run_paths.work_order_path()).to_pylist()
    assert [row["accession"] for row in rows] == ["0000950170-24-000002"]


def test_project_rejects_missing_dataset(tmp_path: Path) -> None:
    """Verify projection refuses a missing or absent dataset."""
    with pytest.raises(ValueError):
        project_xbrl_run(
            dataset_path=tmp_path / "missing.json", artifacts_root=tmp_path
        )
    with pytest.raises(ValueError):
        project_xbrl_run(artifacts_root=tmp_path)
