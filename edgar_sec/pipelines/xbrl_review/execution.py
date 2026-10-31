"""Work-order execution for XBRL projections: chunks, attempts, snapshots.

Consumes a projection run's work order, solves each filing from its
corpus bundle, stages attempt artifacts, and publishes the merged
snapshot through the DAG machinery under the XBRL relation specs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.solve.cohort_scan import plan_cohort_scan
from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
from edgar_sec.engine.xbrl.solve.evidence_index import build_evidence_index
from edgar_sec.engine.xbrl.solve.solver import SOLVER_FINGERPRINT
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node
from edgar_sec.infra.storage.parquet import read_parquet_key_bounds, write_parquet_table
from edgar_sec.pipelines.xbrl_review.bundles import (
    cohort_entries,
    corpus_registry_path,
    load_filing,
    registry_filings,
)
from edgar_sec.pipelines.xbrl_review.paths import (
    CALCULATION_ARCS_FILE,
    HYPOTHESES_FILE,
    MANIFEST_FILE,
    PRESENTATION_ARCS_FILE,
    QUARANTINE_FILE,
    RULE_TRACE_FILE,
    SOLVED_NODES_FILE,
    snapshot_id_for,
    xbrl_paths,
    xbrl_run_paths,
)
from edgar_sec.pipelines.xbrl_review.review import build_engine_stack, solve_filing
from edgar_sec.pipelines.xbrl_review.schemas import (
    CALCULATION_ARCS_SCHEMA,
    CALCULATION_ARCS_SCHEMA_VERSION,
    HYPOTHESES_SCHEMA,
    HYPOTHESES_SCHEMA_VERSION,
    PRESENTATION_ARCS_SCHEMA,
    PRESENTATION_ARCS_SCHEMA_VERSION,
    QUARANTINE_SCHEMA,
    QUARANTINE_SCHEMA_VERSION,
    RULE_TRACE_SCHEMA,
    RULE_TRACE_SCHEMA_VERSION,
    SOLVED_NODES_SCHEMA,
    SOLVED_NODES_SCHEMA_VERSION,
)
from edgar_sec.pipelines.xbrl_review.snapshot.specs import XBRL_RELATIONS

_RELATION_FILES = {
    "solved_nodes": SOLVED_NODES_FILE,
    "rule_trace": RULE_TRACE_FILE,
    "quarantine": QUARANTINE_FILE,
    "hypotheses": HYPOTHESES_FILE,
    "presentation_arcs": PRESENTATION_ARCS_FILE,
    "calculation_arcs": CALCULATION_ARCS_FILE,
}
_RELATION_SCHEMAS = {
    "solved_nodes": (SOLVED_NODES_SCHEMA, SOLVED_NODES_SCHEMA_VERSION),
    "rule_trace": (RULE_TRACE_SCHEMA, RULE_TRACE_SCHEMA_VERSION),
    "quarantine": (QUARANTINE_SCHEMA, QUARANTINE_SCHEMA_VERSION),
    "hypotheses": (HYPOTHESES_SCHEMA, HYPOTHESES_SCHEMA_VERSION),
    "presentation_arcs": (PRESENTATION_ARCS_SCHEMA, PRESENTATION_ARCS_SCHEMA_VERSION),
    "calculation_arcs": (CALCULATION_ARCS_SCHEMA, CALCULATION_ARCS_SCHEMA_VERSION),
}


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of one projection execution run."""

    run_id: str
    snapshot_id: str
    chunks: int
    filings: int
    solved_count: int
    quarantine_count: int
    hypotheses_count: int
    wall_ms: float


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _next_attempt_id(run_paths, chunk_id: str) -> str:
    chunk_dir = run_paths.chunk_dir(chunk_id)
    existing = []
    if chunk_dir.is_dir():
        for entry in chunk_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("attempt-"):
                suffix = entry.name.removeprefix("attempt-")
                if suffix.isdigit():
                    existing.append(int(suffix))
    return str(max(existing, default=0) + 1)


def _completed_attempt(run_paths, chunk_id: str) -> dict | None:
    pointer_path = run_paths.chunk_pointer_path(chunk_id)
    if not pointer_path.is_file():
        return None
    pointer = _read_json(pointer_path)
    if pointer.get("status") != "complete":
        return None
    manifest_path = run_paths.attempt_manifest_path(
        chunk_id, str(pointer.get("attempt_id", ""))
    )
    if not manifest_path.is_file():
        return None
    return _read_json(manifest_path)


