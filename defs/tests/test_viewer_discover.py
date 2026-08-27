import pytest

from defs.viewer.discover import (
    artifact_id,
    artifact_path,
    discover_artifacts,
    discover_documents,
)

from viewer_fixtures import (  # noqa: F401 - fixtures registered via import
    artifacts_root,
    chunk_dataset,
    parquet_dataset,
)
from viewer_fixtures import base64_id


def test_discovery_classifies_and_groups_artifacts(
    artifacts_root, chunk_dataset, parquet_dataset
):
    datasets = discover_artifacts(artifacts_root)
    by_path = {item.relative_path: item for item in datasets}

    chunk = by_path[chunk_dataset["relative"].as_posix()]
    assert chunk.kind == "partition_chunk"
    assert chunk.phase == "metadata"
    assert chunk.run_id == "run-1"
    assert chunk.format == "jsonl"
    assert chunk.size_bytes > 0
    assert chunk.mtime is not None

    canonical = by_path[parquet_dataset["relative"].as_posix()]
    assert canonical.kind == "canonical"
    assert canonical.format == "parquet"
    assert canonical.run_id is None


def test_discovery_lists_documents_separately(artifacts_root):
    plan_relative = "metadata/runs/run-1/plan.json"
    (artifacts_root / plan_relative).parent.mkdir(parents=True, exist_ok=True)
    (artifacts_root / plan_relative).write_text("{}", encoding="utf-8")

    datasets = discover_artifacts(artifacts_root)
    documents = discover_documents(artifacts_root)

    assert all(item.id != artifact_id(plan_relative) for item in datasets)
    assert [item.relative_path for item in documents] == [plan_relative]
    assert documents[0].kind == "run_plan"


def test_discovery_ignores_unrelated_files(artifacts_root):
    (artifacts_root / "notes.txt").write_text("hello", encoding="utf-8")
    assert discover_artifacts(artifacts_root) == []
    assert discover_documents(artifacts_root) == []


def test_discovery_scales_to_multiple_phases_with_runs(artifacts_root):
    from defs.storage.jsonl import write_records_atomic

    for phase in ("metadata", "fixtures"):
        for chunk in ("chunk-00001", "chunk-00002"):
            relative = (
                f"{phase}/runs/run-1/partitions/partition-00001/chunks/{chunk}.jsonl"
            )
            path = artifacts_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            write_records_atomic([{"id": phase}], str(path))

    datasets = discover_artifacts(artifacts_root)
    unions = [item for item in datasets if item.kind == "run_union"]
    assert {(item.phase, item.run_id, item.format) for item in unions} == {
        ("metadata", "run-1", "jsonl"),
        ("fixtures", "run-1", "jsonl"),
    }
    phases = {item.phase for item in datasets}
    assert phases == {"metadata", "fixtures"}


def test_artifact_id_round_trip_and_traversal_guard(artifacts_root):
    relative = "metadata/runs/run-1/chunks/chunk-00001.jsonl"
    dataset_id = base64_id(relative)
    resolved = artifact_path(dataset_id, artifacts_root)
    assert resolved == artifacts_root / relative

    with pytest.raises(ValueError):
        artifact_path(base64_id("../../outside/secret.parquet"), artifacts_root)

    import base64 as b64

    with pytest.raises(ValueError):
        artifact_path(b64.b64encode(b"\xff\xfe").decode("ascii"), artifacts_root)
