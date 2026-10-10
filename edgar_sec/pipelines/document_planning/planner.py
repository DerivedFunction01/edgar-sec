"""Match profile requests to pinned catalog and inventory evidence."""

from __future__ import annotations

import itertools
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogOccurrence,
    CatalogScope,
    CatalogScopeAccession,
    resolve_catalog_scope,
)
from edgar_sec.pipelines.document_planning.discovery import (
    DocumentPlanError,
)
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    CatalogAccessionScopeRow,
    InventoryEvidenceError,
    InventoryEvidenceSource,
    open_inventory_evidence,
)
from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    catalog_only_rows,
    inventory_rows,
)
from edgar_sec.pipelines.document_planning.paths import (
    DocumentPlanningPaths,
    plan_target_part_path,
    resolve_catalog_paths,
    resolve_document_planning_paths,
    resolve_inventory_paths,
)
from edgar_sec.pipelines.document_planning.profiles import (
    ProfileTarget,
    ResolvedProfile,
    compatible_with_catalog_only,
    load_profile,
    profile_digest,
    targets_for_form,
)
from edgar_sec.pipelines.document_planning.publication import publish_plan_bundle
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size
from edgar_sec.infra.storage.parquet import DEFAULT_COMPRESSION
from edgar_sec.pipelines.document_planning.schemas import (
    INVENTORY_RELATIONS,
    MATCHER_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)


class DocumentPlanningError(RuntimeError):
    """A target plan cannot be safely created from the selected evidence."""


@dataclass(frozen=True, slots=True)
class PlanResult:
    plan_id: str
    root: Path
    manifest: Mapping[str, Any]
    reused: bool


@dataclass(frozen=True, slots=True)
class CoveragePreflight:
    catalog_plan_id: str
    catalog_plan_digest: str
    snapshot_id: str
    snapshot_digest: str
    scoped_accessions: int
    indexed_accessions: int
    unindexed_accessions: int


@dataclass(slots=True)
class _Stats:
    statuses: Counter[str]
    origins: Counter[str]
    reasons: Counter[str]
    scoped_accessions: int = 0
    indexed_accessions: int = 0
    unindexed_accessions: int = 0
    matched_accessions: int = 0


def resolve_inventory_snapshot_id(
    requested: str | None, paths: DocumentPlanningPaths | None = None
) -> str | None:
    if requested is None:
        return None
    if requested != "current":
        if (
            not requested
            or requested in {".", ".."}
            or "/" in requested
            or "\\" in requested
        ):
            raise DocumentPlanningError("invalid inventory snapshot ID")
        return requested
    locations = paths or resolve_document_planning_paths()
    inventory_paths = resolve_inventory_paths(locations.artifacts_root)
    pointer = DAGCatalog(inventory_paths.snapshots_root, read_only=True).read_pointer(
        "main"
    )
    if pointer is None or not pointer.get("snapshot_id"):
        raise DocumentPlanningError(
            "inventory current branch has no published snapshot"
        )
    return str(pointer["snapshot_id"])


def coverage_preflight(
    catalog_plan_id: str,
    inventory_snapshot: str,
    paths: DocumentPlanningPaths | None = None,
) -> CoveragePreflight:
    locations = paths or resolve_document_planning_paths()
    catalog_scope = resolve_catalog_scope(
        catalog_plan_id, resolve_catalog_paths(locations.artifacts_root)
    )
    snapshot_id = resolve_inventory_snapshot_id(inventory_snapshot, locations)
    if snapshot_id is None:
        raise DocumentPlanningError("coverage preflight requires an inventory snapshot")
    evidence = _open_inventory(snapshot_id, locations)
    scoped = indexed = 0
    scope_rows = _inventory_scope_rows(catalog_scope.iter_accessions())
    try:
        for _accession, rows in itertools.groupby(
            evidence.stream(scope_rows), key=lambda row: row.accession
        ):
            first = next(rows)
            scoped += 1
            indexed += int(first.indexed)
    except InventoryEvidenceError as error:
        raise DocumentPlanningError(str(error)) from error
    return CoveragePreflight(
        catalog_plan_id,
        catalog_scope.pin.digest,
        snapshot_id,
        evidence.snapshot_digest,
        scoped,
        indexed,
        scoped - indexed,
    )


