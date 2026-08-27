from pathlib import Path

import pytest

from defs.runtime.paths import RunPaths, resolve_paths


def test_paths_are_derived_from_shared_environment_root_without_creation(tmp_path):
    root = tmp_path / "artifacts"
    paths = resolve_paths("metadata", "run-1", {"EDGAR_ARTIFACTS_ROOT": str(root)})

    assert isinstance(paths, RunPaths)
    assert paths.run_root == root / "metadata" / "runs" / "run-1"
    assert paths.plan_path == paths.run_root / "plan.json"
    assert paths.partition_manifest(2).name == "partition-00002.json"
    assert (
        paths.partition_chunks(2)
        == paths.run_root / "partitions" / "partition-00002" / "chunks"
    )
    assert not root.exists()


def test_explicit_config_and_cache_paths_override_derived_locations(tmp_path):
    paths = resolve_paths(
        env={
            "EDGAR_ARTIFACTS_ROOT": str(tmp_path / "artifacts"),
            "EDGAR_CONFIG_PATH": str(tmp_path / "config.json"),
            "EDGAR_CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    assert paths.config_path == tmp_path / "config.json"
    assert paths.cache_root == tmp_path / "cache"


def test_canonical_output_is_composed_from_logical_identity_and_format(tmp_path):
    paths = resolve_paths(env={"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    assert paths.canonical_output("metadata", "submission_metadata", "parquet") == (
        tmp_path / "metadata" / "canonical" / "submission_metadata.parquet"
    )
    assert paths.canonical_output("metadata", "submission_metadata", "jsonl").suffix == ".jsonl"
    with pytest.raises(ValueError):
        paths.canonical_output("metadata", "submission_metadata", "csv")


@pytest.mark.parametrize("value", ["../escape", "", "worker/name", "bad space"])
def test_path_ids_reject_traversal_and_ambiguous_names(value):
    with pytest.raises(ValueError):
        resolve_paths("metadata", value)


def test_directory_creation_is_explicit(tmp_path):
    paths = resolve_paths("metadata", "run-1", {"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    assert isinstance(paths, RunPaths)
    paths.ensure_run_layout()
    assert paths.partitions_root.is_dir()
    assert paths.workers_root.is_dir()
