import pytest
from viewer_fixtures import (  # noqa: F401 - fixtures registered via import
    artifacts_root,
    base64_id,
    chunk_dataset,
    parquet_dataset,
)

from defs.viewer.discover import (
    artifact_id,
    artifact_path,
    discover_artifacts,
    discover_documents,
)


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
    assert canonical.kind == "published_dataset"
    assert canonical.format == "parquet"
    assert canonical.run_id is None


def test_discovery_lists_documents_separately(artifacts_root):
    plan_relative = "transient/metadata/runs/run-1/plan.json"
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
            relative = f"transient/{phase}/runs/run-1/partitions/partition-00001/chunks/{chunk}.jsonl"
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


def test_revision_present_and_changes_on_rewrite(artifacts_root, chunk_dataset):
    from defs.viewer.discover import discover_artifacts

    before = discover_artifacts(artifacts_root)
    summary = next(
        item
        for item in before
        if item.relative_path == chunk_dataset["relative"].as_posix()
    )
    # revision is "<size_bytes>:<nanosecond mtime>"
    assert summary.revision.startswith(f"{summary.size_bytes}:")
    assert summary.revision.split(":")[1].isdigit()

    original = summary.revision
    path = chunk_dataset["path"]
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    after = discover_artifacts(artifacts_root)
    rewritten = next(
        item
        for item in after
        if item.relative_path == chunk_dataset["relative"].as_posix()
    )
    assert rewritten.revision != original
    assert rewritten.revision.startswith(f"{rewritten.size_bytes}:")


def test_union_revision_changes_when_chunk_added(artifacts_root):
    from defs.storage.jsonl import write_records_atomic
    from defs.viewer.discover import discover_artifacts

    base = "transient/metadata/runs/run-2/partitions/partition-00001/chunks"
    for chunk in ("chunk-00001", "chunk-00002"):
        path = artifacts_root / base / f"{chunk}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_records_atomic([{"id": chunk}], str(path))

    first = discover_artifacts(artifacts_root)
    union = next(item for item in first if item.kind == "run_union")
    assert union.revision
    first_revision = union.revision

    path = artifacts_root / base / "chunk-00003.jsonl"
    write_records_atomic([{"id": "chunk-00003"}], str(path))

    second = discover_artifacts(artifacts_root)
    union2 = next(item for item in second if item.kind == "run_union")
    assert union2.revision != first_revision
    assert len(union2.source_paths) == 3
