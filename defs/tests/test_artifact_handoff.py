from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.runtime.artifacts import (
    create_bundle,
    discover_legacy_manifests,
    import_bundle,
    make_manifest,
    publish_manifest,
    resolve_manifest,
)
from defs.storage.artifacts import file_sha256


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


def test_legacy_merge_report_can_bootstrap_manifest(tmp_path):
    root = tmp_path / "artifacts"
    output = root / "metadata" / "runs" / "local" / "merge" / "data.parquet"
    output.parent.mkdir(parents=True)
    pq.write_table(pa.table({"value": [1]}), output)
    report = output.parent / "merge_report.json"
    report.write_text(
        json.dumps(
            {
                "output_path": str(output),
                "artifact_sha256": file_sha256(str(output)),
                "row_count": 1,
            }
        ),
        encoding="utf-8",
    )
    manifests = discover_legacy_manifests(artifacts_root=str(root), publish=True)
    assert len(manifests) == 1
    assert (
        root / "artifact-manifests" / f"{manifests[0]['artifact_id']}.json"
    ).exists()