def create_document_plan(
    catalog_plan_id: str,
    profile_id: str,
    inventory_snapshot: str | None = None,
    paths: DocumentPlanningPaths | None = None,
) -> PlanResult:
    row_group_size = resolve_row_group_size()
    locations = paths or resolve_document_planning_paths()
    profile = load_profile(profile_id, locations.profiles_root)
    selected_snapshot = resolve_inventory_snapshot_id(inventory_snapshot, locations)
    if selected_snapshot is None and not compatible_with_catalog_only(profile):
        raise DocumentPlanningError(
            "catalog-only planning requires a primary-only target profile"
        )
    catalog_scope = resolve_catalog_scope(
        catalog_plan_id, resolve_catalog_paths(locations.artifacts_root)
    )
    inventory_source = (
        _open_inventory(selected_snapshot, locations)
        if selected_snapshot is not None
        else None
    )
    identity = {
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "row_group_size": row_group_size,
        "profile_digest": profile_digest(profile),
        "catalog_plan_id": catalog_scope.pin.catalog_plan_id,
        "catalog_plan_digest": catalog_scope.pin.digest,
        "inventory_snapshot_id": (
            inventory_source.snapshot_id if inventory_source is not None else None
        ),
        "inventory_snapshot_digest": (
            inventory_source.snapshot_digest if inventory_source is not None else None
        ),
    }
    plan_id = f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    locations.plans_root.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{plan_id}.staging-", dir=locations.plans_root)
    )
    stats = _Stats(Counter(), Counter(), Counter())
    try:
        rows = _iter_target_rows(
            plan_id, catalog_scope, inventory_source, profile, stats
        )
        parts = _write_target_parts(stage, rows, row_group_size)
        target_row_count = sum(stats.statuses.values())
        manifest: dict[str, Any] = {
            "plan_id": plan_id,
            "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "matcher_version": MATCHER_VERSION,
            "row_group_size": row_group_size,
            "profile_id": profile.profile_id,
            "profile_schema_version": profile.schema_version,
            "profile_version": profile.version,
            "profile_digest": profile.digest,
            "catalog_plan_id": catalog_scope.pin.catalog_plan_id,
            "catalog_plan_digest": catalog_scope.pin.digest,
            "inventory_snapshot_id": identity["inventory_snapshot_id"],
            "inventory_snapshot_digest": identity["inventory_snapshot_digest"],
            "plan_identity": identity,
            "target_row_count": target_row_count,
            "status_counts": dict(sorted(stats.statuses.items())),
            "origin_counts": dict(sorted(stats.origins.items())),
            "reason_counts": dict(sorted(stats.reasons.items())),
            "distinct_accession_coverage": {
                "catalog_scope": stats.scoped_accessions,
                "inventory_indexed": (
                    stats.indexed_accessions if inventory_source is not None else None
                ),
                "inventory_unindexed": (
                    stats.unindexed_accessions if inventory_source is not None else None
                ),
                "matched": stats.matched_accessions,
            },
            "parts": parts,
        }
        published = publish_plan_bundle(plan_id, identity, manifest, stage, locations)
        return PlanResult(
            published.plan_id,
            published.root,
            published.manifest,
            published.reused,
        )
    except (DocumentPlanError, InventoryEvidenceError, TargetMatchingError) as error:
        raise DocumentPlanningError(str(error)) from error
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _open_inventory(
    snapshot_id: str, locations: DocumentPlanningPaths
) -> InventoryEvidenceSource:
    inventory_paths = resolve_inventory_paths(locations.artifacts_root)
    return open_inventory_evidence(inventory_paths, snapshot_id, INVENTORY_RELATIONS)


def _inventory_scope_rows(
    accessions: Iterable[CatalogScopeAccession],
) -> Iterator[CatalogAccessionScopeRow]:
    for item in accessions:
        if item.filing_date is None:
            raise DocumentPlanningError(
                f"catalog accession lacks a filing date: {item.accession}"
            )
        yield CatalogAccessionScopeRow(
            str(AccessionNumber.from_any(item.accession)), item.form, item.filing_date
        )


def _iter_target_rows(
    plan_id: str,
    catalog_scope: CatalogScope,
    inventory: InventoryEvidenceSource | None,
    profile: ResolvedProfile,
    stats: _Stats,
) -> Iterator[dict[str, Any]]:
    if inventory is None:
        for accession in catalog_scope.iter_accessions():
            if accession.filing_date is None:
                raise DocumentPlanningError(
                    f"catalog accession lacks a filing date: {accession.accession}"
                )
            stats.scoped_accessions += 1
            targets = _requests_for(profile, accession.form)
            rows = catalog_only_rows(plan_id, accession, targets)
            yield from _account_rows(rows, stats)
            if any(row["status"] == "matched" for row in rows):
                stats.matched_accessions += 1
        return
    source_rows = inventory.stream(
        _inventory_scope_rows(catalog_scope.iter_accessions())
    )
    for _accession, grouped in itertools.groupby(
        source_rows, key=lambda row: row.accession
    ):
        evidence_rows = list(grouped)
        first = evidence_rows[0]
        stats.scoped_accessions += 1
        if first.indexed:
            stats.indexed_accessions += 1
        else:
            stats.unindexed_accessions += 1
        targets = _requests_for(profile, first.catalog_form)
        rows = inventory_rows(plan_id, evidence_rows, targets)
        yield from _account_rows(rows, stats)
        if any(row["status"] == "matched" for row in rows):
            stats.matched_accessions += 1