def _write_attempt(run_paths, chunk_id: str, attempt_id: str, results) -> dict:
    solved = [record for result in results for record in result.solved]
    quarantine = [record for result in results for record in result.quarantine]
    hypotheses = [record for result in results for record in result.hypotheses]
    rule_trace = [record for result in results for record in result.rule_trace]
    presentation_arcs = [
        record for result in results for record in result.presentation_arcs
    ]
    calculation_arcs = [
        record for result in results for record in result.calculation_arcs
    ]
    tables = {
        "solved_nodes": (solved, SOLVED_NODES_SCHEMA, SOLVED_NODES_FILE),
        "rule_trace": (rule_trace, RULE_TRACE_SCHEMA, RULE_TRACE_FILE),
        "quarantine": (quarantine, QUARANTINE_SCHEMA, QUARANTINE_FILE),
        "hypotheses": (hypotheses, HYPOTHESES_SCHEMA, HYPOTHESES_FILE),
        "presentation_arcs": (
            presentation_arcs,
            PRESENTATION_ARCS_SCHEMA,
            PRESENTATION_ARCS_FILE,
        ),
        "calculation_arcs": (
            calculation_arcs,
            CALCULATION_ARCS_SCHEMA,
            CALCULATION_ARCS_FILE,
        ),
    }
    attempt_dir = run_paths.attempt_dir(chunk_id, attempt_id)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    for _name, (records, schema, filename) in tables.items():
        write_parquet_table(
            pa.Table.from_pylist([asdict(r) for r in records], schema=schema),
            attempt_dir / filename,
        )
    manifest = {
        "chunk_id": chunk_id,
        "attempt_id": attempt_id,
        "filings": len(results),
        "solved_count": len(solved),
        "quarantine_count": len(quarantine),
        "hypotheses_count": len(hypotheses),
        "rule_trace_count": len(rule_trace),
        "presentation_arcs_count": len(presentation_arcs),
        "calculation_arcs_count": len(calculation_arcs),
        "solver_fingerprint": SOLVER_FINGERPRINT,
    }
    atomic_write_json(attempt_dir / MANIFEST_FILE, manifest, indent=2)
    atomic_write_json(
        run_paths.chunk_pointer_path(chunk_id),
        {"chunk_id": chunk_id, "attempt_id": attempt_id, "status": "complete"},
        indent=2,
    )
    return manifest


def _merge_relation(run_paths, chunk_ids: list[str], spec) -> pa.Table:
    schema, _version = _RELATION_SCHEMAS[spec.name]
    filename = _RELATION_FILES[spec.name]
    rows: dict[tuple, dict] = {}
    for chunk_id in chunk_ids:
        pointer = _read_json(run_paths.chunk_pointer_path(chunk_id))
        attempt_dir = run_paths.attempt_dir(chunk_id, str(pointer["attempt_id"]))
        table_path = attempt_dir / filename
        if not table_path.is_file():
            continue
        for row in pq.read_table(table_path).to_pylist():
            key = tuple(row[field] for field in spec.primary_key)
            rows[key] = row
    merged = sorted(
        rows.values(),
        key=lambda row: tuple(str(row[field] or "") for field in spec.sort_order),
    )
    return pa.Table.from_pylist(merged, schema=schema)


def _publish_snapshot(
    *,
    artifacts_root: Path,
    run_id: str,
    branch_name: str,
    tables: dict[str, pa.Table],
) -> str:
    paths = xbrl_paths(artifacts_root)
    catalog = DAGCatalog(paths.snapshots_root)
    pointer = catalog.read_pointer(branch_name)
    parent_id = str(pointer["snapshot_id"]) if pointer else None
    parent_manifest = catalog.get_manifest(parent_id) if parent_id else None

    staged_dir = paths.snapshots_root / f".stage-{run_id}-{uuid.uuid4().hex[:8]}"
    staged_dir.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, tuple[PartDescriptor, ...]] = {}
    for spec in XBRL_RELATIONS:
        table = tables[spec.name]
        relation_dir = staged_dir / spec.name
        relation_dir.mkdir(parents=True, exist_ok=True)
        part_path = relation_dir / "part-00000.parquet"
        write_parquet_table(table, part_path)
        key_min = key_max = None
        if table.num_rows > 0:
            key_min, key_max = read_parquet_key_bounds(part_path, spec.primary_key[0])
        descriptors[spec.name] = (
            PartDescriptor(
                path=f"{spec.name}/part-00000.parquet",
                sha256=file_sha256(part_path),
                row_count=table.num_rows,
                byte_size=part_path.stat().st_size,
                key_min=key_min,
                key_max=key_max,
            ),
        )
    digest = ordered_parts_fingerprint(
        sorted(d.sha256 for parts in descriptors.values() for d in parts)
    )
    snapshot_id = snapshot_id_for(parent_id, digest)
    manifest = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="delta" if parent_id else "checkpoint",
        parents=(
            (ParentRef(parent_id, parent_manifest.logical_fingerprint),)
            if parent_id and parent_manifest
            else ()
        ),
        checkpoint_anchor_id=(
            parent_manifest.checkpoint_anchor_id if parent_manifest else snapshot_id
        ),
        lineage_depth=(parent_manifest.lineage_depth + 1) if parent_manifest else 0,
        created_at=datetime.now(timezone.utc).isoformat(),
        relations=descriptors,
        logical_fingerprint=digest,
        schema_versions={
            name: str(version) for name, (_s, version) in _RELATION_SCHEMAS.items()
        },
        metadata={"run_id": run_id, "source": "xbrl_review execution"},
    )
    publish_node(
        paths.snapshots_root,
        manifest,
        staged_dir=staged_dir,
        expected_parent_id=parent_id,
        branch_name=branch_name,
    )
    return snapshot_id


