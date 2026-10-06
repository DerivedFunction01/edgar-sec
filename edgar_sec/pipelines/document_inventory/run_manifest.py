"""Atomic run manifest and deterministic chunk identity for the S4 worker.

Pins parent snapshot, cohort identity, parser/schema versions, refresh/fetch modes,
work-order version, chunk size, and every chunk's membership digest. Machine-local
worker count and cache path are deliberately excluded so they may change on resume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.infra.storage.atomic import atomic_write_json

from .paths import InventoryRunPaths

__all__ = [
    "WORK_ORDER_VERSION",
    "OUTCOME_SCHEMA_VERSION",
    "ChunkIdentity",
    "InventoryRunManifest",
    "ManifestMismatchError",
    "compute_chunk_id",
    "membership_digest",
    "partition_into_chunks",
    "write_run_manifest",
    "read_run_manifest",
    "validate_run_manifest",
]


#: Bumped whenever the chunk partitioning algorithm or attempt-commit protocol changes.
WORK_ORDER_VERSION = "1"

#: Pinned per run so an older attempt's schema is never silently accepted.
OUTCOME_SCHEMA_VERSION = 1

#: Refresh modes that control whether existing cache entries are bypassed.
REFRESH_MODES = frozenset({"normal", "force"})

#: Fetch modes for the index page.
FETCH_MODES = frozenset({"live", "force_refresh"})


@dataclass(frozen=True, slots=True)
class ChunkIdentity:
    """Deterministic identity of one chunk within a run."""

    chunk_id: str
    ordinal: int
    membership_digest: str
    membership_count: int
    work_order_version: str


@dataclass(frozen=True, slots=True)
class InventoryRunManifest:
    """Pinned identity that gates resume; refuses reuse on any mismatch."""

    run_id: str
    parent_snapshot_id: str
    canonical_cohort_id: str
    source_identity: str
    parser_version: str
    outcome_schema_version: int
    entry_schema_version: int
    work_order_version: str
    chunk_size: int
    refresh_mode: str
    fetch_mode: str
    fixture_id: str | None
    created_at: str
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    chunk_identities: tuple[ChunkIdentity, ...] = ()

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
            "chunk_size": self.chunk_size,
            "refresh_mode": self.refresh_mode,
            "fetch_mode": self.fetch_mode,
            "fixture_id": self.fixture_id,
            "created_at": self.created_at,
            "settings_snapshot": self.settings_snapshot,
            "chunk_identities": [
                {
                    "chunk_id": ci.chunk_id,
                    "ordinal": ci.ordinal,
                    "membership_digest": ci.membership_digest,
                    "membership_count": ci.membership_count,
                    "work_order_version": ci.work_order_version,
                }
                for ci in self.chunk_identities
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InventoryRunManifest:
        chunk_ids = data.get("chunk_identities", [])
        if not isinstance(chunk_ids, list):
            raise ValueError("chunk_identities must be a list")
        identities = tuple(
            ChunkIdentity(
                chunk_id=str(item["chunk_id"]),
                ordinal=int(item["ordinal"]),
                membership_digest=str(item["membership_digest"]),
                membership_count=int(item["membership_count"]),
                work_order_version=str(item["work_order_version"]),
            )
            for item in chunk_ids
        )
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
            chunk_size=int(data["chunk_size"]),
            refresh_mode=str(data["refresh_mode"]),
            fetch_mode=str(data["fetch_mode"]),
            fixture_id=str(fixture_id) if fixture_id else None,
            created_at=str(data["created_at"]),
            settings_snapshot=data.get("settings_snapshot", {}),
            chunk_identities=identities,
        )


class ManifestMismatchError(ValueError):
    """A run manifest exists but its pinned identity conflicts with the request."""


def compute_chunk_id(
    work_order_version: str,
    ordinal: int,
    membership_digest: str,
    membership_count: int,
) -> str:
    """Return a deterministic chunk id from identity inputs."""
    digest = sha256_text(
        f"{work_order_version}:{ordinal}:{membership_digest}:{membership_count}"
    )
    return f"chunk-{ordinal:06d}-{digest[:8]}"


def membership_digest(accessions: tuple[str, ...]) -> str:
    """Hash the sorted accession list, so digesting is order-independent."""
    return sha256_text(canonical_json(sorted(str(a) for a in accessions)))


def partition_into_chunks(
    work_items: Sequence[IndexWorkItem],
    *,
    chunk_size: int,
    work_order_version: str = WORK_ORDER_VERSION,
) -> tuple[tuple[str, IndexWorkItem, ...], ...]:
    """Sort and partition work items into deterministic chunks.

    Chunk membership is independent of completion order and input arrival order:
    accessions are sorted before partitioning.
    """
    sorted_items = sorted(work_items, key=lambda w: str(w.accession))
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    chunks: list[tuple[str, IndexWorkItem, ...]] = []
    for ordinal, start in enumerate(range(0, len(sorted_items), chunk_size)):
        members = tuple(sorted_items[start : start + chunk_size])
        accessions = tuple(str(w.accession) for w in members)
        digest = membership_digest(accessions)
        chunk_id = compute_chunk_id(work_order_version, ordinal, digest, len(members))
        chunks.append((chunk_id, *members))
    return tuple(chunks)


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
    work_items: Sequence[IndexWorkItem],
    work_order_version: str = WORK_ORDER_VERSION,
) -> InventoryRunManifest:
    """Atomically write the run manifest after validating all pinned fields.

    S5 pins the run id and supply identity; S4 pins versions and chunk size.
    """
    if refresh_mode not in REFRESH_MODES:
        raise ValueError(f"invalid refresh_mode: {refresh_mode!r}")
    if fetch_mode not in FETCH_MODES:
        raise ValueError(f"invalid fetch_mode: {fetch_mode!r}")
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")

    chunks = partition_into_chunks(
        work_items, chunk_size=chunk_size, work_order_version=work_order_version
    )
    chunk_identities: list[ChunkIdentity] = []
    for ordinal, (chunk_id, *members_with_id) in enumerate(chunks):
        digest = membership_digest(tuple(str(w.accession) for w in members_with_id))
        chunk_identities.append(
            ChunkIdentity(
                chunk_id=chunk_id,
                ordinal=ordinal,
                membership_digest=digest,
                membership_count=len(members_with_id),
                work_order_version=work_order_version,
            )
        )

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
        chunk_size=chunk_size,
        refresh_mode=refresh_mode,
        fetch_mode=fetch_mode,
        fixture_id=fixture_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        settings_snapshot=settings_snapshot,
        chunk_identities=tuple(chunk_identities),
    )

    paths.run_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.run_manifest_path(), manifest.to_dict(), canonical=True)
    return manifest


def read_run_manifest(paths: InventoryRunPaths) -> InventoryRunManifest | None:
    """Read the run manifest, returning None when it does not exist."""
    path = paths.run_manifest_path()
    if not path.is_file():
        return None
    import json

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
    work_items: Sequence[IndexWorkItem],
    work_order_version: str = WORK_ORDER_VERSION,
) -> InventoryRunManifest:
    """Return the existing manifest if it is compatible, else raise.

    A missing manifest is acceptable (first run); a malformed or mismatched one refuses.
    """
    if existing is None:
        raise ManifestMismatchError(
            f"run manifest missing at {run_id}; refusing to reuse without writing one"
        )

    mismatches: list[str] = []
    if existing.run_id != run_id:
        mismatches.append(f"run_id {existing.run_id!r} != {run_id!r}")
    if existing.parent_snapshot_id != parent_snapshot_id:
        mismatches.append(
            f"parent_snapshot_id {existing.parent_snapshot_id!r} != {parent_snapshot_id!r}"
        )
    if existing.canonical_cohort_id != canonical_cohort_id:
        mismatches.append(
            f"canonical_cohort_id {existing.canonical_cohort_id!r} != {canonical_cohort_id!r}"
        )
    if existing.source_identity != source_identity:
        mismatches.append(
            f"source_identity {existing.source_identity!r} != {source_identity!r}"
        )
    if existing.parser_version != parser_version:
        mismatches.append(
            f"parser_version {existing.parser_version!r} != {parser_version!r}"
        )
    if existing.chunk_size != chunk_size:
        mismatches.append(f"chunk_size {existing.chunk_size} != {chunk_size}")
    if existing.refresh_mode != refresh_mode:
        mismatches.append(f"refresh_mode {existing.refresh_mode!r} != {refresh_mode!r}")
    if existing.fetch_mode != fetch_mode:
        mismatches.append(f"fetch_mode {existing.fetch_mode!r} != {fetch_mode!r}")
    if existing.work_order_version != work_order_version:
        mismatches.append(
            f"work_order_version {existing.work_order_version!r} != {work_order_version!r}"
        )
    if existing.outcome_schema_version != OUTCOME_SCHEMA_VERSION:
        mismatches.append(
            f"outcome_schema_version {existing.outcome_schema_version} != {OUTCOME_SCHEMA_VERSION}"
        )
    if existing.entry_schema_version != ENTRY_SCHEMA_VERSION:
        mismatches.append(
            f"entry_schema_version {existing.entry_schema_version} != {ENTRY_SCHEMA_VERSION}"
        )

    # Recompute chunk identities from the worklist and compare.
    current_chunks = partition_into_chunks(
        work_items, chunk_size=chunk_size, work_order_version=work_order_version
    )
    if len(current_chunks) != len(existing.chunk_identities):
        mismatches.append(
            f"chunk count {len(existing.chunk_identities)} != {len(current_chunks)}"
        )
    else:
        for existing_ci, (chunk_id, *members) in zip(
            existing.chunk_identities, current_chunks
        ):
            if existing_ci.chunk_id != chunk_id:
                mismatches.append(
                    f"chunk_id mismatch: {existing_ci.chunk_id!r} != {chunk_id!r}"
                )
            digest = membership_digest(tuple(str(w.accession) for w in members))
            if existing_ci.membership_digest != digest:
                mismatches.append(f"membership_digest mismatch for {chunk_id!r}")
            if existing_ci.membership_count != len(members):
                mismatches.append(
                    f"membership_count mismatch for {chunk_id!r}: "
                    f"{existing_ci.membership_count} != {len(members)}"
                )

    if mismatches:
        raise ManifestMismatchError(
            f"run manifest mismatch for {run_id}: " + "; ".join(mismatches[:5])
        )

    return existing
