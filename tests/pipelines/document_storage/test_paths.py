"""Tests for document storage path layout and artifact naming."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage.paths import (
    CASES_DIR,
    REVIEW_MANIFEST_NAME,
    SNAPSHOT_ARTIFACT_NAME,
    DocumentStoragePaths,
    chunk_checkpoint_path,
)


def test_chunk_checkpoint_path(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    path = chunk_checkpoint_path(chunks_dir, "001")
    assert path == chunks_dir / "chunk-001.parquet"
    assert REVIEW_MANIFEST_NAME == "review_manifest.jsonl"
    assert CASES_DIR == "cases"


def test_document_storage_paths_layout(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    paths = DocumentStoragePaths(artifacts_root=artifacts_root)

    assert paths.documents_root == artifacts_root / "document_storage" / "snapshots"
    assert paths.snapshots_root == paths.documents_root
    assert (
        paths.document_transient_root
        == artifacts_root / "transient" / "document_storage"
    )
    assert paths.fixtures_root == artifacts_root / "fixtures"
    assert paths.review_runs_root == artifacts_root / "document_storage" / "review-runs"
    assert paths.exhibits_root == artifacts_root / "document_exhibits" / "snapshots"

    assert paths.snapshot_dir("snap-1") == paths.snapshots_root / "snap-1"
    assert (
        paths.snapshot_artifact("snap-1")
        == paths.snapshots_root / "snap-1" / SNAPSHOT_ARTIFACT_NAME
    )

    assert paths.run_dir("run-1") == paths.document_transient_root / "runs" / "run-1"
    assert paths.run_chunks_dir("run-1") == paths.run_dir("run-1") / "chunks"
    assert paths.run_checkpoints_dir("run-1") == paths.run_dir("run-1") / "checkpoints"
    assert (
        paths.chunk_checkpoint("run-1", "c1")
        == paths.run_chunks_dir("run-1") / "chunk-c1.parquet"
    )

    assert paths.fixture_dir("fix-1") == paths.fixtures_root / "fix-1"
    assert (
        paths.fixture_db_path("fix-1") == paths.fixture_dir("fix-1") / "fixture.sqlite"
    )
    assert (
        paths.fixture_manifest_path("fix-1")
        == paths.fixture_dir("fix-1") / "fixture.manifest.json"
    )

    assert paths.review_run_dir("rev-1") == paths.review_runs_root / "rev-1"
    assert (
        paths.current_pointer_path()
        == paths.snapshots_root / "current" / "pointer.json"
    )


def test_document_storage_paths_from_project(tmp_path: Path) -> None:
    project = ProjectPaths(
        repo_root=tmp_path,
        artifacts_root=tmp_path / "artifacts",
        uploads_root=tmp_path / "uploads",
    )
    paths = DocumentStoragePaths.from_project(project)
    assert paths.artifacts_root == project.artifacts_root