def execute_projection_run(
    run_id: str,
    *,
    artifacts_root: Path | str | None = None,
) -> ExecutionResult:
    """Execute one projected run's work order and publish its snapshot."""
    started = time.perf_counter()
    root = (
        Path(artifacts_root).expanduser().resolve()
        if artifacts_root
        else resolve_paths().artifacts_root.resolve()
    )
    run_paths = xbrl_run_paths(root, run_id)
    if not run_paths.work_order_path().is_file():
        raise ValueError(f"no work order for run {run_id}: run project first")
    projection = _read_json(run_paths.projection_manifest_path())
    chunk_size = int(projection["chunk_size"])
    branch_name = str(projection.get("branch") or "main")
    registry_path = corpus_registry_path(projection.get("source_ref"))

    work_rows = pq.read_table(run_paths.work_order_path()).to_pylist()
    work_rows.sort(key=lambda row: row["accession"])
    seeds_by_accession = {
        str(s.accession): s for s in registry_filings(registry_path=registry_path)
    }
    unknown = [
        r["accession"] for r in work_rows if r["accession"] not in seeds_by_accession
    ]
    if unknown:
        raise ValueError(
            "work order names accession(s) outside the projection registry: "
            + ", ".join(unknown)
        )
    seeds = tuple(seeds_by_accession[row["accession"]] for row in work_rows)

    resources = derive_resources()
    taxonomy, solver, counter, tokenizer, promoted_loaded = build_engine_stack(seeds)
    entries = cohort_entries(seeds, registry_path=registry_path)
    scan_plan = plan_cohort_scan(entries)
    evidence_index = build_evidence_index(
        entries, build_cohort_table(taxonomy, entries)
    )

    chunk_ids: list[str] = []
    totals = {"solved_count": 0, "quarantine_count": 0, "hypotheses_count": 0}
    for offset in range(0, len(work_rows), chunk_size):
        chunk_rows = work_rows[offset : offset + chunk_size]
        chunk_id = f"chunk-{offset // chunk_size:04d}"
        chunk_ids.append(chunk_id)
        resumed = _completed_attempt(run_paths, chunk_id)
        if resumed is not None:
            for key in totals:
                totals[key] += int(resumed[key])
            continue
        attempt_id = _next_attempt_id(run_paths, chunk_id)
        chunk_seeds = [seeds_by_accession[row["accession"]] for row in chunk_rows]
        results = []
        for batch_start in range(0, len(chunk_seeds), scan_plan.batch_cardinality):
            for seed in chunk_seeds[
                batch_start : batch_start + scan_plan.batch_cardinality
            ]:
                loaded = load_filing(seed, registry_path=registry_path)
                results.append(
                    solve_filing(
                        loaded,
                        solver=solver,
                        counter=counter,
                        tokenizer=tokenizer,
                        evidence_record=evidence_index.record(loaded.accession),
                    )
                )
            reclaim()
        manifest = _write_attempt(run_paths, chunk_id, attempt_id, results)
        for key in totals:
            totals[key] += int(manifest[key])

    tables = {
        spec.name: _merge_relation(run_paths, chunk_ids, spec)
        for spec in XBRL_RELATIONS
    }
    snapshot_id = _publish_snapshot(
        artifacts_root=root,
        run_id=run_id,
        branch_name=branch_name,
        tables=tables,
    )
    wall_ms = round((time.perf_counter() - started) * 1000.0, 1)
    run_manifest_path = run_paths.run_manifest_path()
    run_manifest = _read_json(run_manifest_path) if run_manifest_path.is_file() else {}
    run_manifest.update(
        {
            "run_id": run_id,
            "status": "executed",
            "snapshot_id": snapshot_id,
            "branch": branch_name,
            "chunks": len(chunk_ids),
            "attempts": len(chunk_ids),
            "filings": len(work_rows),
            "solved_count": totals["solved_count"],
            "quarantine_count": totals["quarantine_count"],
            "hypotheses_count": totals["hypotheses_count"],
            "wall_ms": wall_ms,
            "promoted_rules_loaded": promoted_loaded,
            "scan_batch_cardinality": scan_plan.batch_cardinality,
            "scan_worker_budget": scan_plan.worker_budget,
            "resource_threads": resources.threads,
            "resource_memory_limit": resources.memory_limit,
        }
    )
    atomic_write_json(run_manifest_path, run_manifest, indent=2)
    return ExecutionResult(
        run_id=run_id,
        snapshot_id=snapshot_id,
        chunks=len(chunk_ids),
        filings=len(work_rows),
        solved_count=totals["solved_count"],
        quarantine_count=totals["quarantine_count"],
        hypotheses_count=totals["hypotheses_count"],
        wall_ms=wall_ms,
    )


__all__ = ["ExecutionResult", "execute_projection_run"]
