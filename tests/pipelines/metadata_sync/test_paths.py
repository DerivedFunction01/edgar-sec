"""Directory layout tests for the metadata pipeline.

The published/transient split is the load-bearing property here: a chunk
checkpoint is resumability state and a snapshot is output, and mixing them would
let a partially written artifact be mistaken for a published one.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    ProjectPaths,
    resolve_paths,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    METADATA_DIR,
    SNAPSHOT_FILE_NAME,
    SNAPSHOT_MANIFEST_NAME,
    MetadataPaths,
    resolve_metadata_paths,
    resolve_run_paths,
)


def test_published_and_transient_state_live_in_separate_trees(tmp_path: Path) -> None:
    metadata = MetadataPaths(artifacts_root=tmp_path)
    snapshot = metadata.snapshot_file("snap")
    chunk = resolve_run_paths("plan", tmp_path).chunk_file(0)

    assert metadata_root_of(snapshot) == tmp_path / "metadata"
    assert str(chunk).startswith(str(tmp_path / "transient" / METADATA_DIR))
    assert "transient" not in snapshot.parts
    assert "transient" not in metadata.plan_dir("plan").parts


def metadata_root_of(path: Path) -> Path:
    return path.parent.parent.parent


def test_snapshot_paths_are_scoped_by_snapshot_id(tmp_path: Path) -> None:
    metadata = MetadataPaths(artifacts_root=tmp_path)
    assert metadata.snapshot_file("abc") == (
        tmp_path / "metadata" / "snapshots" / "abc" / SNAPSHOT_FILE_NAME
    )
    assert metadata.snapshot_manifest("abc") == (
        tmp_path / "metadata" / "snapshots" / "abc" / SNAPSHOT_MANIFEST_NAME
    )
    assert metadata.current_pointer == (
        tmp_path / "metadata" / "snapshots" / "current" / "pointer.json"
    )


def test_plan_paths_are_scoped_by_plan_id(tmp_path: Path) -> None:
    run_paths = resolve_run_paths("plan42", tmp_path)
    assert run_paths.plan_file == (
        tmp_path / "metadata" / "plans" / "plan42" / PLAN_FILE_NAME
    )
    assert run_paths.chunk_file(0).name == "chunk_0000.parquet"
    assert run_paths.chunk_file(12).name == "chunk_0012.parquet"


def test_source_paths_are_content_addressed(tmp_path: Path) -> None:
    metadata = MetadataPaths(artifacts_root=tmp_path)
    source = metadata.source_dir("company_tickers", "snap1")
    assert source == tmp_path / "metadata" / "sources" / "company_tickers" / "snap1"
    assert metadata.source_snapshot_file("company_tickers", "snap1") == (
        source / "raw.json"
    )
    assert metadata.source_manifest_file("company_tickers", "snap1") == (
        source / "manifest.json"
    )


def test_registry_paths_are_content_addressed(tmp_path: Path) -> None:
    metadata = MetadataPaths(artifacts_root=tmp_path)
    root = metadata.registry_root("reg1")
    assert root == tmp_path / "metadata" / "registries" / "reg1"
    assert metadata.registry_manifest_root("reg1") == root / "datasets"
    assert metadata.registry_dataset("reg1", "registrant_registry") == (
        root / "datasets" / "registrant_registry.parquet"
    )
    assert metadata.effective_input_file("reg1") == root / "effective_cik_input.csv"


def _project_paths(artifacts_root: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=artifacts_root.parent,
        artifacts_root=artifacts_root,
        cache_root=artifacts_root / "cache",
        uploads_root=artifacts_root / "uploads",
    )


def test_resolve_metadata_paths_prefers_an_explicit_root(tmp_path: Path) -> None:
    assert resolve_metadata_paths(tmp_path).artifacts_root == tmp_path.resolve()
    assert resolve_metadata_paths(None, plan_id="ignored").artifacts_root == (
        resolve_paths().artifacts_root
    )


def test_resolve_run_paths_honours_every_resolution_channel(tmp_path: Path) -> None:
    assert (
        resolve_run_paths("p", tmp_path).metadata.artifacts_root == tmp_path.resolve()
    )
    project = _project_paths(tmp_path / "elsewhere")
    resolved = resolve_run_paths("p", None, project_paths=project)
    assert resolved.metadata.artifacts_root == project.artifacts_root
    assert resolved.plan_id == "p"
