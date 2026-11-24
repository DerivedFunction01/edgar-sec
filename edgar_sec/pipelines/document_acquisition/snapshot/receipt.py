"""Publication receipts for acquisition snapshot publishing."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

from .models import PublicationReceipt

__all__ = ["read_publication_receipt"]


def _receipt_path(paths: AcquisitionPaths, run_id: str) -> Path:
    return paths.publication_receipt_path(run_id)


def read_publication_receipt(
    paths: AcquisitionPaths, run_id: str
) -> PublicationReceipt | None:
    path = _receipt_path(paths, run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PublicationReceipt(
            receipt_schema_version=data["receipt_schema_version"],
            snapshot_id=data["snapshot_id"],
            run_id=data["run_id"],
            branch=data["branch"],
            published_at_utc=data["published_at_utc"],
            adopted_payload_count=data["adopted_payload_count"],
            adopted_payload_bytes=data["adopted_payload_bytes"],
            relation_row_counts=data["relation_row_counts"],
        )
    except (KeyError, OSError, ValueError):
        return None


def _write_receipt(
    paths: AcquisitionPaths, run_id: str, receipt: PublicationReceipt
) -> None:
    payload = {
        "receipt_schema_version": receipt.receipt_schema_version,
        "snapshot_id": receipt.snapshot_id,
        "run_id": receipt.run_id,
        "branch": receipt.branch,
        "published_at_utc": receipt.published_at_utc,
        "adopted_payload_count": receipt.adopted_payload_count,
        "adopted_payload_bytes": receipt.adopted_payload_bytes,
        "relation_row_counts": receipt.relation_row_counts,
    }
    atomic_write_json(_receipt_path(paths, run_id), payload)
    snap_receipt_path = paths.snapshot_root(receipt.snapshot_id) / "receipt.json"
    if snap_receipt_path.parent.is_dir():
        atomic_write_json(snap_receipt_path, payload)
