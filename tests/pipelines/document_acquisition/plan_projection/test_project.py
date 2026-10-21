from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    AcquisitionProjectError,
    project_acquisition_run,
)
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_acquisition.run_validation import (
    _sqlite_scanner_installed,
    iter_resolved_work_order_operations,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.pipelines.document_planning.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
)
from tests.pipelines.document_acquisition.plan_projection.plan_fixture import (
    write_plan_bundle,
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
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
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
    plan_root.mkdir(parents=True)
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
    write_plan_bundle(plan_root, plan_id, identity, rows)
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
    assert manifest["bundle_schema_version"] == 5
    assert manifest["matcher_version"] == "target-matcher-v6"
    assert manifest["work_order_schema_version"] == "4"
    assert set(manifest["work_order_relations"]) == {
        "targets",
        "target_operations",
        "source_requests",
        "operation_inputs",
        "resolved_operations",
    }
    assert part["row_count"] == len(rows)
    operations = list(iter_resolved_work_order_operations(paths, result.run_id))
    assert len(operations) == 3 * len(rows)
    raw = next(
        row
        for row in operations
        if row["operation"] == "raw" and row["source_request_id"] is not None
    )
    assert raw["support_status"] == "supported"
    assert raw["selected"] is True
    assert raw["handler_id"] == "raw_identity"
    assert raw["source_request_id"] is not None
    assert raw["source_request_canonical_path"] is not None
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
            if self.path.parent.name == "work_order":
                for batch in batches:
                    work_order_batch_sizes.append(batch.num_rows)
                    yield batch
            else:
                yield from batches

    def inspect_seed(database, targets, operations=()):
        seen.append(targets)
        return original_initialize(database, targets, operations)

    monkeypatch.setattr(project.pq, "ParquetFile", TrackingParquetFile)
    monkeypatch.setattr(project, "initialize_run_state", inspect_seed)

    with connect() as con:
        scanner_installed = _sqlite_scanner_installed(con)

    project_acquisition_run(plan_root.name, paths=paths)

    assert len(seen) == 1
    assert iter(seen[0]) is seen[0]
    assert not isinstance(seen[0], (list, tuple))
    # Seeding streams the work order once. Post-seed validation compares
    # in SQL when sqlite_scanner is installed; without it, the Python
    # fallback re-reads the work order, doubling the tracked batches.
    if scanner_installed:
        assert work_order_batch_sizes == [2, 1]
    else:
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


@pytest.mark.parametrize(
    "field",
    [
        "target_operation_schema_version",
        "source_request_schema_version",
        "operation_input_schema_version",
        "resolved_operation_schema_version",
    ],
)
def test_run_manifest_rejects_mismatched_relation_schema_versions(
    project_fixture, field
):
    paths, plan_root, _rows = project_fixture
    result = project_acquisition_run(plan_root.name, paths=paths)
    manifest_path = paths.run_manifest_path(result.run_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] += 1
    manifest["run_digest"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "run_digest"}
    )
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        load_validated_work_order(paths, result.run_id)


def test_invalid_target_plan_leaves_no_run_directory(project_fixture):
    paths, plan_root, _rows = project_fixture
    manifest_path = plan_root / "plan.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["plan_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AcquisitionProjectError, match="cannot be projected"):
        project_acquisition_run(plan_root.name, paths=paths)

    assert list(paths.runs_root.iterdir()) == []
