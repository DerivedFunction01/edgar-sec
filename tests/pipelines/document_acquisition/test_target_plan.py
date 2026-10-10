from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_acquisition.arrow_schemas import WORK_ORDER_SCHEMA
from edgar_sec.pipelines.document_acquisition.target_plan import (
    TargetPlanError,
    _validate_row,
    load_acquisition_work_order,
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
def target_plan_factory(tmp_path):
    def build(
        rows: list[dict[str, Any]] | None = None,
    ) -> tuple[Path, list[dict[str, Any]]]:
        inventory_digest = "b" * 64
        identity = {
            "bundle_schema_version": target_plan_bundle_schema_version(),
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "matcher_version": target_plan_matcher_version(),
            "row_group_size": DEFAULT_ROW_GROUP_SIZE,
            "profile_digest": "c" * 64,
            "catalog_plan_id": "catalog-fixture",
            "catalog_plan_digest": "a" * 64,
            "inventory_snapshot_id": "snapshot-fixture",
            "inventory_snapshot_digest": inventory_digest,
        }
        plan_id = f"dplan_{canonical_hash(identity)[:32]}"
        plan_root = tmp_path / plan_id
        (plan_root / "targets" / "form=10-K").mkdir(parents=True)
        target_rows = rows or _rows(plan_id)
        part_path = plan_root / "targets" / "form=10-K" / "part-00000.parquet"
        pq.write_table(
            pa.Table.from_pylist(target_rows, schema=TARGET_SCHEMA),
            part_path,
            row_group_size=DEFAULT_ROW_GROUP_SIZE,
        )
        statuses = Counter(row["status"] for row in target_rows)
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
            "target_row_count": len(target_rows),
            "status_counts": dict(statuses),
            "origin_counts": {"inventory_index": len(target_rows)},
            "reason_counts": {},
            "parts": [
                {
                    "path": "targets/form=10-K/part-00000.parquet",
                    "form": "10-K",
                    "rows": len(target_rows),
                    "byte_size": part_path.stat().st_size,
                    "sha256": file_sha256(part_path),
                }
            ],
        }
        _seal_manifest(manifest, plan_root)
        return plan_root, target_rows

    return build


def _rows(plan_id: str) -> list[dict[str, Any]]:
    accessions = [
        "0000000001-24-000001",
        "0000000001-24-000002",
        "0000000001-24-000003",
        "0000000001-24-000004",
    ]
    result = [
        {
            "target_id": "",
            "accession": accessions[0],
            "form": "10-K",
            "filing_date": "2024-01-01",
            "request_id": "primary:primary",
            "target_role": "primary",
            "target_type": "primary",
            "optional": False,
            "inventory_entry_id": "entry-direct",
            "status": "matched",
            "status_reason": None,
            "source_origin": "inventory_index",
            "retrieval_mode": "direct_url",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/report.htm",
            "sequence": None,
            "byte_size": 250,
            "availability_evidence": "index_html",
            "catalog_direct_selection": "submitted_primary",
        },
        {
            "target_id": "",
            "accession": accessions[1],
            "form": "10-K",
            "filing_date": "2024-01-02",
            "request_id": "exhibit:EX-21",
            "target_role": "exhibit",
            "target_type": "EX-21",
            "optional": True,
            "inventory_entry_id": "entry-bundle",
            "status": "matched",
            "status_reason": None,
            "source_origin": "inventory_index",
            "retrieval_mode": "bundle_sequence",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/0000000001-24-000002.txt",
            "sequence": 3,
            "byte_size": 500,
            "availability_evidence": "index_html",
            "catalog_direct_selection": None,
        },
        {
            "target_id": "",
            "accession": accessions[2],
            "form": "10-K",
            "filing_date": "2024-01-03",
            "request_id": "graphic:GRAPHIC",
            "target_role": "graphic",
            "target_type": "GRAPHIC",
            "optional": True,
            "inventory_entry_id": None,
            "status": "constructed_candidate",
            "status_reason": "unverified_candidate",
            "source_origin": "inventory_index",
            "retrieval_mode": "constructed_package",
            "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000003/report.zip",
            "sequence": None,
            "byte_size": None,
            "availability_evidence": "constructed",
            "catalog_direct_selection": None,
        },
        {
            "target_id": "",
            "accession": accessions[3],
            "form": "10-K",
            "filing_date": "2024-01-04",
            "request_id": "exhibit:EX-99",
            "target_role": "exhibit",
            "target_type": "EX-99",
            "optional": True,
            "inventory_entry_id": None,
            "status": "unresolved",
            "status_reason": "no_usable_retrieval_locator",
            "source_origin": "inventory_index",
            "retrieval_mode": "none",
            "target_url": None,
            "sequence": None,
            "byte_size": None,
            "availability_evidence": "none",
            "catalog_direct_selection": None,
        },
    ]
    for row in result:
        row["target_id"] = canonical_hash(
            [
                plan_id,
                row["accession"],
                row["request_id"],
                row["inventory_entry_id"],
                row["status"],
            ]
        )
    return result


