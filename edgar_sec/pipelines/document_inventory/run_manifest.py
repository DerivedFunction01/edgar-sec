"""Path-backed work-order identity and resumable chunk manifests for S4."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_inventory.paths import InventoryRunPaths

WORK_ORDER_VERSION = "2"
OUTCOME_SCHEMA_VERSION = 1
WORK_ORDER_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("index_url", pa.string(), nullable=False),
    ]
)
_WORK_ORDER_WRITE_BATCH_ROWS = 4096
_REFRESH_MODES = frozenset({"normal", "force"})
_FETCH_MODES = frozenset({"live", "force_refresh"})

__all__ = [
    "WORK_ORDER_VERSION",
    "OUTCOME_SCHEMA_VERSION",
    "WORK_ORDER_SCHEMA",
    "ChunkIdentity",
    "InventoryRunManifest",
    "ManifestMismatchError",
    "WorkOrderIdentity",
    "compute_chunk_id",
    "iter_work_order_chunks",
    "membership_digest",
    "partition_into_chunks",
    "read_run_manifest",
    "validate_run_manifest",
    "validate_work_order",
    "write_run_manifest",
    "write_work_order",
]


@dataclass(frozen=True, slots=True)
class ChunkIdentity:
    chunk_id: str
    ordinal: int
    membership_digest: str
    membership_count: int
    work_order_version: str


@dataclass(frozen=True, slots=True)
class WorkOrderIdentity:
    digest: str
    row_count: int


@dataclass(frozen=True, slots=True)
class InventoryRunManifest:
    run_id: str
    parent_snapshot_id: str
    canonical_cohort_id: str
    source_identity: str
    parser_version: str
    outcome_schema_version: int
    entry_schema_version: int
    work_order_version: str
    work_order_digest: str
    work_order_rows: int
    chunk_size: int
    refresh_mode: str
    fetch_mode: str
    fixture_id: str | None
    created_at: str
    settings_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "parent_snapshot_id": self.parent_snapshot_id,
            "canonical_cohort_id": self.canonical_cohort_id,
            "source_identity": self.source_identity,
            "parser_version": self.parser_version,
            "outcome_schema_version": self.outcome_schema_version,
            "entry_schema_version": self.entry_schema_version,
            "work_order_version": self.work_order_version,
            "work_order_digest": self.work_order_digest,
            "work_order_rows": self.work_order_rows,
            "chunk_size": self.chunk_size,
            "refresh_mode": self.refresh_mode,
            "fetch_mode": self.fetch_mode,
            "fixture_id": self.fixture_id,
            "created_at": self.created_at,
            "settings_snapshot": self.settings_snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InventoryRunManifest:
        fixture_id = data.get("fixture_id")
        return cls(
            run_id=str(data["run_id"]),
            parent_snapshot_id=str(data["parent_snapshot_id"]),
            canonical_cohort_id=str(data["canonical_cohort_id"]),
            source_identity=str(data["source_identity"]),
            parser_version=str(data["parser_version"]),
            outcome_schema_version=int(data["outcome_schema_version"]),
            entry_schema_version=int(data["entry_schema_version"]),
            work_order_version=str(data["work_order_version"]),
            work_order_digest=str(data["work_order_digest"]),
            work_order_rows=int(data["work_order_rows"]),
            chunk_size=int(data["chunk_size"]),
            refresh_mode=str(data["refresh_mode"]),
            fetch_mode=str(data["fetch_mode"]),
            fixture_id=str(fixture_id) if fixture_id else None,
            created_at=str(data["created_at"]),
            settings_snapshot=data.get("settings_snapshot", {}),
        )


class ManifestMismatchError(ValueError):
    """A run manifest exists but its pinned identity conflicts with the request."""


def compute_chunk_id(
    work_order_version: str,
    ordinal: int,
    membership_digest: str,
    membership_count: int,
) -> str:
    from edgar_sec.foundation.hashing import sha256_text

    digest = sha256_text(
        f"{work_order_version}:{ordinal}:{membership_digest}:{membership_count}"
    )
    return f"chunk-{ordinal:06d}-{digest[:8]}"


def membership_digest(accessions: tuple[str, ...]) -> str:
    from edgar_sec.foundation.hashing import sha256_text

    return sha256_text(
        canonical_json(sorted(str(accession) for accession in accessions))
    )


def partition_into_chunks(
    work_items: Sequence[IndexWorkItem],
    *,
    chunk_size: int,
    work_order_version: str = WORK_ORDER_VERSION,
) -> tuple[tuple[str, IndexWorkItem, ...], ...]:
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    ordered = sorted(work_items, key=lambda item: str(item.accession))
    chunks = []
    for ordinal, start in enumerate(range(0, len(ordered), chunk_size)):
        members = tuple(ordered[start : start + chunk_size])
        digest = membership_digest(tuple(str(item.accession) for item in members))
        chunk_id = compute_chunk_id(work_order_version, ordinal, digest, len(members))
        chunks.append((chunk_id, *members))
    return tuple(chunks)


def _row_digest_update(hasher, accession: str, index_url: str) -> None:
    for value in (accession, index_url):
        encoded = value.encode("utf-8")
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)


def validate_work_order(
    path: Path | str, *, batch_rows: int = _WORK_ORDER_WRITE_BATCH_ROWS
) -> WorkOrderIdentity:
    work_order = Path(path)
    if batch_rows < 1:
        raise ValueError("batch_rows must be positive")
    try:
        parquet = pq.ParquetFile(work_order)
    except (OSError, pa.ArrowException, pq.ParquetException) as exc:
        raise ManifestMismatchError(
            f"work order is not readable Parquet: {work_order}"
        ) from exc
    schema = parquet.schema_arrow
    if schema.names != WORK_ORDER_SCHEMA.names or any(
        field.type != pa.string() for field in schema
    ):
        raise ManifestMismatchError(f"work-order schema mismatch: {work_order}")
    digest = hashlib.sha256()
    row_count = 0
    previous = None
    for batch in parquet.iter_batches(batch_size=batch_rows):
        for row in batch.to_pylist():
            accession_text = row["accession"]
            index_url = row["index_url"]
            try:
                accession = str(AccessionNumber.from_any(accession_text))
            except ValueError as exc:
                raise ManifestMismatchError(
                    "work order contains an invalid accession"
                ) from exc
            if accession_text != accession:
                raise ManifestMismatchError("work-order accessions must be normalized")
            if not index_url:
                raise ManifestMismatchError("work order contains an empty index URL")
            if previous is not None and accession <= previous:
                raise ManifestMismatchError(
                    "work-order accessions must be sorted and unique"
                )
            previous = accession
            _row_digest_update(digest, accession, index_url)
            row_count += 1
    if row_count != parquet.metadata.num_rows:
        raise ManifestMismatchError(
            "work-order Parquet row count changed while reading"
        )
    return WorkOrderIdentity(digest.hexdigest(), row_count)


def write_work_order(
    path: Path | str,
    work_items: Iterable[IndexWorkItem],
    *,
    batch_rows: int = _WORK_ORDER_WRITE_BATCH_ROWS,
) -> WorkOrderIdentity:
    if batch_rows < 1:
        raise ValueError("batch_rows must be positive")
    writer = StagedParquetWriter(path, WORK_ORDER_SCHEMA)
    buffered_accessions: list[str] = []
    buffered_urls: list[str] = []
    previous = None
    count = 0
    try:
        for item in work_items:
            accession = str(item.accession)
            if previous is not None and accession <= previous:
                raise ValueError("work items must be sorted by unique accession")
            if not item.index_url:
                raise ValueError("work item has an empty index URL")
            previous = accession
            buffered_accessions.append(accession)
            buffered_urls.append(item.index_url)
            count += 1
            if len(buffered_accessions) >= batch_rows:
                writer.write_batch(
                    {"accession": buffered_accessions, "index_url": buffered_urls}
                )
                buffered_accessions = []
                buffered_urls = []
        if buffered_accessions:
            writer.write_batch(
                {"accession": buffered_accessions, "index_url": buffered_urls}
            )
        writer.commit(expected_count=count)
    except BaseException:
        writer.reset()
        raise
    return validate_work_order(path, batch_rows=batch_rows)


def iter_work_order_chunks(
    path: Path | str,
    *,
    chunk_size: int,
    work_order_version: str = WORK_ORDER_VERSION,
) -> Iterable[tuple[ChunkIdentity, tuple[IndexWorkItem, ...]]]:
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    parquet = pq.ParquetFile(path)
    for ordinal, batch in enumerate(parquet.iter_batches(batch_size=chunk_size)):
        rows = batch.to_pylist()
        members = tuple(
            IndexWorkItem(AccessionNumber(row["accession"]), row["index_url"])
            for row in rows
        )
        digest = membership_digest(tuple(str(item.accession) for item in members))
        chunk_id = compute_chunk_id(work_order_version, ordinal, digest, len(members))
        yield (
            ChunkIdentity(chunk_id, ordinal, digest, len(members), work_order_version),
            members,
        )


def write_run_manifest(
    paths: InventoryRunPaths,
    *,
    parent_snapshot_id: str,
    canonical_cohort_id: str,
    source_identity: str,
    parser_version: str,
    chunk_size: int,
    refresh_mode: str,
    fetch_mode: str,
    fixture_id: str | None = None,
    work_order_path: Path | str,
    work_order_version: str = WORK_ORDER_VERSION,
) -> InventoryRunManifest:
    if refresh_mode not in _REFRESH_MODES:
        raise ValueError(f"invalid refresh_mode: {refresh_mode!r}")
    if fetch_mode not in _FETCH_MODES:
        raise ValueError(f"invalid fetch_mode: {fetch_mode!r}")
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    identity = validate_work_order(work_order_path)
    resolved = resolve_settings(include=["runtime", "sec"])
    settings_snapshot = {
        path: value
        for path, value in resolved.items()
        if path in ("runtime.chunk_size", "sec.rate_limit_rps")
    }
    manifest = InventoryRunManifest(
        run_id=paths.run_id,
        parent_snapshot_id=parent_snapshot_id,
        canonical_cohort_id=canonical_cohort_id,
        source_identity=source_identity,
        parser_version=parser_version,
        outcome_schema_version=OUTCOME_SCHEMA_VERSION,
        entry_schema_version=ENTRY_SCHEMA_VERSION,
        work_order_version=work_order_version,
        work_order_digest=identity.digest,
        work_order_rows=identity.row_count,
        chunk_size=chunk_size,
        refresh_mode=refresh_mode,
        fetch_mode=fetch_mode,
        fixture_id=fixture_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        settings_snapshot=settings_snapshot,
    )
    paths.run_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.run_manifest_path(), manifest.to_dict(), canonical=True)
    return manifest


def read_run_manifest(paths: InventoryRunPaths) -> InventoryRunManifest | None:
    path = paths.run_manifest_path()
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return InventoryRunManifest.from_dict(data)


def validate_run_manifest(
    existing: InventoryRunManifest | None,
    *,
    run_id: str,
    parent_snapshot_id: str,
    canonical_cohort_id: str,
    source_identity: str,
    parser_version: str,
    chunk_size: int,
    refresh_mode: str,
    fetch_mode: str,
    fixture_id: str | None,
    work_order_path: Path | str,
    work_order_version: str = WORK_ORDER_VERSION,
) -> InventoryRunManifest:
    if existing is None:
        raise ManifestMismatchError(f"run manifest missing at {run_id}")
    work_order = validate_work_order(work_order_path)
    mismatches = []
    expected = {
        "run_id": (existing.run_id, run_id),
        "parent_snapshot_id": (existing.parent_snapshot_id, parent_snapshot_id),
        "canonical_cohort_id": (existing.canonical_cohort_id, canonical_cohort_id),
        "source_identity": (existing.source_identity, source_identity),
        "parser_version": (existing.parser_version, parser_version),
        "chunk_size": (existing.chunk_size, chunk_size),
        "refresh_mode": (existing.refresh_mode, refresh_mode),
        "fetch_mode": (existing.fetch_mode, fetch_mode),
        "fixture_id": (existing.fixture_id, fixture_id),
        "work_order_version": (existing.work_order_version, work_order_version),
        "work_order_digest": (existing.work_order_digest, work_order.digest),
        "work_order_rows": (existing.work_order_rows, work_order.row_count),
        "outcome_schema_version": (
            existing.outcome_schema_version,
            OUTCOME_SCHEMA_VERSION,
        ),
        "entry_schema_version": (existing.entry_schema_version, ENTRY_SCHEMA_VERSION),
    }
    for name, (actual, expected_value) in expected.items():
        if actual != expected_value:
            mismatches.append(f"{name} {actual!r} != {expected_value!r}")
    if mismatches:
        raise ManifestMismatchError(
            f"run manifest mismatch for {run_id}: " + "; ".join(mismatches[:5])
        )
    return existing
