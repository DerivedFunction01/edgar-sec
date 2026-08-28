from pathlib import Path

import pytest

from defs.runtime.paths import (
    MERGE_REPORT_NAME,
    ArtifactRole,
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
    assert (
        paths.canonical_output("metadata", "submission_metadata", "jsonl").suffix
        == ".jsonl"
    )
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


def _builder_cases(tmp_path: Path):
    paths = resolve_paths("metadata", "run-1", {"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    assert isinstance(paths, RunPaths)
    root = Path(str(tmp_path))
    return [
        (
            paths.plan_path.relative_to(root),
            ArtifactRole.RUN_PLAN,
            "metadata",
            "run-1",
            None,
        ),
        (
            paths.partition_manifest(2).relative_to(root),
            ArtifactRole.PARTITION_MANIFEST,
            "metadata",
            "run-1",
            2,
        ),
        (
            (paths.partition_chunks(3) / "chunk-00003.parquet").relative_to(root),
            ArtifactRole.PARTITION_CHUNK,
            "metadata",
            "run-1",
            3,
        ),
        (
            (paths.run_root / "chunks" / "chunk-00001.parquet").relative_to(root),
            ArtifactRole.CHUNK,
            "metadata",
            "run-1",
            None,
        ),
        (
            paths.merge_report_path.relative_to(root),
            ArtifactRole.MERGE_REPORT,
            "metadata",
            "run-1",
            None,
        ),
        (
            (paths.workers_root / "w1" / "attempt-1" / "fragment.parquet").relative_to(
                root
            ),
            ArtifactRole.WORKER_FRAGMENT,
            "metadata",
            "run-1",
            None,
        ),
    ]


def test_every_built_path_classifies_to_the_same_role(tmp_path):
    for relative, role, phase, run_id, partition_id in _builder_cases(tmp_path):
        result = classify_artifact_path(relative)
        assert result.role is role
        assert result.phase == phase
        assert result.run_id == run_id
        assert result.partition_id == partition_id


def test_preview_and_canonical_paths_classify(tmp_path):
    project = resolve_paths(env={"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    preview = project.phase("metadata").preview_root / "local" / "sample.parquet"
    canonical = project.canonical_output("metadata", "submission_metadata", "jsonl")

    classified_preview = classify_artifact_path(preview.relative_to(tmp_path))
    assert classified_preview.role is ArtifactRole.PREVIEW
    assert classified_preview.phase == "metadata"
    assert classified_preview.run_id == "local"

    classified_canonical = classify_artifact_path(canonical.relative_to(tmp_path))
    assert classified_canonical.role is ArtifactRole.CANONICAL
    assert classified_canonical.phase == "metadata"
    assert classified_canonical.run_id is None


@pytest.mark.parametrize(
    "relative",
    [
        "metadata/runs/run-1/unknown.bin",
        "metadata/runs/run-1/partitions/partition-00001/chunks",
        "metadata/runs/run-1/partitions/other.json",
        "metadata/runs/run-1/partitions/partition-1/chunks/file.parquet",
        "metadata",
    ],
)
def test_unrecognized_paths_classify_as_unknown(relative):
    assert classify_artifact_path(relative).role is ArtifactRole.UNKNOWN


@pytest.mark.parametrize(
    "relative",
    [
        "metadata/runs/run-1/unknown.bin",
        "metadata/runs/run-1/preview_sample.parquet",
        "metadata/runs/run-1/partitions/other.json",
        "metadata/runs/run-1/partitions/partition-1/chunks/file.parquet",
    ],
)
def test_unknown_files_inside_a_run_keep_phase_and_run(relative):
    classified = classify_artifact_path(relative)
    assert classified.role is ArtifactRole.UNKNOWN
    assert classified.phase == "metadata"
    assert classified.run_id == "run-1"


def test_any_first_segment_is_a_valid_phase_name():
    classified = classify_artifact_path("other/runs/run-1/plan.json")
    assert classified.role is ArtifactRole.RUN_PLAN
    assert classified.phase == "other"


def test_absolute_paths_are_rejected():
    with pytest.raises(ValueError):
        classify_artifact_path("/tmp/artifacts/metadata/runs/r1/plan.json")


def test_merge_report_path_in_matches_run_builder(tmp_path):
    paths = resolve_paths("metadata", "run-1", {"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    assert merge_report_path_in(paths.run_root) == paths.merge_report_path


def test_partition_artifact_paths_round_trip_classification(tmp_path):
    paths = resolve_paths("metadata", "run-1", {"EDGAR_ARTIFACTS_ROOT": str(tmp_path)})
    artifact = paths.partition_root(3) / "merge" / "submission_metadata.parquet"
    report = paths.partition_root(3) / "merge" / "merge_report.json"
    relative_artifact = artifact.relative_to(paths.phase_paths.project.artifacts_root)
    relative_report = report.relative_to(paths.phase_paths.project.artifacts_root)

    classified_artifact = classify_artifact_path(relative_artifact)
    assert classified_artifact.role is ArtifactRole.PARTITION_ARTIFACT
    assert classified_artifact.phase == "metadata"
    assert classified_artifact.run_id == "run-1"
    assert classified_artifact.partition_id == 3

    classified_report = classify_artifact_path(relative_report)
    assert classified_report.role is ArtifactRole.PARTITION_ARTIFACT
    assert classified_report.partition_id == 3

    helpers_root = partition_merge_root_in(paths.run_root, 3)
    assert (
        partition_artifact_path_in(paths.run_root, 3, "submission_metadata.parquet")
        == helpers_root / "submission_metadata.parquet"
    )
    assert (
        partition_merge_report_path_in(paths.run_root, 3)
        == helpers_root / MERGE_REPORT_NAME
    )


def test_partition_artifact_filename_must_be_a_basename():
    with pytest.raises(ValueError):
        partition_artifact_path_in("run", 1, "nested/submission_metadata.parquet")
    with pytest.raises(ValueError):
        partition_artifact_path_in("run", 1, "")