def _requests_for(profile: ResolvedProfile, form: str) -> tuple[ProfileTarget, ...]:
    targets = targets_for_form(profile, form)
    if not targets:
        raise DocumentPlanningError(
            f"profile {profile.profile_id!r} has no rule for catalog form {form!r}"
        )
    return tuple(sorted(targets, key=lambda item: item.request_id))


def _account_rows(
    rows: list[dict[str, Any]], stats: _Stats
) -> Iterator[dict[str, Any]]:
    for row in rows:
        stats.statuses[row["status"]] += 1
        stats.origins[row["source_origin"]] += 1
        if row["status_reason"] is not None:
            stats.reasons[row["status_reason"]] += 1
        yield row


def _write_target_parts(
    staging_root: Path, rows: Iterable[dict[str, Any]], row_group_size: int
) -> list[dict[str, Any]]:
    read_batch_size = resolve_read_batch_size()
    spool_root = Path(tempfile.mkdtemp(prefix=".rows-", dir=staging_root))
    spool_path = spool_root / "rows.parquet"
    writer = pq.ParquetWriter(
        spool_path, TARGET_SCHEMA, compression=DEFAULT_COMPRESSION
    )
    batch: list[dict[str, Any]] = []
    row_count = 0
    try:
        for row in rows:
            batch.append(row)
            row_count += 1
            if len(batch) == read_batch_size:
                writer.write_table(
                    pa.Table.from_pylist(batch, schema=TARGET_SCHEMA),
                    row_group_size=row_group_size,
                )
                batch.clear()
        if batch:
            writer.write_table(
                pa.Table.from_pylist(batch, schema=TARGET_SCHEMA),
                row_group_size=row_group_size,
            )
    finally:
        writer.close()
    if row_count == 0:
        shutil.rmtree(spool_root)
        return []
    try:
        parts = _sort_and_write_parts(spool_path, staging_root, row_group_size)
    finally:
        shutil.rmtree(spool_root, ignore_errors=True)
    return parts


def _sort_and_write_parts(
    spool_path: Path, staging_root: Path, row_group_size: int
) -> list[dict[str, Any]]:
    read_batch_size = resolve_read_batch_size()
    parts: list[dict[str, Any]] = []
    current_form: str | None = None
    buffered: list[pa.Table] = []
    buffered_rows = 0
    next_part: dict[str, int] = {}

    def flush() -> None:
        nonlocal buffered, buffered_rows
        if not buffered or current_form is None:
            return
        table = pa.concat_tables(buffered).cast(TARGET_SCHEMA)
        part_index = next_part.get(current_form, 0)
        relative = plan_target_part_path(current_form, part_index)
        path = staging_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            table,
            path,
            compression=DEFAULT_COMPRESSION,
            row_group_size=row_group_size,
        )
        parts.append(
            {
                "path": relative,
                "form": current_form,
                "rows": table.num_rows,
                "byte_size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
        next_part[current_form] = part_index + 1
        buffered = []
        buffered_rows = 0

    with connect() as con:
        reader = con.execute(
            "SELECT * FROM read_parquet(?) "
            "ORDER BY form, accession, request_id, inventory_entry_id NULLS FIRST, status",
            [str(spool_path)],
        ).to_arrow_reader(read_batch_size)
        for batch in reader:
            forms = batch.column(batch.schema.get_field_index("form")).to_pylist()
            offset = 0
            while offset < batch.num_rows:
                form = forms[offset]
                end = offset + 1
                while end < batch.num_rows and forms[end] == form:
                    end += 1
                cursor = offset
                if current_form != form:
                    flush()
                    current_form = form
                while cursor < end:
                    take = min(row_group_size - buffered_rows, end - cursor)
                    buffered.append(pa.Table.from_batches([batch.slice(cursor, take)]))
                    buffered_rows += take
                    cursor += take
                    if buffered_rows == row_group_size:
                        flush()
                offset = end
    flush()
    parts.sort(key=lambda item: (item["form"], item["path"]))
    return parts


__all__ = [
    "CoveragePreflight",
    "DocumentPlanningError",
    "PlanResult",
    "coverage_preflight",
    "create_document_plan",
    "resolve_inventory_snapshot_id",
]
