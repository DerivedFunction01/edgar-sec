"""Immutable models for acquisition snapshot publication and receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PUBLICATION_RECEIPT_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    receipt_schema_version: str
    snapshot_id: str
    run_id: str
    branch: str
    published_at_utc: str
    adopted_payload_count: int
    adopted_payload_bytes: int
    relation_row_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class SnapshotPublication:
    status: Literal["published", "already_published", "failed"]
    run_id: str
    snapshot_id: str | None = None
    reason: str | None = None
    receipt: PublicationReceipt | None = None

    @classmethod
    def published(
        cls, run_id: str, snapshot_id: str, receipt: PublicationReceipt
    ) -> SnapshotPublication:
        return cls(
            status="published",
            run_id=run_id,
            snapshot_id=snapshot_id,
            receipt=receipt,
        )

    @classmethod
    def already_published(cls, run_id: str, snapshot_id: str) -> SnapshotPublication:
        return cls(status="already_published", run_id=run_id, snapshot_id=snapshot_id)

    @classmethod
    def failed(cls, run_id: str, reason: str) -> SnapshotPublication:
        return cls(status="failed", run_id=run_id, reason=reason)

    @property
    def was_published(self) -> bool:
        return self.status == "published"


@dataclass(frozen=True, slots=True)
class CleanupReport:
    run_id: str
    cleaned_files_count: int
    cleaned_bytes: int
    receipt_verified: bool
    status: Literal["cleaned", "refused"]
    reason: str | None = None


__all__ = [
    "PUBLICATION_RECEIPT_SCHEMA_VERSION",
    "CleanupReport",
    "PublicationReceipt",
    "SnapshotPublication",
]
