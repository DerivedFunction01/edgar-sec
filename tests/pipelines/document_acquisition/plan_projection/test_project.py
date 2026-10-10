from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    AcquisitionProjectError,
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.pipelines.document_planning.schemas import (
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)


@pytest.fixture
def project_fixture(tmp_path: Path):
    artifacts_root = tmp_path / "artifacts"
    plan_root, rows = _make_plan(artifacts_root)
    paths = resolve_acquisition_paths(tmp_path, artifacts_root)
    return paths, plan_root, rows


def _make_plan(
    artifacts_root: Path, *, row_count: int = 3
) -> tuple[Path, list[dict[str, Any]]]:
    identity = {
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "c" * 64,
        "catalog_plan_id": "catalog-fixture",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": "snapshot-fixture",
        "inventory_snapshot_digest": "b" * 64,
    }
    plan_id = f"dplan_{canonical_hash(identity)[:32]}"
    plan_root = artifacts_root / "document_planning" / "plans" / plan_id
    part = plan_root / "targets" / "form=10-K" / "part-00000.parquet"
    part.parent.mkdir(parents=True)
    rows = []
    for index in range(row_count):
        accession = f"0000000001-24-{index + 1:06d}"
        status = "matched" if index == 0 else "unresolved"
        row = {
            "target_id": "",
            "accession": accession,
            "form": "10-K",
            "filing_date": f"2024-01-{index + 1:02d}",
            "request_id": f"primary:{index}",
            "target_role": "primary",
            "target_type": "primary",
            "optional": False,
            "inventory_entry_id": f"entry-{index}",
            "status": status,
            "status_reason": None if status == "matched" else "not_found",
            "source_origin": "inventory_index",
            "retrieval_mode": "direct_url" if status == "matched" else "none",
            "target_url": (
                "https://www.sec.gov/Archives/edgar/data/1/"
                f"000000000124{index + 1:06d}/report.htm"
                if status == "matched"
                else None
            ),
            "sequence": None,
            "byte_size": 32 if status == "matched" else None,
            "availability_evidence": "index_html" if status == "matched" else "none",
            "catalog_direct_selection": None,
        }
        row["target_id"] = canonical_hash(
            [plan_id, accession, row["request_id"], row["inventory_entry_id"], status]
        )
        rows.append(row)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=TARGET_SCHEMA),
        part,
        row_group_size=DEFAULT_ROW_GROUP_SIZE,
    )
    statuses = Counter(row["status"] for row in rows)
    manifest = {
        "plan_id": plan_id,
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": identity["row_group_size"],
        "profile_id": "profile-fixture",
        "profile_schema_version": "1",
        "profile_version": "1",
        "profile_digest": identity["profile_digest"],
        "catalog_plan_id": identity["catalog_plan_id"],
        "catalog_plan_digest": identity["catalog_plan_digest"],
        "inventory_snapshot_id": identity["inventory_snapshot_id"],
        "inventory_snapshot_digest": identity["inventory_snapshot_digest"],
        "plan_identity": identity,
        "target_row_count": len(rows),
        "status_counts": dict(statuses),
        "origin_counts": {"inventory_index": len(rows)},
        "reason_counts": {},
        "parts": [
            {
                "path": "targets/form=10-K/part-00000.parquet",
                "form": "10-K",
                "rows": len(rows),
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        ],
    }
    manifest["plan_digest"] = canonical_hash(manifest)
    (plan_root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plan_root, rows


def test_creates_pinned_run_and_canonical_manifest(project_fixture):
    paths, plan_root, rows = project_fixture

    result = project_acquisition_run(plan_root.name, paths=paths)

    manifest_path = paths.run_manifest_path(result.run_id)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    part = manifest["work_order_parts"][0]
    assert not result.reused
    assert result.executable_count == 1
    assert result.skipped_count == len(rows) - 1
    assert manifest_text == json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert manifest["run_digest"] == canonical_hash(
        {key: value for key, value in manifest.items() if key != "run_digest"}
    )
    assert manifest["bundle_schema_version"] == 3
    assert manifest["matcher_version"] == "target-matcher-v2"
    assert manifest["work_order_schema_version"] == "1"
    assert part["row_count"] == len(rows)
    work_order = paths.work_order_root(result.run_id) / "part-00000.parquet"
    assert part["byte_size"] == work_order.stat().st_size
    assert part["sha256"] == file_sha256(work_order)
    assert paths.run_state_path(result.run_id).is_file()


def test_state_seed_is_a_bounded_batch_generator(project_fixture, monkeypatch):
    import edgar_sec.pipelines.document_acquisition.plan_projection.project as project

    paths, plan_root, _rows = project_fixture
    monkeypatch.setenv("PARQUET_READ_BATCH_SIZE", "2")
    original_initialize = project.initialize_run_state
    original_parquet_file = project.pq.ParquetFile
    seen: list[object] = []
    work_order_batch_sizes: list[int] = []

    class TrackingParquetFile:
        def __init__(self, path):
            self.path = Path(path)
            self.parquet = original_parquet_file(path)

        def __getattr__(self, name):
            return getattr(self.parquet, name)

        def iter_batches(self, **kwargs):
            batches = self.parquet.iter_batches(**kwargs)
            if "work_order" in self.path.parts:
                for batch in batches:
                    work_order_batch_sizes.append(batch.num_rows)
                    yield batch
            else:
                yield from batches

    def inspect_seed(database, targets):
        seen.append(targets)
        return original_initialize(database, targets)

    monkeypatch.setattr(project.pq, "ParquetFile", TrackingParquetFile)
    monkeypatch.setattr(project, "initialize_run_state", inspect_seed)

    project_acquisition_run(plan_root.name, paths=paths)

    assert len(seen) == 1
    assert iter(seen[0]) is seen[0]
    assert not isinstance(seen[0], (list, tuple))
    assert work_order_batch_sizes == [2, 1, 2, 1]


def test_identical_projection_reuses_valid_run(project_fixture):
    paths, plan_root, _rows = project_fixture
    first = project_acquisition_run(plan_root.name, paths=paths)

    second = project_acquisition_run(plan_root.name, paths=paths)

    assert second.run_id == first.run_id
    assert second.reused
    assert second.manifest == first.manifest


def test_corrupt_existing_database_is_refused(project_fixture):
    paths, plan_root, _rows = project_fixture
    result = project_acquisition_run(plan_root.name, paths=paths)
    paths.run_state_path(result.run_id).write_bytes(b"not sqlite")

    with pytest.raises(AcquisitionProjectError, match="integrity"):
        project_acquisition_run(plan_root.name, paths=paths)


def test_divergent_existing_work_order_is_refused(project_fixture):
    paths, plan_root, _rows = project_fixture
    result = project_acquisition_run(plan_root.name, paths=paths)
    work_order = paths.work_order_root(result.run_id) / "part-00000.parquet"
    work_order.write_bytes(b"divergent")

    with pytest.raises(AcquisitionProjectError, match="manifest|digest"):
        project_acquisition_run(plan_root.name, paths=paths)


def test_invalid_target_plan_leaves_no_run_directory(project_fixture):
    paths, plan_root, _rows = project_fixture
    manifest_path = plan_root / "plan.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["plan_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AcquisitionProjectError, match="cannot be projected"):
        project_acquisition_run(plan_root.name, paths=paths)

    assert list(paths.runs_root.iterdir()) == []
