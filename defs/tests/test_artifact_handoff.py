from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.runtime.artifacts import (
    create_bundle,
    find_manifests,
    import_bundle,
    make_manifest,
    publish_manifest,
    resolve_manifest,
    resolve_source,
)


def test_manifest_is_relative_and_bundle_round_trips(tmp_path):
    root = tmp_path / "workspace"
    artifact = root / "phase" / "run" / "data.parquet"
    artifact.parent.mkdir(parents=True)
    pq.write_table(pa.table({"value": [1, 2]}), artifact)
    manifest = make_manifest(
        dataset="example",
        phase="phase",
        run_id="run",
        schema_version="1",
        artifact_path=str(artifact),
        artifacts_root=str(root),
        row_count=2,
    )
    assert "/" not in manifest["artifact_path"][:1]
    publish_manifest(manifest, artifacts_root=str(root))
    bundle = tmp_path / "bundle.zip"
    create_bundle(
        [manifest["artifact_id"]], artifacts_root=str(root), output=str(bundle)
    )
    destination = tmp_path / "imported"
    destination.mkdir()
    assert import_bundle(str(bundle), artifacts_root=str(destination)) == [
        manifest["artifact_id"]
    ]
    restored, path = resolve_manifest(
        manifest["artifact_id"], artifacts_root=str(destination)
    )
    assert restored == manifest
    assert path.exists()


def test_manifest_rejects_absolute_path(tmp_path):
    artifact = tmp_path / "data.parquet"
    pq.write_table(pa.table({"value": [1]}), artifact)
    manifest = make_manifest(
        dataset="example",
        phase="phase",
        run_id="run",
        schema_version="1",
        artifact_path=str(artifact),
        artifacts_root=str(tmp_path),
        row_count=1,
    )
    manifest["artifact_path"] = "/tmp/escape.parquet"
    with pytest.raises(ValueError, match="relative"):
        publish_manifest(manifest, artifacts_root=str(tmp_path))


def test_resolve_source_prefers_final_then_partitions(tmp_path):
    root = tmp_path / "workspace"
    p1_file = root / "metadata" / "p1.parquet"
    p1_file.parent.mkdir(parents=True)
    pq.write_table(pa.table({"id": [1]}), p1_file)

    p1_manifest = make_manifest(
        dataset="submissions",
        phase="metadata",
        run_id="r1",
        schema_version="1.0.0",
        artifact_path=str(p1_file),
        artifacts_root=str(root),
        row_count=1,
        partition="partition-00001",
    )
    publish_manifest(p1_manifest, artifacts_root=str(root))

    # Without final, resolve_source returns the partition
    manifests, paths = resolve_source(
        "submissions", phase="metadata", artifacts_root=str(root)
    )
    assert len(manifests) == 1
    assert manifests[0]["artifact_id"] == p1_manifest["artifact_id"]
    assert paths == [p1_file]

    # When final is published, resolve_source prefers final
    final_file = root / "metadata" / "canonical" / "submissions.parquet"
    final_file.parent.mkdir(parents=True)
    pq.write_table(pa.table({"id": [1, 2]}), final_file)

    final_manifest = make_manifest(
        dataset="submissions",
        phase="metadata",
        run_id="r1",
        schema_version="1.0.0",
        artifact_path=str(final_file),
        artifacts_root=str(root),
        row_count=2,
    )
    publish_manifest(final_manifest, artifacts_root=str(root))

    manifests_final, paths_final = resolve_source(
        "submissions", phase="metadata", artifacts_root=str(root)
    )
    assert len(manifests_final) == 1
    assert manifests_final[0]["artifact_id"] == final_manifest["artifact_id"]
    assert paths_final == [final_file]

    # Explicit partition request returns that partition specifically
    manifests_p1, paths_p1 = resolve_source(
        "submissions", phase="metadata", partition_id=1, artifacts_root=str(root)
    )
    assert len(manifests_p1) == 1
    assert manifests_p1[0]["artifact_id"] == p1_manifest["artifact_id"]
    assert paths_p1 == [p1_file]


def test_find_manifests_discovers_final_and_partitions(tmp_path):

    root = tmp_path / "workspace"
    artifact = root / "metadata" / "canonical" / "submission_metadata.parquet"
    artifact.parent.mkdir(parents=True)
    pq.write_table(pa.table({"value": [10, 20]}), artifact)

    manifest = make_manifest(
        dataset="submission_metadata",
        phase="metadata",
        run_id="r1",
        schema_version="1.0.0",
        artifact_path=str(artifact),
        artifacts_root=str(root),
        row_count=2,
    )
    publish_manifest(manifest, artifacts_root=str(root))

    results = find_manifests(
        "submission_metadata",
        phase="metadata",
        scope="final",
        artifacts_root=str(root),
    )
    assert len(results) == 1
    assert results[0]["artifact_id"] == manifest["artifact_id"]
    assert results[0]["dataset"] == "submission_metadata"


def test_prepare_bundle_for_phase_round_trips(tmp_path):
    from defs.runtime.artifacts import (
        import_bundle,
        prepare_bundle_for_phase,
        resolve_dependencies,
    )
    from defs.runtime.registry import PhaseDependency

    root = tmp_path / "workspace"
    p1_file = (
        root
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    )
    p1_file.parent.mkdir(parents=True)
    pq.write_table(pa.table({"id": [1, 2, 3]}), p1_file)

    manifest = make_manifest(
        dataset="submission_metadata",
        phase="metadata",
        run_id="run_phase1",
        schema_version="1.0.0",
        artifact_path=str(p1_file),
        artifacts_root=str(root),
        row_count=3,
    )
    publish_manifest(manifest, artifacts_root=str(root))

    # Test resolve_dependencies
    deps = [PhaseDependency(phase="metadata", dataset="submission_metadata")]
    resolved = resolve_dependencies(deps, artifacts_root=str(root))
    assert len(resolved) == 1
    assert resolved[0]["artifact_id"] == manifest["artifact_id"]

    # Test prepare_bundle_for_phase
    bundle_path = tmp_path / "phase2_inputs.zip"
    out_path, bundled_manifests = prepare_bundle_for_phase(
        "filing-catalog", output=str(bundle_path), artifacts_root=str(root)
    )
    assert out_path == str(bundle_path)
    assert len(bundled_manifests) == 1
    assert bundle_path.is_file()

    # Import bundle into clean destination workspace
    colab_dest = tmp_path / "colab_workspace"
    imported_ids = import_bundle(str(bundle_path), artifacts_root=str(colab_dest))
    assert imported_ids == [manifest["artifact_id"]]

    # Verify that target phase can resolve dependencies immediately on new workspace
    dest_manifests, dest_paths = resolve_source(
        "submission_metadata", phase="metadata", artifacts_root=str(colab_dest)
    )
    assert len(dest_manifests) == 1
    assert dest_paths[0].exists()
