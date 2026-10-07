"""Snapshot part-list resolution: a pre-multipart snapshot still resolves, and a
tampered, truncated, or partial one is refused rather than read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SNAPSHOT_MANIFEST_VERSION,
    SnapshotLayoutError,
    load_snapshot_manifest,
    read_snapshot_parts,
)


def _table(n: int) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {f.name: None for f in SUBMISSION_METADATA_SCHEMA}
            | {"cik": f"00000000{index:02d}", "cik_padded": f"00000000{index:02d}"}
            for index in range(n)
        ],
        schema=SUBMISSION_METADATA_SCHEMA,
    )


def _multipart(tmp_path: Path, count: int = 3) -> Path:
    """Publish a multipart snapshot manifest with ``count`` parts."""
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir(parents=True)
    entries = []
    for index in range(count):
        path = parts_dir / f"part-{index:05d}.parquet"
        pq.write_table(_table(1), path)
        entries.append(
            {
                "path": f"parts/{path.name}",
                "part_index": index,
                "source": f"chunk:{index}",
                "row_count": 1,
                "byte_count": path.stat().st_size,
                "sha256": file_sha256(path),
                "schema_version": "1.0.0",
            }
        )
    manifest_path = tmp_path / "metadata.manifest.json"
    atomic_write_json(
        manifest_path,
        {
            "manifest_version": SNAPSHOT_MANIFEST_VERSION,
            "snapshot_id": "snap1",
            "output_path": "",
            "artifact_sha256": "",
            "row_count": count,
            "part_count": count,
            "parts": entries,
        },
        canonical=False,
        indent=2,
    )
    return manifest_path


def test_a_multipart_manifest_resolves_to_its_parts(tmp_path: Path) -> None:
    parts = read_snapshot_parts(_multipart(tmp_path))
    assert parts.part_count == 3
    assert parts.row_count == 3
    assert [p.name for p in parts.paths] == [
        "part-00000.parquet",
        "part-00001.parquet",
        "part-00002.parquet",
    ]
    assert parts.layout.multipart is True
    assert parts.sql_sources()[0].endswith("part-00000.parquet")


def test_a_tampered_part_is_refused(tmp_path: Path) -> None:
    manifest = _multipart(tmp_path)
    victim = tmp_path / "parts" / "part-00001.parquet"
    pq.write_table(_table(5), victim)

    with pytest.raises(SnapshotLayoutError, match="digest mismatch"):
        read_snapshot_parts(manifest)


def test_a_missing_part_is_refused_as_an_incomplete_publication(
    tmp_path: Path,
) -> None:
    manifest = _multipart(tmp_path)
    (tmp_path / "parts" / "part-00001.parquet").unlink()

    with pytest.raises(SnapshotLayoutError, match="not fully published"):
        read_snapshot_parts(manifest)


def test_an_unlisted_part_on_disk_is_not_part_of_the_snapshot(tmp_path: Path) -> None:
    """A file the manifest does not name is untrusted data, not a part."""
    manifest = _multipart(tmp_path)
    pq.write_table(_table(9), tmp_path / "parts" / "part-00099.parquet")

    parts = read_snapshot_parts(manifest)
    assert parts.part_count == 3
    assert "part-00099.parquet" not in {p.name for p in parts.paths}


def test_a_repeated_part_path_is_refused(tmp_path: Path) -> None:
    manifest = _multipart(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["parts"][1]["path"] = document["parts"][0]["path"]
    atomic_write_json(manifest, document, canonical=False)

    with pytest.raises(SnapshotLayoutError, match="repeats path"):
        read_snapshot_parts(manifest)


def test_a_part_without_a_digest_is_refused(tmp_path: Path) -> None:
    manifest = _multipart(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["parts"][0].pop("sha256")
    atomic_write_json(manifest, document, canonical=False)

    with pytest.raises(SnapshotLayoutError, match="no digest"):
        read_snapshot_parts(manifest)


def test_a_manifest_naming_no_payload_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "metadata.manifest.json"
    atomic_write_json(manifest, {"snapshot_id": "empty"}, canonical=False)

    with pytest.raises(SnapshotLayoutError, match="names no payload"):
        read_snapshot_parts(manifest)


def test_a_missing_manifest_is_a_file_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_snapshot_parts(tmp_path / "absent.json")


def test_a_non_object_manifest_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "metadata.manifest.json"
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(SnapshotLayoutError, match="not a JSON object"):
        load_snapshot_manifest(manifest)


def test_verification_can_be_skipped_for_a_metadata_only_read(
    tmp_path: Path,
) -> None:
    manifest = _multipart(tmp_path)
    (tmp_path / "parts" / "part-00000.parquet").write_bytes(b"not parquet")

    with pytest.raises(SnapshotLayoutError):
        read_snapshot_parts(manifest)

    parts = read_snapshot_parts(manifest, verify_digests=False)
    assert parts.part_count == 3


def test_dag_node_manifest_is_readable_by_snapshot_parts(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    part = parts_dir / "part-00000.parquet"
    part.write_bytes(b"mock")
    atomic_write_json(
        manifest_path,
        {
            "snapshot_id": "snap-dag",
            "kind": "checkpoint",
            "relations": {
                "submissions": [
                    {
                        "path": "parts/part-00000.parquet",
                        "sha256": file_sha256(part),
                        "row_count": 42,
                    }
                ]
            },
        },
        canonical=False,
    )
    parts = read_snapshot_parts(manifest_path)
    assert parts.part_count == 1
    assert parts.row_count == 42
    assert parts.paths == (part,)
