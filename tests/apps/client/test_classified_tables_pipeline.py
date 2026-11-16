"""Facade classified tables: pipeline version over the DAG store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.apps.client.classified_tables import ClassifiedTable
from edgar_sec.apps.client.classified_tables_pipeline import (
    PipelineClassifiedTables,
    classified_tables_pipeline,
    default_store_root,
)
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node

_ACC = "0000000000-24-000001"
_OTHER = "0000000000-24-000099"
_SNAP = "tc-0123456789abcdef01234567"
_REGISTRY_HEX = "ad797b40" + "0" * 56
_REGISTRY_STATE = f"sha256:{_REGISTRY_HEX}"

_SCHEMAS: dict[str, pa.Schema] = {
    "run_provenance": pa.schema(
        [
            ("store_snapshot_id", pa.string()),
            ("plan_id", pa.string()),
            ("plan_format_version", pa.string()),
            ("run_output_version", pa.string()),
            ("source_snapshot_id", pa.string()),
            ("registry_state", pa.string()),
            ("normalize_version", pa.string()),
            ("renderer_version", pa.string()),
            ("merged_at", pa.string()),
            ("published_at", pa.string()),
            ("filing_count", pa.int64()),
            ("profile_count", pa.int64()),
            ("target_count", pa.int64()),
            ("work_item_count", pa.int64()),
            ("document_count", pa.int64()),
            ("geometry_count", pa.int64()),
            ("classified_count", pa.int64()),
        ]
    ),
    "provenance": pa.schema(
        [
            pa.field("plan_format_version", pa.string(), nullable=False),
            pa.field("plan_id", pa.string(), nullable=False),
            pa.field("registry_state", pa.string(), nullable=False),
            pa.field("source_snapshot_id", pa.string(), nullable=False),
            pa.field("normalize_version", pa.string(), nullable=False),
            pa.field("renderer_version", pa.string(), nullable=False),
            pa.field("created_at", pa.string(), nullable=False),
            pa.field("filing_count", pa.int64(), nullable=False),
            pa.field("profile_count", pa.int64(), nullable=False),
            pa.field("target_count", pa.int64(), nullable=False),
            pa.field("work_item_count", pa.int64(), nullable=False),
        ]
    ),
    "filings": pa.schema(
        [
            pa.field("accession", pa.string(), nullable=False),
            pa.field("cik", pa.int64(), nullable=True),
            pa.field("form", pa.string(), nullable=False),
            pa.field("filing_date", pa.string(), nullable=True),
            pa.field("stratum", pa.string(), nullable=True),
        ]
    ),
    "profile_application": pa.schema(
        [
            pa.field("accession", pa.string(), nullable=False),
            pa.field("family", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("vocabulary_seat", pa.string(), nullable=False),
        ]
    ),
    "document_targets": pa.schema(
        [
            pa.field("accession", pa.string(), nullable=False),
            pa.field("target_role", pa.string(), nullable=False),
            pa.field("target_type", pa.string(), nullable=False),
            pa.field("optional", pa.bool_(), nullable=False),
            pa.field("document_name", pa.string(), nullable=True),
            pa.field("geometry_expectation", pa.string(), nullable=False),
            pa.field("provenance_route", pa.string(), nullable=False),
        ]
    ),
    "work_items": pa.schema(
        [
            pa.field("work_item_id", pa.string(), nullable=False),
            pa.field("accession", pa.string(), nullable=False),
            pa.field("ordinal", pa.int64(), nullable=False),
        ]
    ),
    "filing_records": pa.schema(
        [
            pa.field("plan_id", pa.string(), nullable=False),
            pa.field("accession", pa.string(), nullable=False),
            pa.field("cik", pa.int64(), nullable=True),
            pa.field("form", pa.string(), nullable=False),
            pa.field("filing_date", pa.string(), nullable=True),
            pa.field("stratum", pa.string(), nullable=True),
            pa.field("source_snapshot_id", pa.string(), nullable=False),
            pa.field("registry_state", pa.string(), nullable=False),
            pa.field("normalize_version", pa.string(), nullable=False),
            pa.field("renderer_version", pa.string(), nullable=False),
            pa.field("document_count", pa.int64(), nullable=False),
            pa.field("geometry_count", pa.int64(), nullable=False),
            pa.field("classified_count", pa.int64(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("absence_reason", pa.string(), nullable=True),
        ]
    ),
    "geometry_inventory": pa.schema(
        [
            pa.field("plan_id", pa.string(), nullable=False),
            pa.field("accession", pa.string(), nullable=False),
            pa.field("source_document", pa.string(), nullable=False),
            pa.field("table_index", pa.int64(), nullable=False),
            pa.field("provenance_route", pa.string(), nullable=False),
        ]
    ),
    "classifications": pa.schema(
        [
            pa.field("plan_id", pa.string(), nullable=False),
            pa.field("accession", pa.string(), nullable=False),
            pa.field("source_document", pa.string(), nullable=False),
            pa.field("table_index", pa.int64(), nullable=False),
            pa.field("family", pa.string(), nullable=False),
            pa.field("flavor", pa.string(), nullable=True),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("tier", pa.string(), nullable=False),
            pa.field("score", pa.float64(), nullable=False),
            pa.field("assembled_family", pa.string(), nullable=True),
            pa.field("mechanism", pa.string(), nullable=True),
            pa.field("evidence", pa.string(), nullable=False),
        ]
    ),
}

_EVIDENCE = json.dumps({"group": "headers", "detail": "row labels", "points": 4.5})


def _rows() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {name: [] for name in _SCHEMAS}
    rows["run_provenance"] = [
        {
            "store_snapshot_id": _SNAP,
            "plan_id": "plan-1",
            "plan_format_version": "1.0.0",
            "run_output_version": "1.0.0",
            "source_snapshot_id": "acq-20261114-007",
            "registry_state": _REGISTRY_STATE,
            "normalize_version": "normalize-v3",
            "renderer_version": "renderer-v2",
            "merged_at": "2026-11-15T03:59:00+00:00",
            "published_at": "2026-11-15T04:00:00+00:00",
            "filing_count": 2,
            "profile_count": 1,
            "target_count": 2,
            "work_item_count": 2,
            "document_count": 2,
            "geometry_count": 3,
            "classified_count": 2,
        }
    ]
    rows["provenance"] = [
        {
            "plan_format_version": "1.0.0",
            "plan_id": "plan-1",
            "registry_state": _REGISTRY_STATE,
            "source_snapshot_id": "acq-20261114-007",
            "normalize_version": "normalize-v3",
            "renderer_version": "renderer-v2",
            "created_at": "2026-11-15T03:58:00+00:00",
            "filing_count": 2,
            "profile_count": 1,
            "target_count": 2,
            "work_item_count": 2,
        }
    ]
    filing = {
        "cik": 1,
        "form": "10-K",
        "filing_date": "2024-03-01",
        "stratum": "annual",
    }
    rows["filings"] = [
        {"accession": _ACC, **filing},
        {"accession": _OTHER, **filing},
    ]
    record = {
        "plan_id": "plan-1",
        "source_snapshot_id": "acq-20261114-007",
        "registry_state": _REGISTRY_STATE,
        "normalize_version": "normalize-v3",
        "renderer_version": "renderer-v2",
        **filing,
    }
    rows["filing_records"] = [
        {
            "accession": _ACC,
            "document_count": 1,
            "geometry_count": 2,
            "classified_count": 2,
            "status": "classified",
            "absence_reason": None,
            **record,
        },
        {
            "accession": _OTHER,
            "document_count": 1,
            "geometry_count": 0,
            "classified_count": 0,
            "status": "no_geometries",
            "absence_reason": "no tables found",
            **record,
        },
    ]
    rows["geometry_inventory"] = [
        {
            "plan_id": "plan-1",
            "accession": _ACC,
            "source_document": "primary",
            "table_index": 1,
            "provenance_route": "render_to_txt",
        },
        {
            "plan_id": "plan-1",
            "accession": _ACC,
            "source_document": "ex13.htm",
            "table_index": 0,
            "provenance_route": "render_to_txt",
        },
    ]
    rows["classifications"] = [
        {
            "plan_id": "plan-1",
            "accession": _ACC,
            "source_document": "primary",
            "table_index": 1,
            "family": "balance_sheet",
            "flavor": "statement",
            "kind": "table",
            "tier": "assigned",
            "score": 4.5,
            "assembled_family": None,
            "mechanism": None,
            "evidence": _EVIDENCE,
        },
        {
            "plan_id": "plan-1",
            "accession": _ACC,
            "source_document": "ex13.htm",
            "table_index": 0,
            "family": "income_statement",
            "flavor": "statement",
            "kind": "table",
            "tier": "assigned",
            "score": 3.25,
            "assembled_family": None,
            "mechanism": None,
            "evidence": _EVIDENCE,
        },
    ]
    return rows


def _store(root: Path) -> Path:
    dataset = root / "table_classification"
    snapshots_root = dataset / "snapshots"
    staged = root / "staging" / "snapshot"
    staged.mkdir(parents=True)
    rows = _rows()
    descriptors: dict[str, PartDescriptor] = {}
    for name, schema in _SCHEMAS.items():
        table = pa.Table.from_pylist(rows[name], schema=schema)
        part = staged / f"{name}.parquet"
        pq.write_table(table, part)
        descriptors[name] = PartDescriptor(
            path=f"{_SNAP}/{name}.parquet",
            sha256=file_sha256(part),
            row_count=table.num_rows,
            byte_size=part.stat().st_size,
        )
    manifest = DAGNodeManifest(
        snapshot_id=_SNAP,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=_SNAP,
        lineage_depth=0,
        created_at="2026-11-15T04:00:00+00:00",
        relations={name: (descriptors[name],) for name in _SCHEMAS},
        logical_fingerprint=ordered_parts_fingerprint(
            [descriptors[name].sha256 for name in _SCHEMAS]
        ),
        schema_versions={name: "1" for name in _SCHEMAS},
        metadata={"plan_id": "plan-1"},
    )
    publish_node(snapshots_root, manifest, staged_dir=staged, branch_name="main")
    return dataset


def _filing(accession: str = _ACC) -> FilingAggregate:
    def _boom(filing: FilingAggregate) -> bytes:
        raise AssertionError("pipeline version must never compute on demand")

    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="10-K",
        filing_date="2024-03-01",
        primary_document_path="acme.htm",
        fetcher=_boom,
    )


def test_pipeline_reads_rows_with_provenance_and_stamp(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = classified_tables_pipeline(_filing(), store_root=store)
    assert isinstance(result, PipelineClassifiedTables)
    assert result.store_present is True
    assert result.filing_present is True
    assert result.origin == "pipeline"
    assert result.snapshot_id == _SNAP
    assert result.source_snapshot_id == "acq-20261114-007"
    assert result.plan_id == "plan-1"
    assert result.registry_state == _REGISTRY_STATE
    assert result.normalize_version == "normalize-v3"
    assert result.renderer_version == "renderer-v2"
    assert result.plan_format_version == "1.0.0"
    assert result.run_output_version == "1.0.0"
    assert result.stamp == (
        f"classified-v1;registry={_REGISTRY_HEX}"
        ";normalize=normalize-v3;renderer=renderer-v2"
    )
    assert [(row.source_document, row.table_index) for row in result.tables] == [
        ("ex13.htm", 0),
        ("primary", 1),
    ]
    first = result.tables[0]
    assert (first.family, first.tier, first.score) == (
        "income_statement",
        "assigned",
        3.25,
    )
    assert all(row.origin == "pipeline" for row in result.tables)
    assert all(row.stamp == result.stamp for row in result.tables)
    assert result.classified_count == 2
    assert len(result.tables) == result.classified_count


def test_pipeline_rows_match_the_fast_served_shape(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = classified_tables_pipeline(_ACC, store_root=store)
    fast = ClassifiedTable(
        table_index=0,
        source_document="ex13.htm",
        family="income_statement",
        tier="assigned",
        score=3.25,
        origin="fast",
        stamp=result.stamp or "",
    )
    row = result.tables[0]
    core = (row.table_index, row.source_document, row.family, row.tier, row.score)
    assert core == (
        fast.table_index,
        fast.source_document,
        fast.family,
        fast.tier,
        fast.score,
    )
    assert fast.origin == "fast"
    assert row.origin != fast.origin


def test_absent_store_is_honest_absence_and_never_computes(
    tmp_path: Path,
) -> None:
    result = classified_tables_pipeline(_filing(), store_root=tmp_path / "nope")
    assert result.store_present is False
    assert result.filing_present is False
    assert result.tables == ()
    assert result.snapshot_id is None
    assert result.stamp is None


def test_absent_filing_is_honest_absence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = classified_tables_pipeline(
        _filing("0000000000-24-000555"), store_root=store
    )
    assert result.store_present is True
    assert result.filing_present is False
    assert result.classified_count is None
    assert result.tables == ()
    assert result.snapshot_id == _SNAP


def test_filing_without_classifications_is_present(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = classified_tables_pipeline(_OTHER, store_root=store)
    assert result.store_present is True
    assert result.filing_present is True
    assert result.classified_count == 0
    assert result.tables == ()


def test_pipeline_read_is_read_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot_dir = store / "snapshots" / _SNAP
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in snapshot_dir.iterdir()
    }
    classified_tables_pipeline(_filing(), store_root=store)
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in snapshot_dir.iterdir()
    }
    assert after == before


def test_facade_serves_the_pipeline_version(tmp_path: Path) -> None:
    _store(tmp_path)
    assert default_store_root(tmp_path) == tmp_path / "table_classification"
    result = Edgar(artifacts_root=tmp_path).classified_tables_from_store(_filing())
    assert result.store_present is True
    assert len(result.tables) == 2
    assert result.origin == "pipeline"
