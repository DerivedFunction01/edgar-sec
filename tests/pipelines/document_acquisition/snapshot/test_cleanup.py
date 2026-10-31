from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.cleanup import (
    cleanup_transient_run,
)
from edgar_sec.pipelines.document_acquisition.snapshot.errors import (
    SnapshotCleanupError,
)
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_cleanup_non_existent_run_returns_clean_report(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    report = cleanup_transient_run(paths, "run-missing")
    assert report.status == "cleaned"
    assert report.cleaned_files_count == 0
    assert report.reason == "run directory does not exist"


def test_cleanup_refused_when_run_is_locked(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    lock_file = paths.run_lock_path(run_id)
    lock_file.touch()

    with pytest.raises(SnapshotCleanupError, match="is locked"):
        cleanup_transient_run(paths, run_id)


def test_cleanup_refused_without_verified_receipt(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")

    with pytest.raises(SnapshotCleanupError, match="no verified publication receipt"):
        cleanup_transient_run(paths, run_id)


def test_cleanup_with_explicit_discard_cleans_unverified_run(
    tmp_path: Path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    assert paths.run_staging_root(run_id).is_dir()

    report = cleanup_transient_run(paths, run_id, explicit_discard=True)
    assert report.status == "cleaned"
    assert not report.receipt_verified
    assert report.cleaned_files_count > 0
    assert not paths.run_staging_root(run_id).exists()


def test_cleanup_with_verified_receipt(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id)
    assert pub.status == "published"

    report = cleanup_transient_run(paths, run_id)
    assert report.status == "cleaned"
    assert report.receipt_verified
    assert not paths.run_staging_root(run_id).exists()
    assert paths.run_manifest_path(run_id).is_file()