def _seal_manifest(manifest: dict[str, Any], root: Path) -> None:
    import json

    manifest.pop("plan_digest", None)
    manifest["plan_digest"] = canonical_hash(manifest)
    (root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_projects_all_rows_and_preserves_selector_provenance(
    target_plan_factory, tmp_path
):
    plan_root, source_rows = target_plan_factory()
    output = tmp_path / "work-order.parquet"

    result = load_acquisition_work_order(plan_root, output)

    work_order = pq.read_table(output)
    assert work_order.schema.equals(WORK_ORDER_SCHEMA, check_metadata=False)
    assert work_order.num_rows == len(source_rows)
    assert result.executable_count == 2
    assert result.skipped_count == 2
    assert (
        work_order.column("catalog_direct_selection").to_pylist()[0]
        == "submitted_primary"
    )
    assert work_order.column("executable").to_pylist() == [True, True, False, False]
    assert work_order.column("skip_reason").to_pylist() == [
        None,
        None,
        "candidate_not_authorized",
        "target_not_matched",
    ]
    assert target_plan_bundle_schema_version() == 3
    assert target_plan_matcher_version() == "target-matcher-v2"
    assert result.bundle_schema_version == 3
    assert result.matcher_version == "target-matcher-v2"
    assert result.target_schema_version == 1
    assert file_sha256(plan_root / "targets/form=10-K/part-00000.parquet") == next(
        part["sha256"] for part in _manifest(plan_root)["parts"]
    )


def test_missing_declared_part_size_fails_before_output(target_plan_factory, tmp_path):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    del manifest["parts"][0]["byte_size"]
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "not-created" / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="missing declared byte_size"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()
    assert not output.parent.exists()


@pytest.mark.parametrize("version", [None, 1])
def test_missing_or_unsupported_bundle_schema_version_fails_before_output(
    target_plan_factory, tmp_path, version
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    if version is None:
        del manifest["bundle_schema_version"]
        message = "missing or unsupported target-plan bundle schema version"
    else:
        manifest["bundle_schema_version"] = version
        message = "missing or unsupported target-plan bundle schema version"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match=message):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_missing_bundle_schema_version_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    del manifest["plan_identity"]["bundle_schema_version"]
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="bundle schema version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_unsupported_bundle_schema_version_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["plan_identity"]["bundle_schema_version"] = 1
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="bundle schema version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_matcher_version_mismatch_is_rejected_before_output(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["matcher_version"] = "target-matcher-v1"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="requires target-matcher-v2"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_matcher_version_mismatch_in_identity_is_rejected(
    target_plan_factory, tmp_path
):
    plan_root, _rows_value = target_plan_factory()
    manifest = _manifest(plan_root)
    manifest["plan_identity"]["matcher_version"] = "target-matcher-v1"
    _seal_manifest(manifest, plan_root)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(
        TargetPlanError, match="matcher version in target-plan identity"
    ):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


def test_cross_accession_url_fails_before_output(target_plan_factory, tmp_path):
    plan_root, _rows_value = target_plan_factory()
    part = plan_root / "targets/form=10-K/part-00000.parquet"
    rows = pq.read_table(part).to_pylist()
    rows[0]["target_url"] = (
        "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/report.htm"
    )
    _replace_part(plan_root, rows)
    output = tmp_path / "work-order.parquet"

    with pytest.raises(TargetPlanError, match="outside the accession's SEC archive"):
        load_acquisition_work_order(plan_root, output)

    assert not output.exists()


@pytest.mark.parametrize("sequence", [True, 0, -1])
def test_bundle_sequence_rejects_boolean_and_nonpositive_values(
    target_plan_factory, sequence
):
    plan_root, rows = target_plan_factory()
    row = dict(rows[1], sequence=sequence)

    with pytest.raises(TargetPlanError, match="positive integer"):
        _validate_row(row, plan_root.name, True, "10-K")


def _manifest(root: Path) -> dict[str, Any]:
    import json

    return json.loads((root / "plan.json").read_text(encoding="utf-8"))


def _replace_part(root: Path, rows: list[dict[str, Any]]) -> None:
    import json

    part = root / "targets/form=10-K/part-00000.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=TARGET_SCHEMA), part)
    manifest = _manifest(root)
    manifest["parts"][0]["byte_size"] = part.stat().st_size
    manifest["parts"][0]["sha256"] = file_sha256(part)
    _seal_manifest(manifest, root)
