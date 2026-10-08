"""Directory layout; a chunk checkpoint is resumability state, a snapshot output."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    ProjectPaths,
    resolve_paths,
)
from edgar_sec.pipelines.metadata_sync.options import BundleRunPaths
from edgar_sec.pipelines.metadata_sync.paths import (
    ASSIGNMENTS_DIR_NAME,
    METADATA_DIR,
    RECEIPT_FILE_NAME,
    ROSTER_DIR_NAME,
    SNAPSHOT_CIK_INDEX_NAME,
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


def test_plan_paths_are_scoped_by_plan_id(tmp_path: Path) -> None:
    run_paths = resolve_run_paths("plan42", tmp_path)
    assert run_paths.plan_file == (
        tmp_path / "metadata" / "plans" / "plan42" / PLAN_FILE_NAME
    )
    assert run_paths.chunk_file(0).name == "chunk_0000.parquet"
    assert run_paths.chunk_file(12).name == "chunk_0012.parquet"


def test_a_plan_is_a_directory_of_artifacts_not_one_file(tmp_path: Path) -> None:
    """Manifest, roster, and assignments are separately copied and separately trusted."""
    run_paths = resolve_run_paths("plan42", tmp_path)
    bundle = tmp_path / "metadata" / "plans" / "plan42"
    assert run_paths.plan_bundle == bundle
    assert run_paths.plan_file == bundle / PLAN_FILE_NAME
    assert run_paths.roster_file == bundle / ROSTER_DIR_NAME / "ciks.parquet"
    assert run_paths.input_manifest_file == bundle / "input" / "input_manifest.json"
    assert run_paths.assignments_dir == bundle / ASSIGNMENTS_DIR_NAME
    assert (
        run_paths.assignment_file("abc")
        == bundle / ASSIGNMENTS_DIR_NAME / "abc.parquet"
    )


def test_a_copied_bundle_resolves_the_same_shape(tmp_path: Path) -> None:
    """Worker and coordinator run identical code against one plan."""
    bundle = BundleRunPaths(bundle_root=tmp_path / "out" / "worker-00", plan_id="p")
    assert bundle.plan_file == tmp_path / "out" / "worker-00" / "plan.json"
    assert (
        bundle.roster_file == tmp_path / "out" / "worker-00" / "roster" / "ciks.parquet"
    )
    assert bundle.assignment_file("a") == (
        tmp_path / "out" / "worker-00" / "assignments" / "a.parquet"
    )
    assert (
        bundle.chunk_file(3)
        == tmp_path / "out" / "worker-00" / "chunks" / "chunk_0003.parquet"
    )
    assert bundle.receipt_file == tmp_path / "out" / "worker-00" / RECEIPT_FILE_NAME
    assert "transient" not in bundle.chunk_file(0).parts


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


def test_the_effective_roster_is_published_beside_the_csv(tmp_path: Path) -> None:
    """The CSV is an export; the roster dataset is what a plan consumes."""
    metadata = MetadataPaths(artifacts_root=tmp_path)
    assert metadata.effective_cik_roster("reg1") == (
        tmp_path
        / "metadata"
        / "registries"
        / "reg1"
        / "datasets"
        / "effective_ciks.parquet"
    )


def test_the_published_cik_index_sits_beside_the_payload(tmp_path: Path) -> None:
    metadata = MetadataPaths(artifacts_root=tmp_path)
    assert metadata.snapshot_cik_index("snap1") == (
        tmp_path / "metadata" / "snapshots" / "snap1" / SNAPSHOT_CIK_INDEX_NAME
    )
    assert metadata.snapshot_cik_index("snap1").parent == (
        metadata.snapshot_file("snap1").parent
    )


def _project_paths(artifacts_root: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=artifacts_root.parent,
        artifacts_root=artifacts_root,
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
