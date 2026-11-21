"""Tests for bundle manifest writing, reading, and pipeline affinity."""

from __future__ import annotations

from pathlib import Path
import pytest

from edgar_sec.infra.distribution.guards import (
    assert_pipeline_affinity,
    read_bundle_manifest,
    write_bundle_manifest,
)
from edgar_sec.infra.distribution.partition import build_assignment


def test_bundle_manifest_round_trip(tmp_path: Path) -> None:
    """Verifies atomic write and read of bundle.json."""
    asgn = build_assignment("metadata", "work-123", "1" * 64, "worker-01", (0, 1, 2))
    manifest_path = write_bundle_manifest(tmp_path, asgn)
    assert manifest_path.is_file()

    loaded = read_bundle_manifest(tmp_path)
    assert loaded["pipeline"] == "metadata"
    assert loaded["work_id"] == "work-123"
    assert loaded["work_digest"] == "1" * 64
    assert loaded["assignment_id"] == asgn.assignment_id
    assert loaded["worker_id"] == "worker-01"
    assert loaded["chunk_ids"] == [0, 1, 2]


def test_assert_pipeline_affinity(tmp_path: Path) -> None:
    """Verifies pipeline affinity matches and rejects mismatches."""
    asgn = build_assignment("metadata", "work-123", "1" * 64, "worker-01", (0,))
    write_bundle_manifest(tmp_path, asgn)
    manifest = read_bundle_manifest(tmp_path)

    assert_pipeline_affinity(manifest, "metadata")
    with pytest.raises(ValueError, match="pipeline mismatch"):
        assert_pipeline_affinity(manifest, "inventory")


def test_unsupported_bundle_schema_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bundle.json").write_text(
        '{"schema_version": 99}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported bundle schema"):
        read_bundle_manifest(tmp_path)
