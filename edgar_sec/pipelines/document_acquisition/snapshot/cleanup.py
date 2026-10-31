"""Transient run cleanup gated on publication receipt or explicit discard."""

from __future__ import annotations

import shutil
from pathlib import Path

from edgar_sec.foundation.runtime.paths import RUN_LOCK_FILE, validate_safe_id
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

from .errors import SnapshotCleanupError
from .models import CleanupReport
from .writer import read_publication_receipt


def cleanup_transient_run(
    paths: AcquisitionPaths,
    run_id: str,
    *,
    explicit_discard: bool = False,
) -> CleanupReport:
    validate_safe_id(run_id, "run_id")
    run_dir = paths.run_dir(run_id)
    if not run_dir.is_dir():
        return CleanupReport(
            run_id=run_id,
            cleaned_files_count=0,
            cleaned_bytes=0,
            receipt_verified=False,
            status="cleaned",
            reason="run directory does not exist",
        )

    lock_file = paths.run_lock_path(run_id)
    if lock_file.is_file():
        raise SnapshotCleanupError(f"cleanup refused: run {run_id} is locked")

    receipt = read_publication_receipt(paths, run_id)
    receipt_verified = False
    if receipt is not None:
        catalog = DAGCatalog(paths.snapshots_root)
        if catalog.has_snapshot(receipt.snapshot_id):
            receipt_verified = True

    if not receipt_verified and not explicit_discard:
        raise SnapshotCleanupError(
            f"cleanup refused: run {run_id} has no verified publication receipt"
        )

    staging_root = paths.run_staging_root(run_id)
    cleaned_count = 0
    cleaned_bytes = 0

    if staging_root.is_dir():
        for path in staging_root.rglob("*"):
            if path.is_file():
                cleaned_count += 1
                try:
                    cleaned_bytes += path.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(staging_root, ignore_errors=True)

    return CleanupReport(
        run_id=run_id,
        cleaned_files_count=cleaned_count,
        cleaned_bytes=cleaned_bytes,
        receipt_verified=receipt_verified,
        status="cleaned",
    )


__all__ = ["cleanup_transient_run"]
