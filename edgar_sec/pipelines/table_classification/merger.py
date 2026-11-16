"""Run merge: validate every work item, then assemble run outputs.

The merger is the only component that assembles a run's outputs, and
it assembles them only once every planned work item has validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.parquet import read_parquet_table, write_parquet_table

from .paths import ClassificationPaths
from .planner import Plan
from .schemas import (
    GEOMETRY_KEY,
    OUTPUT_RELATIONS,
    OUTPUT_RELATION_SCHEMAS,
    RUN_OUTPUT_VERSION,
)

__all__ = ["MergeError", "MergeReport", "merge_run"]


class MergeError(RuntimeError):
    """Merge rejected; the run outputs were not assembled."""


@dataclass(frozen=True, slots=True)
class MergeReport:
    """Result of one merge: counts and the merged directory."""

    plan_id: str
    merged_dir: Path
    filing_count: int
    geometry_count: int
    classified_count: int


def _read_work(
    paths: ClassificationPaths, plan: Plan, work_item_id: str
) -> dict[str, list[dict]]:
    out_dir = paths.work_dir(plan.plan_id, work_item_id)
    relations: dict[str, list[dict]] = {}
    for relation in OUTPUT_RELATIONS:
        target = out_dir / f"{relation}.parquet"
        if not target.is_file():
            raise MergeError(f"work item {work_item_id} is missing {relation}")
        relations[relation] = read_parquet_table(target).to_pylist()
    return relations


def merge_run(paths: ClassificationPaths, plan: Plan) -> MergeReport:
    """Validate one run's staged work and write its merged outputs."""
    collected: dict[str, list[dict]] = {relation: [] for relation in OUTPUT_RELATIONS}
    for item in sorted(plan.work_items, key=lambda entry: entry.ordinal):
        relations = _read_work(paths, plan, item.work_item_id)
        records = relations["filing_records"]
        if len(records) != 1 or records[0]["accession"] != item.accession:
            raise MergeError(f"work item {item.work_item_id} has a bad filing record")
        record = records[0]
        geometries = relations["geometry_inventory"]
        classifications = relations["classifications"]
        if record["geometry_count"] != len(geometries):
            raise MergeError(f"geometry count mismatch for {item.accession}")
        if record["classified_count"] != len(classifications):
            raise MergeError(f"classification count mismatch for {item.accession}")
        geometry_keys = {
            tuple(row[name] for name in GEOMETRY_KEY) for row in geometries
        }
        classification_keys = {
            tuple(row[name] for name in GEOMETRY_KEY) for row in classifications
        }
        if geometry_keys != classification_keys:
            raise MergeError(f"unclassified geometries for {item.accession}")
        for relation in OUTPUT_RELATIONS:
            collected[relation].extend(relations[relation])
    all_geometry_keys = [
        tuple(row[name] for name in GEOMETRY_KEY)
        for row in collected["geometry_inventory"]
    ]
    if len(set(all_geometry_keys)) != len(all_geometry_keys):
        raise MergeError("duplicate geometry keys across the run")
    merged_dir = paths.merged_dir(plan.plan_id)
    merged_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, dict] = {}
    for relation, rows in collected.items():
        schema = OUTPUT_RELATION_SCHEMAS[relation]
        table = pa.table(
            {name: [row[name] for row in rows] for name in schema.names},
            schema=schema,
        )
        target = merged_dir / f"{relation}.parquet"
        write_parquet_table(table, target)
        digests[relation] = {"rows": len(rows), "sha256": file_sha256(target)}
    manifest = {
        "plan_id": plan.plan_id,
        "run_output_version": RUN_OUTPUT_VERSION,
        "source_snapshot_id": plan.provenance["source_snapshot_id"],
        "registry_state": plan.provenance["registry_state"],
        "merged_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "relations": digests,
    }
    atomic_write_text(merged_dir / "run_manifest.json", canonical_json(manifest))
    return MergeReport(
        plan_id=plan.plan_id,
        merged_dir=merged_dir,
        filing_count=len(collected["filing_records"]),
        geometry_count=len(collected["geometry_inventory"]),
        classified_count=len(collected["classifications"]),
    )
