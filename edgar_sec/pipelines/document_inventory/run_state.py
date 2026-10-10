"""Read and validate persisted inventory projection and execution state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.checkpoint import (
    REFUSAL_STATUSES,
    RETRYABLE_STATUSES,
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.paths import (
    COHORT_ACCESSIONS_FILE,
    COHORT_SOURCES_FILE,
    PROJECTION_MANIFEST_FILE,
    WORK_ORDER_FILE,
    InventoryPaths,
    InventoryRunPaths,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    InventoryRunManifest,
    ManifestMismatchError,
    WORK_ORDER_VERSION,
    iter_work_order_chunks,
    read_run_manifest,
    validate_run_manifest,
    validate_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    ENTRY_SCHEMA_VERSION,
    LOOKUP_LAYOUT_VERSION,
    PARSER_FINGERPRINT,
    PrefetchProjection,
    SNAPSHOT_RELATION_VERSION,
    _intent_id,
    _COHORT_ACCESSIONS_SCHEMA,
    _COHORT_SOURCES_SCHEMA,
    _hash_relations,
    _read_projection_manifest,
    _validate_output_schema,
)

__all__ = [
    "InventoryRunStatus",
    "discover_run_statuses",
    "load_run_state",
    "load_run_status",
]


@dataclass(frozen=True, slots=True)
class InventoryRunStatus:
    run_id: str
    state: str
    valid: bool
    error: str | None
    catalog_plan_id: str | None
    base_snapshot_id: str | None
    work_order_rows: int
    expected_chunks: int
    committed_chunks: int
    outstanding_chunks: int
    pending_accessions: int
    invalid_chunks: int
    retryable_failures: int
    refused_outcomes: int
    locked: bool
    lock_metadata: dict[str, Any] | None
    published_snapshot_id: str | None

    @property
    def can_publish(self) -> bool:
        return (
            self.valid
            and self.state == "ready"
            and self.outstanding_chunks == 0
            and self.retryable_failures == 0
            and self.refused_outcomes == 0
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["can_publish"] = self.can_publish
        return payload


def _read_persisted_projection(
    paths: InventoryRunPaths,
) -> tuple[PrefetchProjection, InventoryRunManifest]:
    try:
        paths.run_root.resolve().relative_to(
            InventoryPaths(paths.artifacts_root).transient_root.resolve()
        )
        paths.projection_manifest_path().resolve().relative_to(paths.run_root.resolve())
        paths.run_manifest_path().resolve().relative_to(paths.run_root.resolve())
        paths.lock_path().resolve().relative_to(paths.run_root.resolve())
        paths.cancelled_path().resolve().relative_to(paths.run_root.resolve())
    except ValueError as exc:
        raise ValueError("run path escapes the transient inventory root") from exc
    manifest = _read_projection_manifest(paths.projection_manifest_path())
    if manifest.get("projection_version") != "1":
        raise ValueError("unsupported projection manifest version")
    if manifest.get("run_id") != paths.run_id:
        raise ValueError("projection run id differs from its directory")
    catalog_id = manifest.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise ValueError("projection manifest has no catalog id")
    plan_id = manifest.get("catalog_plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("projection manifest has no catalog plan id")
    base_id = manifest.get("base_snapshot_id")
    if base_id is not None and (not isinstance(base_id, str) or not base_id):
        raise ValueError("projection manifest has an invalid base snapshot id")
    parser_version = manifest.get("parser_version")
    if parser_version != PARSER_FINGERPRINT:
        raise ValueError("projection parser version is unsupported")
    chunk_size = manifest.get("chunk_size")
    if (
        not isinstance(chunk_size, int)
        or isinstance(chunk_size, bool)
        or chunk_size < 1
    ):
        raise ValueError("projection chunk size is invalid")
    explicit_refresh = manifest.get("explicit_refresh")
    if not isinstance(explicit_refresh, bool):
        raise ValueError("projection refresh mode is invalid")
    refresh_salt = manifest.get("explicit_refresh_salt")
    if explicit_refresh:
        if not isinstance(refresh_salt, str) or not refresh_salt:
            raise ValueError("projection refresh salt is missing")
    elif refresh_salt is not None:
        raise ValueError("projection unexpectedly has a refresh salt")
    version_fields = {
        "snapshot_relation_version": SNAPSHOT_RELATION_VERSION,
        "entry_schema_version": ENTRY_SCHEMA_VERSION,
        "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
    }
    if any(manifest.get(key) != value for key, value in version_fields.items()):
        raise ValueError("projection schema versions are unsupported")

    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("projection output records are missing")
    output_specs = {
        "cohort_accessions": (COHORT_ACCESSIONS_FILE, _COHORT_ACCESSIONS_SCHEMA),
        "cohort_sources": (COHORT_SOURCES_FILE, _COHORT_SOURCES_SCHEMA),
        "work_order": (WORK_ORDER_FILE, None),
    }
    if set(outputs) != set(output_specs):
        raise ValueError("projection output records do not match the contract")
    for name, (filename, schema) in output_specs.items():
        record = outputs.get(name)
        if not isinstance(record, dict) or record.get("path") != filename:
            raise ValueError(f"projection output path mismatch: {name}")
        digest = record.get("sha256")
        path = paths.run_root / filename
        if not isinstance(digest, str) or not path.is_file():
            raise ValueError(f"projection output is missing: {name}")
        try:
            path.resolve().relative_to(paths.run_root.resolve())
        except ValueError as exc:
            raise ValueError(f"projection output escapes its run: {name}") from exc
        if file_sha256(path) != digest:
            raise ValueError(f"projection output digest mismatch: {name}")
        if schema is not None:
            _validate_output_schema(path, schema)
        if file_sha256(path) != digest:
            raise ValueError(f"projection output changed while reading: {name}")

    accession_rows = pq.ParquetFile(paths.cohort_accessions_path()).metadata.num_rows
    source_rows = pq.ParquetFile(paths.cohort_sources_path()).metadata.num_rows
    if manifest.get("cohort_accession_rows") != accession_rows:
        raise ValueError("projection accession row count mismatch")
    if manifest.get("cohort_source_rows") != source_rows:
        raise ValueError("projection source row count mismatch")
    cohort_fingerprint = _hash_relations(
        paths.cohort_accessions_path(), paths.cohort_sources_path()
    )
    if manifest.get("cohort_fingerprint") != cohort_fingerprint:
        raise ValueError("projection cohort fingerprint mismatch")
    base_manifest_sha = manifest.get("base_manifest_sha256")
    if base_id is None and base_manifest_sha is not None:
        raise ValueError("empty base has a manifest digest")
    if base_id is not None and not isinstance(base_manifest_sha, str):
        raise ValueError("projection base manifest digest is missing")
    expected_run_id = _intent_id(
        catalog_id=catalog_id,
        catalog_plan_id=plan_id,
        base_snapshot_id=base_id,
        base_manifest_sha256=base_manifest_sha,
        cohort_fingerprint=cohort_fingerprint,
        chunk_size=chunk_size,
        refresh_salt=refresh_salt,
    )
    if expected_run_id != paths.run_id:
        raise ValueError("projection run identity does not match its persisted inputs")

    work_order = validate_work_order(paths.work_order_path())
    if (
        manifest.get("work_order_digest") != work_order.digest
        or manifest.get("work_order_rows") != work_order.row_count
    ):
        raise ManifestMismatchError("projection work-order identity mismatch")
    work_order_version = manifest.get("work_order_version")
    if work_order_version != WORK_ORDER_VERSION:
        raise ValueError("projection work-order version is unsupported")
    run = validate_run_manifest(
        read_run_manifest(paths),
        run_id=paths.run_id,
        parent_snapshot_id=base_id or "",
        canonical_cohort_id=cohort_fingerprint,
        source_identity=f"filing-catalog-plan:{plan_id}",
        parser_version=parser_version,
        chunk_size=chunk_size,
        refresh_mode="force" if explicit_refresh else "normal",
        fetch_mode="force_refresh" if explicit_refresh else "live",
        fixture_id=None,
        work_order_path=paths.work_order_path(),
        work_order_version=work_order_version,
    )
    projection = PrefetchProjection(
        paths.run_id,
        plan_id,
        base_id,
        cohort_fingerprint,
        work_order.digest,
        work_order.row_count,
        refresh_salt or "",
        paths,
    )
    return projection, run


def load_run_state(
    artifacts_root: Path | str, run_id: str
) -> tuple[PrefetchProjection, InventoryRunManifest]:
    paths = inventory_run_paths(artifacts_root, run_id)
    return _read_persisted_projection(paths)


def _published_snapshot_id(artifacts_root: Path | str, run_id: str) -> str | None:
    paths = InventoryPaths(artifacts_root)
    try:
        matches = DAGCatalog.find_snapshot_ids_by_metadata(
            paths.snapshots_root, "run_intent_id", run_id
        )
        if not matches:
            return None
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
        for snapshot_id in matches:
            manifest = catalog.get_manifest(snapshot_id)
            if manifest is None or manifest.metadata.get("run_intent_id") != run_id:
                continue
            if catalog.get_manifest_sha256(snapshot_id) != sha256_text(
                canonical_json(manifest.to_dict())
            ):
                continue
            snapshot_root = paths.snapshot_root(snapshot_id).resolve()
            if not snapshot_root.is_dir():
                continue
            valid_parts = True
            for parts in manifest.relations.values():
                for part in parts:
                    part_path = (snapshot_root / part.path).resolve()
                    try:
                        part_path.relative_to(snapshot_root)
                    except ValueError:
                        valid_parts = False
                        break
                    if (
                        not part_path.is_file()
                        or part_path.stat().st_size != part.byte_size
                        or file_sha256(part_path) != part.sha256
                    ):
                        valid_parts = False
                        break
                if not valid_parts:
                    break
            if valid_parts:
                return snapshot_id
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
        return None
    return None


def _invalid_status(run_id: str, error: Exception) -> InventoryRunStatus:
    return InventoryRunStatus(
        run_id=run_id,
        state="invalid",
        valid=False,
        error=f"{type(error).__name__}: {error}",
        catalog_plan_id=None,
        base_snapshot_id=None,
        work_order_rows=0,
        expected_chunks=0,
        committed_chunks=0,
        outstanding_chunks=0,
        pending_accessions=0,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=None,
    )


def load_run_status(
    artifacts_root: Path | str, run_id: str, *, allow_locked: bool = False
) -> InventoryRunStatus:
    try:
        paths = inventory_run_paths(artifacts_root, run_id)
        projection, run = _read_persisted_projection(paths)
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        pa.ArrowException,
    ) as exc:
        return _invalid_status(run_id, exc)

    expected = committed = invalid = retryable = refused = pending = 0
    try:
        for chunk, members in iter_work_order_chunks(
            paths.work_order_path(),
            chunk_size=run.chunk_size,
            work_order_version=run.work_order_version,
        ):
            expected += 1
            checked = validate_committed_chunk(
                paths, chunk.chunk_id, run=run, chunk=chunk
            )
            if not checked.valid or checked.attempt_id is None:
                invalid += int(paths.chunk_pointer_path(chunk.chunk_id).exists())
                pending += len(members)
                continue
            committed += 1
            outcome_path = paths.attempt_outcomes_path(
                chunk.chunk_id, checked.attempt_id
            )
            parquet = pq.ParquetFile(outcome_path)
            for batch in parquet.iter_batches(
                batch_size=resolve_parquet_read_batch_size(), columns=["status"]
            ):
                statuses = batch.column("status").to_pylist()
                retryable_count = sum(
                    status in RETRYABLE_STATUSES for status in statuses
                )
                retryable += retryable_count
                pending += retryable_count
                refused += sum(status in REFUSAL_STATUSES for status in statuses)
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        pa.ArrowException,
    ) as exc:
        return _invalid_status(run_id, exc)

    lock_metadata = None
    if paths.lock_path().is_file():
        try:
            payload = json.loads(paths.lock_path().read_text(encoding="utf-8"))
            lock_metadata = payload if isinstance(payload, dict) else {"invalid": True}
        except (OSError, UnicodeError, json.JSONDecodeError):
            lock_metadata = {"invalid": True}
    cancelled = False
    if paths.cancelled_path().is_file():
        try:
            marker = json.loads(paths.cancelled_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return _invalid_status(run_id, exc)
        if marker != {"cancelled": True, "run_id": run_id}:
            return _invalid_status(run_id, ValueError("invalid cancellation marker"))
        cancelled = True
    published = _published_snapshot_id(artifacts_root, run_id)
    outstanding = expected - committed
    if published:
        state = "published"
    elif cancelled:
        state = "cancelled"
    elif lock_metadata is not None and not allow_locked:
        state = "running"
    elif outstanding:
        state = "blocked" if retryable or refused else "projected"
    elif retryable or refused:
        state = "blocked"
    else:
        state = "ready"
    return InventoryRunStatus(
        run_id=run_id,
        state=state,
        valid=True,
        error=None,
        catalog_plan_id=projection.catalog_plan_id,
        base_snapshot_id=projection.base_snapshot_id,
        work_order_rows=projection.work_order_rows,
        expected_chunks=expected,
        committed_chunks=committed,
        outstanding_chunks=outstanding,
        pending_accessions=pending,
        invalid_chunks=invalid,
        retryable_failures=retryable,
        refused_outcomes=refused,
        locked=lock_metadata is not None,
        lock_metadata=lock_metadata,
        published_snapshot_id=published,
    )


def discover_run_statuses(
    artifacts_root: Path | str,
) -> tuple[InventoryRunStatus, ...]:
    transient = InventoryPaths(artifacts_root).transient_root
    if not transient.is_dir():
        return ()
    statuses = []
    for run_root in sorted(transient.iterdir(), key=lambda path: path.name):
        if not run_root.is_dir():
            continue
        try:
            inventory_run_paths(artifacts_root, run_root.name)
        except ValueError:
            continue
        if not (run_root / PROJECTION_MANIFEST_FILE).exists():
            continue
        statuses.append(load_run_status(artifacts_root, run_root.name))
    return tuple(statuses)
