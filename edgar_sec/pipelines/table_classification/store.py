"""Build and publish of the classification Parquet DAG store.

The store republishes one plan bundle plus the merger's verified merged
output as one checkpoint node, content-addressed, CAS-guarded on the tip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.infra.storage.dag.publication import publish_node, read_pointer
from edgar_sec.infra.storage.parquet import (
    read_parquet_key_bounds,
    read_parquet_table,
    write_parquet_table,
)

from .paths import ClassificationPaths
from .schemas import (
    OUTPUT_RELATION_SCHEMAS,
    OUTPUT_RELATIONS,
    PLAN_RELATION_SCHEMAS,
    PLAN_RELATIONS,
)
from .specs import STORE_RELATION_SPECS, STORE_SCHEMA_VERSIONS

_SPEC_BY_NAME = {spec.name: spec for spec in STORE_RELATION_SPECS}


class StoreInputError(RuntimeError):
    """The plan bundle or merged output fails the store's input checks."""


@dataclass(frozen=True, slots=True)
class StorePublishResult:
    """Outcome of one store publish attempt against the branch tip."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None
    filing_count: int = 0
    geometry_count: int = 0
    classified_count: int = 0


@dataclass(frozen=True, slots=True)
class _RunInputs:
    """One run's verified inputs: plan rows, output tables, manifest."""

    provenance: dict
    manifest: dict
    tables: dict[str, pa.Table]
    digests: dict[str, str]


