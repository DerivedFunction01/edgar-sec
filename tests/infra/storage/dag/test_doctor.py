"""Tests for graph integrity auditing."""

from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.doctor import audit_graph
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    PartDescriptor,
    write_manifest,
)


def test_doctor_audits_integrity(tmp_path: Path) -> None:
    # 1. Healthy checkpoint c0
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    part_file = c0_dir / "data.parquet"
    part_file.write_bytes(b"parquet_bytes_placeholder")
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "data": (
                PartDescriptor(
                    "data.parquet",
                    "hash",
                    10,
                    part_file.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    write_manifest(c0_dir / "manifest.json", c0_manifest)

    (tmp_path / "current").mkdir()
    atomic_write_json(tmp_path / "current" / "pointer.json", {"snapshot_id": "c0"})

    audit_healthy = audit_graph(tmp_path)
    assert audit_healthy.is_healthy is True
    assert len(audit_healthy.errors) == 0

    # 2. Corrupt part size
    part_file.write_bytes(b"modified_bytes_with_different_size")
    audit_corrupt = audit_graph(tmp_path)
    assert audit_corrupt.is_healthy is False
    assert any("byte size mismatch" in err for err in audit_corrupt.errors)


def test_doctor_audits_digest_mismatch(tmp_path: Path) -> None:
    """Verify doctor flags SHA-256 digest mismatches when verify_digests=True."""
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    part_file = c0_dir / "data.parquet"
    part_file.write_bytes(b"same_length_data_1")
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "data": (
                PartDescriptor(
                    "data.parquet",
                    "0000000000000000000000000000000000000000000000000000000000000000",
                    10,
                    part_file.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    write_manifest(c0_dir / "manifest.json", c0_manifest)
    (tmp_path / "current").mkdir(exist_ok=True)
    atomic_write_json(tmp_path / "current" / "pointer.json", {"snapshot_id": "c0"})

    assert audit_graph(tmp_path, verify_digests=False).is_healthy is True
    audit_digests = audit_graph(tmp_path, verify_digests=True)
    assert audit_digests.is_healthy is False
    assert any("digest mismatch" in err for err in audit_digests.errors)
