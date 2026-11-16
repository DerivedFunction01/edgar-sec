"""Store publish: checkpoint shape, input verification, no-op republish."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.schemas import (
    OUTPUT_RELATION_SCHEMAS,
    PLAN_RELATION_SCHEMAS,
)
from edgar_sec.pipelines.table_classification.store import (
    StoreInputError,
    publish_merged_run,
    store_tip,
)

PUBLISHED_AT = datetime(2026, 11, 15, 4, 30, tzinfo=UTC)
PLAN_ID = "tcplan-0123456789abcdef"
ACCESSION = "0000000001-26-000001"
EVIDENCE = json.dumps([{"group": "caption", "detail": "balance sheet", "points": 6.0}])

EXPECTED_RELATIONS = {
    "run_provenance",
    "provenance",
    "filings",
    "profile_application",
    "document_targets",
    "work_items",
    "filing_records",
    "geometry_inventory",
    "classifications",
    "evidence",
    "assembled_tables",
}


def _plan_rows(plan_id: str = PLAN_ID) -> dict[str, list[dict]]:
    return {
        "provenance": [
            {
                "plan_format_version": "1.0.0",
                "plan_id": plan_id,
                "registry_state": "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec",
                "source_snapshot_id": "acq-snapshot-1",
                "normalize_version": "norm-1",
                "renderer_version": "rend-1",
                "created_at": "2026-11-15T04:00:00Z",
                "filing_count": 1,
                "profile_count": 1,
                "target_count": 1,
                "work_item_count": 1,
            }
        ],
        "filings": [
            {
                "accession": ACCESSION,
                "cik": 1,
                "form": "10-K",
                "filing_date": "2026-02-01",
                "stratum": "annual",
            }
        ],
        "profile_application": [
            {
                "accession": ACCESSION,
                "family": "balance_sheet",
                "kind": "statement",
                "vocabulary_seat": "primary_statement",
            }
        ],
        "document_targets": [
            {
                "accession": ACCESSION,
                "target_role": "primary",
                "target_type": "10-K",
                "optional": False,
                "document_name": "filing.htm",
                "geometry_expectation": "expected",
                "provenance_route": "render_to_txt",
            }
        ],
        "work_items": [
            {
                "work_item_id": "wi-0123456789abcdef",
                "accession": ACCESSION,
                "ordinal": 0,
            }
        ],
    }


def _output_rows(
    plan_id: str = PLAN_ID, score: float = 12.5, evidence: str = EVIDENCE
) -> dict[str, list[dict]]:
    return {
        "filing_records": [
            {
                "plan_id": plan_id,
                "accession": ACCESSION,
                "cik": 1,
                "form": "10-K",
                "filing_date": "2026-02-01",
                "stratum": "annual",
                "source_snapshot_id": "acq-snapshot-1",
                "registry_state": "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec",
                "normalize_version": "norm-1",
                "renderer_version": "rend-1",
                "document_count": 1,
                "geometry_count": 2,
                "classified_count": 1,
                "status": "classified",
                "absence_reason": None,
            }
        ],
        "geometry_inventory": [
            {
                "plan_id": plan_id,
                "accession": ACCESSION,
                "source_document": "primary",
                "table_index": 0,
                "provenance_route": "render_to_txt",
            },
            {
                "plan_id": plan_id,
                "accession": ACCESSION,
                "source_document": "primary",
                "table_index": 1,
                "provenance_route": "render_to_txt",
            },
        ],
        "classifications": [
            {
                "plan_id": plan_id,
                "accession": ACCESSION,
                "source_document": "primary",
                "table_index": 0,
                "family": "balance_sheet",
                "flavor": None,
                "kind": "statement",
                "tier": "confident",
                "score": score,
                "assembled_family": "balance_sheet",
                "mechanism": "assembly",
                "evidence": evidence,
            }
        ],
    }


def write_run(
    paths: ClassificationPaths,
    plan_id: str = PLAN_ID,
    *,
    score: float = 12.5,
    evidence: str = EVIDENCE,
    registry_state: str = "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec",
) -> None:
    """Write one plan bundle plus its merged output, merger-style."""
    plan_rows = _plan_rows(plan_id)
    if (
        registry_state
        != "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec"
    ):
        plan_rows["provenance"][0]["registry_state"] = registry_state
    plan_dir = paths.plan_dir(plan_id)
    plan_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in plan_rows.items():
        table = pa.Table.from_pylist(rows, schema=PLAN_RELATION_SCHEMAS[name])
        write_parquet_table(table, plan_dir / f"{name}.parquet")
    (plan_dir / "plan.json").write_text(json.dumps({"plan_id": plan_id}))

    output_rows = _output_rows(plan_id, score=score, evidence=evidence)
    merged_dir = paths.merged_dir(plan_id)
    merged_dir.mkdir(parents=True, exist_ok=True)
    digests = {}
    for name, rows in output_rows.items():
        target = merged_dir / f"{name}.parquet"
        table = pa.Table.from_pylist(rows, schema=OUTPUT_RELATION_SCHEMAS[name])
        write_parquet_table(table, target)
        digests[name] = {"rows": len(rows), "sha256": file_sha256(target)}
    manifest = {
        "plan_id": plan_id,
        "run_output_version": "1.0.0",
        "source_snapshot_id": "acq-snapshot-1",
        "registry_state": "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec",
        "merged_at": "2026-11-15T04:20:00Z",
        "relations": digests,
    }
    (merged_dir / "run_manifest.json").write_text(json.dumps(manifest))


def _paths(tmp_path: Path) -> ClassificationPaths:
    return ClassificationPaths(artifacts_root=tmp_path)


def test_publish_checkpoint_carries_provenance_and_relations(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths)
    result = publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    assert result.published
    assert result.snapshot_id is not None
    assert result.snapshot_id.startswith("tc-")
    assert result.filing_count == 1
    assert result.geometry_count == 2
    assert result.classified_count == 1
    assert store_tip(paths) == result.snapshot_id

    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    manifest = catalog.get_manifest(result.snapshot_id)
    assert manifest is not None
    assert manifest.kind == "checkpoint"
    assert manifest.metadata["source_snapshot_id"] == "acq-snapshot-1"
    assert (
        manifest.metadata["registry_state"]
        == "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec"
    )
    assert manifest.metadata["plan_id"] == PLAN_ID
    assert set(manifest.relations) == EXPECTED_RELATIONS

    snapshot_dir = paths.snapshots_root / result.snapshot_id
    provenance = pq.read_table(snapshot_dir / "run_provenance.parquet").to_pylist()
    assert len(provenance) == 1
    row = provenance[0]
    assert row["plan_format_version"] == "1.0.0"
    assert row["run_output_version"] == "1.0.0"
    assert row["source_snapshot_id"] == "acq-snapshot-1"
    assert (
        row["registry_state"]
        == "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec"
    )
    assert row["normalize_version"] == "norm-1"
    assert row["renderer_version"] == "rend-1"
    assert row["merged_at"] == "2026-11-15T04:20:00Z"
    assert row["document_count"] == 1

    classifications = pq.read_table(
        snapshot_dir / "classifications.parquet"
    ).to_pylist()
    assert classifications[0]["evidence"] == EVIDENCE
    assert classifications[0]["assembled_family"] == "balance_sheet"

    evidence = pq.read_table(snapshot_dir / "evidence.parquet").to_pylist()
    assert len(evidence) == 1
    assert evidence[0]["group"] == "caption"
    assert evidence[0]["detail"] == "balance sheet"
    assert evidence[0]["points"] == 6.0
    assert evidence[0]["ordinal"] == 0

    assembled = pq.read_table(snapshot_dir / "assembled_tables.parquet").to_pylist()
    assert len(assembled) == 1
    assert assembled[0]["assembled_family"] == "balance_sheet"
    assert assembled[0]["mechanism"] == "assembly"
    assert assembled[0]["family"] == "balance_sheet"


def test_republish_identical_run_is_noop(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths)
    first = publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    second = publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    assert first.published
    assert not second.published
    assert store_tip(paths) == first.snapshot_id


def test_second_run_advances_tip_with_lineage(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths)
    first = publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    other_plan = "tcplan-fedcba9876543210"
    write_run(paths, other_plan, score=99.0)
    second = publish_merged_run(paths, other_plan, published_at=PUBLISHED_AT)
    assert second.published
    assert second.snapshot_id != first.snapshot_id
    assert second.tip_before == first.snapshot_id
    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    manifest = catalog.get_manifest(second.snapshot_id or "")
    assert manifest is not None
    assert manifest.parents[0].snapshot_id == first.snapshot_id
    assert manifest.lineage_depth == 1


def test_manifest_registry_mismatch_is_refused(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths, registry_state="other-registry")
    with pytest.raises(StoreInputError, match="registry_state"):
        publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    assert store_tip(paths) is None


def test_malformed_evidence_is_refused(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths, evidence="not-json")
    with pytest.raises(StoreInputError, match="evidence"):
        publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    assert store_tip(paths) is None


def test_merged_digest_mismatch_is_refused(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_run(paths)
    target = paths.merged_dir(PLAN_ID) / "classifications.parquet"
    rows = _output_rows(score=1.0)["classifications"]
    table = pa.Table.from_pylist(
        rows, schema=OUTPUT_RELATION_SCHEMAS["classifications"]
    )
    write_parquet_table(table, target)
    with pytest.raises(StoreInputError, match="digest mismatch"):
        publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    assert store_tip(paths) is None
