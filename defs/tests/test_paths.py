import pytest

from defs.runtime.paths import (
    MERGE_REPORT_NAME,
    ArtifactRole,
    FixturePaths,
    RunPaths,
    classify_artifact_path,
    merge_report_path_in,
    partition_artifact_path_in,
    partition_merge_report_path_in,
    partition_merge_root_in,
    resolve_paths,
)


def test_paths_are_derived_from_shared_environment_root_without_creation(tmp_path):
    root = tmp_path / "artifacts"
    paths = resolve_paths("metadata", "run-1", {"ARTIFACTS_ROOT": str(root)})

    assert isinstance(paths, RunPaths)
    assert paths.run_root == root / "metadata" / "runs" / "run-1"
    assert paths.plan_path == paths.run_root / "plan.json"
    assert paths.partition_manifest(2).name == "partition-00002.json"
    assert (
        paths.partition_chunks(2)
        == paths.run_root / "partitions" / "partition-00002" / "chunks"
    )
    assert not root.exists()


def test_explicit_cache_path_overrides_derived_locations(tmp_path):
    paths = resolve_paths(
        env={
            "ARTIFACTS_ROOT": str(tmp_path / "artifacts"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    assert paths.artifacts_root == tmp_path / "artifacts"
    assert paths.cache_root == tmp_path / "cache"
    assert (
        paths.runtime_config_path == tmp_path / "artifacts" / "runtime" / "config.json"
    )
    assert (
        paths.phase("metadata").config_path
        == tmp_path / "artifacts" / "metadata" / "config.json"
    )


def test_paths_resolve_through_the_shared_environment_layer(tmp_path, monkeypatch):
    """Without an explicit mapping, paths flow through the settings registry."""
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "from-process"))
    paths = resolve_paths()
    assert paths.artifacts_root == tmp_path / "from-process"
    assert (
        paths.runtime_config_path
        == tmp_path / "from-process" / "runtime" / "config.json"
    )
    assert (
        paths.phase("metadata").config_path
        == tmp_path / "from-process" / "metadata" / "config.json"
    )
    assert paths.cache_root == tmp_path / "from-process" / "caches"


def test_paths_resolve_from_dotenv_without_explicit_mapping(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        f"ARTIFACTS_ROOT={tmp_path / 'from-dotenv'}\n"
        f"CACHE_ROOT={tmp_path / 'dotenv-cache'}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ARTIFACTS_ROOT", raising=False)
    monkeypatch.delenv("CACHE_ROOT", raising=False)
    monkeypatch.setenv("DOTENV_PATH", str(env_file))
    paths = resolve_paths()
    assert paths.artifacts_root == tmp_path / "from-dotenv"
    assert paths.cache_root == tmp_path / "dotenv-cache"


def test_explicit_mapping_ignores_process_environment_and_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("ARTIFACTS_ROOT=/should/be/ignored\n", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(env_file))
    monkeypatch.setenv("ARTIFACTS_ROOT", "/also/ignored")
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(tmp_path / "explicit")})
    assert paths.artifacts_root == tmp_path / "explicit"


def test_published_dataset_path_is_composed_from_logical_identity_and_format(tmp_path):
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(tmp_path)})
    assert paths.published_dataset_path(
        "metadata", "submission_metadata", "parquet"
    ) == (
        tmp_path
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    )
    assert (
        paths.published_dataset_path("metadata", "submission_metadata", "jsonl").suffix
        == ".jsonl"
    )
    with pytest.raises(ValueError):
        paths.published_dataset_path("metadata", "submission_metadata", "csv")
    assert paths.manifests_root == tmp_path / "manifests"
    assert paths.dataset_manifests("metadata", "submission_metadata") == (
        tmp_path / "manifests" / "metadata" / "submission_metadata" / "final"
    )
    assert paths.dataset_manifests(
        "metadata", "submission_metadata", partition="partition-00001"
    ) == (
        tmp_path
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "partitions"
        / "partition-00001"
    )
    assert paths.phase("metadata").published_dataset(
        "submission_metadata", "parquet"
    ) == (
        tmp_path
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    )


def test_fixture_paths_dialect_and_files(tmp_path):
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(tmp_path)})
    fixture = paths.fixture("sample-100", dialect="duckdb")
    assert isinstance(fixture, FixturePaths)
    assert fixture.dialect == "duckdb"
    assert fixture.db_path == tmp_path / "fixtures" / "sample-100" / "fixture.duckdb"
    assert (
        fixture.manifest_path
        == tmp_path / "fixtures" / "sample-100" / "fixture.manifest.json"
    )

    sqlite_fixture = paths.fixture("sample-100", dialect="sqlite")
    assert sqlite_fixture.dialect == "sqlite"
    assert (
        sqlite_fixture.db_path
        == tmp_path / "fixtures" / "sample-100" / "fixture.sqlite"
    )

    phase_fixture = paths.phase("metadata").fixture("sample-100", dialect="sqlite")
    assert (
        phase_fixture.db_path
        == tmp_path
        / "acceptance"
        / "metadata"
        / "fixtures"
        / "sample-100"
        / "fixture.sqlite"
    )


def test_partition_merge_paths_and_helpers(tmp_path):
    run_root = tmp_path / "metadata" / "runs" / "run-1"
    assert partition_merge_root_in(run_root, 1) == (
        run_root / "partitions" / "partition-00001" / "merge"
    )
    assert partition_merge_report_path_in(run_root, 1) == (
        run_root / "partitions" / "partition-00001" / "merge" / MERGE_REPORT_NAME
    )
    assert partition_artifact_path_in(run_root, 1, "sub.parquet") == (
        run_root / "partitions" / "partition-00001" / "merge" / "sub.parquet"
    )
    assert merge_report_path_in(run_root) == run_root / "merge" / MERGE_REPORT_NAME


def test_classify_artifact_path():
    classified = classify_artifact_path("metadata/runs/r1/plan.json")
    assert classified.role == ArtifactRole.RUN_PLAN
    assert classified.phase == "metadata"
    assert classified.run_id == "r1"

    pub_dataset = classify_artifact_path(
        "manifests/metadata/submission_metadata/final/submission_metadata.parquet"
    )
    assert pub_dataset.role == ArtifactRole.PUBLISHED_DATASET
    assert pub_dataset.phase == "metadata"

    pub_manifest = classify_artifact_path(
        "manifests/metadata/submission_metadata/final/4d7fde4d090d580d876e4f8f89bb0830.json"
    )
    assert pub_manifest.role == ArtifactRole.PUBLISHED_MANIFEST
    assert pub_manifest.phase == "metadata"

    unknown = classify_artifact_path("other/file.txt")
    assert unknown.role == ArtifactRole.UNKNOWN