def store_tip(paths: ClassificationPaths, branch: str = "main") -> str | None:
    """The branch tip snapshot id, or ``None`` when no store is published."""
    catalog_file = DAGPaths(paths.snapshots_root).catalog_file
    if not catalog_file.is_file():
        return None
    pointer = read_pointer(paths.snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def derive_store_snapshot_id(inputs: _RunInputs) -> str:
    """Content identity: source snapshot, registry, plan, relation digests."""
    provenance = inputs.provenance
    fingerprint = sha256_text(
        canonical_json(
            {
                "source_snapshot_id": provenance["source_snapshot_id"],
                "registry_state": provenance["registry_state"],
                "plan_id": provenance["plan_id"],
                "digests": dict(sorted(inputs.digests.items())),
            }
        )
    )
    return f"tc-{fingerprint[:24]}"


def publish_merged_run(
    paths: ClassificationPaths,
    plan_id: str,
    *,
    published_at: datetime,
    branch: str = "main",
) -> StorePublishResult:
    """Publish one merged run as the next store checkpoint snapshot.

    The snapshot id is content-derived; republishing the identical run
    over the same tip is a no-op that leaves the tip unmoved.
    """
    inputs = _read_inputs(paths, plan_id)
    tip = store_tip(paths, branch)
    snapshot_id = derive_store_snapshot_id(inputs)
    counts = _counts(inputs)
    if snapshot_id == tip:
        return StorePublishResult(
            published=False, snapshot_id=None, tip_before=tip, **counts
        )
    tables = _sorted_tables(inputs)
    tables["evidence"] = _evidence_table(tables["classifications"])
    tables["assembled_tables"] = _assembled_table(tables["classifications"])
    tables["run_provenance"] = _provenance_table(inputs, snapshot_id, published_at)
    staging = paths.transient_dir(plan_id) / f"store-{snapshot_id}"
    staged_dir = staging / "snapshot"
    staged_dir.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, PartDescriptor] = {}
    for spec in STORE_RELATION_SPECS:
        part_file = staged_dir / f"{spec.name}.parquet"
        write_parquet_table(tables[spec.name], part_file)
        key_min, key_max = read_parquet_key_bounds(part_file, spec.primary_key[0])
        descriptors[spec.name] = PartDescriptor(
            path=f"{snapshot_id}/{spec.name}.parquet",
            sha256=file_sha256(part_file),
            row_count=tables[spec.name].num_rows,
            byte_size=part_file.stat().st_size,
            key_min=key_min,
            key_max=key_max,
        )
    manifest = _manifest(paths, snapshot_id, tip, descriptors, inputs, published_at)
    publish_node(
        paths.snapshots_root,
        manifest,
        staged_dir=staged_dir,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return StorePublishResult(
        published=True, snapshot_id=snapshot_id, tip_before=tip, **counts
    )


def _read_inputs(paths: ClassificationPaths, plan_id: str) -> _RunInputs:
    """Read and cross-verify the plan bundle and the merged output."""
    tables: dict[str, pa.Table] = {}
    digests: dict[str, str] = {}
    for name in PLAN_RELATIONS:
        file = paths.plan_relation_path(plan_id, name)
        if not file.is_file():
            raise StoreInputError(f"plan relation missing: {file}")
        table = read_parquet_table(file)
        if not table.schema.equals(PLAN_RELATION_SCHEMAS[name]):
            raise StoreInputError(f"plan relation {name} schema mismatch")
        tables[name] = table
        digests[name] = file_sha256(file)
    provenance_rows = tables["provenance"].to_pylist()
    if len(provenance_rows) != 1:
        raise StoreInputError("plan provenance must carry exactly one row")
    provenance = provenance_rows[0]
    if provenance["plan_id"] != plan_id:
        raise StoreInputError("plan provenance plan_id does not match the bundle")

    merged_dir = paths.merged_dir(plan_id)
    manifest_file = merged_dir / "run_manifest.json"
    if not manifest_file.is_file():
        raise StoreInputError(f"run manifest missing: {manifest_file}")
    manifest = json.loads(manifest_file.read_text())
    if manifest.get("plan_id") != plan_id:
        raise StoreInputError("run manifest plan_id does not match the plan")
    for field in ("source_snapshot_id", "registry_state"):
        if manifest.get(field) != provenance[field]:
            raise StoreInputError(f"run manifest {field} does not match the plan")
    for name in OUTPUT_RELATIONS:
        file = merged_dir / f"{name}.parquet"
        if not file.is_file():
            raise StoreInputError(f"merged relation missing: {file}")
        digest = file_sha256(file)
        recorded = manifest.get("relations", {}).get(name, {})
        if recorded.get("sha256") != digest:
            raise StoreInputError(f"merged relation {name} digest mismatch")
        table = read_parquet_table(file)
        if not table.schema.equals(OUTPUT_RELATION_SCHEMAS[name]):
            raise StoreInputError(f"merged relation {name} schema mismatch")
        if recorded.get("rows") != table.num_rows:
            raise StoreInputError(f"merged relation {name} row count mismatch")
        tables[name] = table
        digests[name] = digest
    return _RunInputs(
        provenance=provenance, manifest=manifest, tables=tables, digests=digests
    )


def _counts(inputs: _RunInputs) -> dict[str, int]:
    records = inputs.tables["filing_records"].to_pylist()
    return {
        "filing_count": len(records),
        "geometry_count": sum(int(r["geometry_count"]) for r in records),
        "classified_count": sum(int(r["classified_count"]) for r in records),
    }


def _sorted_tables(inputs: _RunInputs) -> dict[str, pa.Table]:
    tables: dict[str, pa.Table] = {}
    for name, table in inputs.tables.items():
        spec = _SPEC_BY_NAME[name]
        rows = table.to_pylist()
        rows.sort(
            key=lambda row: tuple(
                row[col] if row[col] is not None else "" for col in spec.sort_order
            )
        )
        tables[name] = pa.Table.from_pylist(rows, schema=spec.schema)
    return tables


def _evidence_table(classifications: pa.Table) -> pa.Table:
    """Decompose the classifications' evidence JSON into point rows."""
    rows: list[dict] = []
    for record in classifications.to_pylist():
        try:
            points = json.loads(record["evidence"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise StoreInputError("classification evidence is not valid JSON") from exc
        if not isinstance(points, list):
            raise StoreInputError("classification evidence is not a point list")
        for ordinal, point in enumerate(points):
            rows.append(
                {
                    "plan_id": record["plan_id"],
                    "accession": record["accession"],
                    "source_document": record["source_document"],
                    "table_index": record["table_index"],
                    "ordinal": ordinal,
                    "group": point["group"],
                    "detail": point["detail"],
                    "points": float(point["points"]),
                }
            )
    spec = _SPEC_BY_NAME["evidence"]
    rows.sort(key=lambda row: tuple(row[col] for col in spec.sort_order))
    return pa.Table.from_pylist(rows, schema=spec.schema)


def _assembled_table(classifications: pa.Table) -> pa.Table:
    """Project the classifications that assembly claimed, one row each."""
    rows = [
        {
            "plan_id": record["plan_id"],
            "accession": record["accession"],
            "source_document": record["source_document"],
            "table_index": record["table_index"],
            "family": record["family"],
            "flavor": record["flavor"],
            "assembled_family": record["assembled_family"],
            "mechanism": record["mechanism"],
        }
        for record in classifications.to_pylist()
        if record["assembled_family"] is not None
    ]
    spec = _SPEC_BY_NAME["assembled_tables"]
    rows.sort(key=lambda row: tuple(row[col] for col in spec.sort_order))
    return pa.Table.from_pylist(rows, schema=spec.schema)


def _provenance_table(
    inputs: _RunInputs, snapshot_id: str, published_at: datetime
) -> pa.Table:
    provenance = inputs.provenance
    records = inputs.tables["filing_records"].to_pylist()
    row = {
        "store_snapshot_id": snapshot_id,
        "plan_id": provenance["plan_id"],
        "plan_format_version": provenance["plan_format_version"],
        "run_output_version": inputs.manifest["run_output_version"],
        "source_snapshot_id": provenance["source_snapshot_id"],
        "registry_state": provenance["registry_state"],
        "normalize_version": provenance["normalize_version"],
        "renderer_version": provenance["renderer_version"],
        "merged_at": inputs.manifest["merged_at"],
        "published_at": published_at.isoformat(),
        "filing_count": int(provenance["filing_count"]),
        "profile_count": int(provenance["profile_count"]),
        "target_count": int(provenance["target_count"]),
        "work_item_count": int(provenance["work_item_count"]),
        "document_count": sum(int(r["document_count"]) for r in records),
        "geometry_count": sum(int(r["geometry_count"]) for r in records),
        "classified_count": sum(int(r["classified_count"]) for r in records),
    }
    spec = _SPEC_BY_NAME["run_provenance"]
    return pa.Table.from_pylist([row], schema=spec.schema)


def _manifest(
    paths: ClassificationPaths,
    snapshot_id: str,
    tip: str | None,
    descriptors: dict[str, PartDescriptor],
    inputs: _RunInputs,
    published_at: datetime,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
        parent = catalog.get_manifest(tip)
        parents = (
            ParentRef(
                snapshot_id=tip,
                manifest_sha256=catalog.get_manifest_sha256(tip) or "",
            ),
        )
        if parent is not None:
            depth = parent.lineage_depth + 1
    relations = {spec.name: (descriptors[spec.name],) for spec in STORE_RELATION_SPECS}
    fingerprint = ordered_parts_fingerprint(
        [descriptors[spec.name].sha256 for spec in STORE_RELATION_SPECS]
    )
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint",
        parents=parents,
        checkpoint_anchor_id=snapshot_id,
        lineage_depth=depth,
        created_at=published_at.isoformat(),
        relations=relations,
        logical_fingerprint=fingerprint,
        schema_versions=dict(STORE_SCHEMA_VERSIONS),
        metadata={
            "plan_id": inputs.provenance["plan_id"],
            "source_snapshot_id": inputs.provenance["source_snapshot_id"],
            "registry_state": inputs.provenance["registry_state"],
        },
    )


__all__ = [
    "StoreInputError",
    "StorePublishResult",
    "derive_store_snapshot_id",
    "publish_merged_run",
    "store_tip",
]
