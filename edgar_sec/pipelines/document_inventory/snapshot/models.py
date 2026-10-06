"""Immutable snapshot metadata and publication results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

__all__ = [
    "AccessionRow",
    "EntryRow",
    "LookupShard",
    "PartitionPart",
    "SnapshotMetadata",
    "SnapshotPublication",
    "SourceEdgeRow",
]


@dataclass(frozen=True, slots=True)
class PartitionPart:
    """One Parquet part inside an annual partition."""

    path: str
    row_count: int
    key_min: str
    key_max: str
    byte_size: int
    sha256: str
    row_group_count: int


@dataclass(frozen=True, slots=True)
class LookupShard:
    """One seek-index shard for an accession, filing-CIK, or source-CIK."""

    lookup: str
    shard_key: str
    part_path: str
    row_count: int
    sha256: str
    key_min: str | None = None
    key_max: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    """Immutable metadata of one published snapshot; mirrors manifest.json.

    Fields are read-only after publication; queries resolve the parent and the
    active mapping rather than following mutable state.
    """

    snapshot_id: str
    parent_snapshot_id: str
    run_intent_id: str
    base_snapshot_id: str | None
    schema_version: str
    entry_schema_version: int
    lookup_layout_version: str
    created_at: str
    accessions_partitions: tuple[PartitionPart, ...]
    entries_partitions: tuple[PartitionPart, ...]
    accession_sources_partitions: tuple[PartitionPart, ...]
    accessions_lookup: tuple[LookupShard, ...]
    filing_cik_lookup: tuple[LookupShard, ...]
    source_cik_lookup: tuple[LookupShard, ...]
    active_accessions: Mapping[str, str]
    superseded_entry_ids: Mapping[str, tuple[str, ...]]
    accessions_digest: str

    @classmethod
    def from_manifest(cls, payload: dict) -> "SnapshotMetadata":
        accessions = payload.get("accessions", [])
        entries = payload.get("entries", [])
        sources = payload.get("accession_sources", [])
        lookups = payload.get("lookups", {})
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            parent_snapshot_id=str(payload.get("parent_snapshot_id", "")),
            run_intent_id=str(payload["run_intent_id"]),
            base_snapshot_id=payload.get("base_snapshot_id"),
            schema_version=str(payload.get("schema_version", "1")),
            entry_schema_version=int(payload.get("entry_schema_version", 1)),
            lookup_layout_version=str(payload.get("lookup_layout_version", "1")),
            created_at=str(payload["created_at"]),
            accessions_partitions=tuple(PartitionPart(**p) for p in accessions),
            entries_partitions=tuple(PartitionPart(**p) for p in entries),
            accession_sources_partitions=tuple(PartitionPart(**p) for p in sources),
            accessions_lookup=tuple(
                LookupShard(**s) for s in lookups.get("accession", [])
            ),
            filing_cik_lookup=tuple(
                LookupShard(**s) for s in lookups.get("filing_cik", [])
            ),
            source_cik_lookup=tuple(
                LookupShard(**s) for s in lookups.get("source_cik", [])
            ),
            active_accessions={
                k: tuple(v) for k, v in payload.get("active_accessions", {}).items()
            },
            superseded_entry_ids={
                k: tuple(v) for k, v in payload.get("superseded_entry_ids", {}).items()
            },
            accessions_digest=str(payload["accessions_digest"]),
        )

    def accessor_for(self, accession: str) -> str | None:
        """Return the accession-part locator for an active accession, else None."""
        locator = self.active_accessions.get(accession)
        return locator[0] if isinstance(locator, tuple) else locator

    def superseded_for(self, accession: str) -> tuple[str, ...]:
        """Return entry ids superseded for the accession; empty when none."""
        return tuple(self.superseded_entry_ids.get(accession, ()))

    @property
    def accession_count(self) -> int:
        return sum(p.row_count for p in self.accessions_partitions)

    @property
    def source_cik_count(self) -> int:
        return sum(p.row_count for p in self.accession_sources_partitions)

    @property
    def entry_count(self) -> int:
        return sum(p.row_count for p in self.entries_partitions)


@dataclass(frozen=True, slots=True)
class AccessionRow:
    """One accession row as returned by a query; all values are text."""

    accession: str
    filing_cik: str
    form: str
    filing_date: str
    report_date: str | None
    bundle_url: str | None
    bundle_size: int | None
    index_url: str
    index_sha256: str
    first_indexed_by: str


@dataclass(frozen=True, slots=True)
class EntryRow:
    """One child-file row as returned by a query; matches ENTRY_SCHEMA."""

    entry_id: str
    accession: str
    table_kind: str
    row_ordinal: int
    sequence: int | None
    document_type: str | None
    document_label: str | None
    description: str | None
    filename: str | None
    href: str | None
    archive_url: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class SourceEdgeRow:
    """One (accession, source_cik) relationship as returned by a query."""

    accession: str
    source_cik: str
    first_seen_by: str


@dataclass(frozen=True, slots=True)
class SnapshotPublication:
    """Result of one ``build_inventory`` run.

    Exactly one of ``published``/``no_op``/``failed`` is populated; callers
    inspect ``status`` first.
    """

    status: Literal["published", "no_op", "failed"]
    snapshot: SnapshotMetadata | None = None
    parent: SnapshotMetadata | None = None
    reason: str | None = None

    @classmethod
    def published(cls, snapshot: SnapshotMetadata) -> "SnapshotPublication":
        return cls(status="published", snapshot=snapshot)

    @classmethod
    def no_op(cls, parent: SnapshotMetadata) -> "SnapshotPublication":
        return cls(status="no_op", parent=parent)

    @classmethod
    def failed(cls, reason: str) -> "SnapshotPublication":
        return cls(status="failed", reason=reason)

    @property
    def was_published(self) -> bool:
        return self.status == "published"

    @property
    def was_no_op(self) -> bool:
        return self.status == "no_op"

    @property
    def was_failed(self) -> bool:
        return self.status == "failed"
