"""Unit tests for infra.storage.manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.manifests import (
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
    ManifestError,
    SnapshotPart,
    SnapshotReader,
    dependents_of,
    expand_dependency_closure,
    list_snapshots,
    read_manifest,
    read_pointer,
    resolved_parts,
    snapshot_dir,
    snapshot_identity,
    write_manifest,
)


def _publish(
    root: Path,
    snapshot_id: str,
    *,
    operation: str = "consolidate",
    parts: tuple[tuple[str, str], ...] = (
        ("index/index-0000.parquet", PART_KIND_INDEX),
    ),
    source_ids: tuple[str, ...] = (),
) -> Path:
    """Publish one snapshot with the given part paths and write the files."""
    target = snapshot_dir(root, snapshot_id)
    for relative, _kind in parts:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")
    manifest = {
        "snapshot_id": snapshot_id,
        "schema_version": "1",
        "run_id": "run-1",
        "source_snapshot_ids": list(source_ids),
        "resolved_parts": [
            {"path": relative, "kind": kind, "row_count": 1, "byte_size": 7}
            for relative, kind in parts
        ],
    }
    write_manifest(
        root, manifest, dataset="test_ds", phase="test_phase", set_current=False
    )
    return target


def test_part_path_resolves_against_the_snapshot_directory(tmp_path: Path) -> None:
    """A recorded part path is snapshot-relative, so the snapshot id must be kept.

    Anchoring at the snapshots root instead would resolve every snapshot's parts
    into the same wrong location.
    """
    root = tmp_path / "snapshots"
    target = _publish(root, "snap-1")
    reader = SnapshotReader(snapshots_root=root, snapshot_id="snap-1")
    part = reader.parts(PART_KIND_INDEX)[0]
    assert reader.part_path(part) == target / "index" / "index-0000.parquet"
    assert reader.part_path(part).is_file()


def test_part_paths_of_two_snapshots_do_not_collide(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    _publish(root, "snap-1")
    _publish(root, "snap-2")
    first = SnapshotReader(root, "snap-1").parts(PART_KIND_INDEX)[0]
    second = SnapshotReader(root, "snap-2").parts(PART_KIND_INDEX)[0]
    resolved = {
        SnapshotReader(root, "snap-1").part_path(first),
        SnapshotReader(root, "snap-2").part_path(second),
    }
    assert len(resolved) == 2
    assert all(path.is_file() for path in resolved)


def test_resolved_parts_filters_by_kind(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    _publish(
        root,
        "snap-1",
        parts=(
            ("index/index-0000.parquet", PART_KIND_INDEX),
            ("payload/payload-0000.parquet", PART_KIND_PAYLOAD),
        ),
    )
    manifest = read_manifest(root, "snap-1")
    assert [part.kind for part in resolved_parts(manifest, PART_KIND_INDEX)] == [
        PART_KIND_INDEX
    ]
    assert [part.kind for part in resolved_parts(manifest, PART_KIND_PAYLOAD)] == [
        PART_KIND_PAYLOAD
    ]
    assert resolved_parts(manifest, "nope") == ()


def test_write_manifest_refuses_to_overwrite_a_published_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshots"
    _publish(root, "snap-1")
    with pytest.raises(ManifestError, match="already published"):
        write_manifest(
            root,
            {"snapshot_id": "snap-1"},
            dataset="test_ds",
            phase="test_phase",
            set_current=False,
        )


def test_list_snapshots_skips_an_unreadable_manifest(tmp_path: Path) -> None:
    """A damaged snapshot must not hide the healthy ones."""
    root = tmp_path / "snapshots"
    _publish(root, "good")
    broken = snapshot_dir(root, "broken")
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    found = [item["snapshot_id"] for item in list_snapshots(root)]
    assert found == ["good"]


def test_list_snapshots_on_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert list_snapshots(tmp_path / "nope") == []


def test_pointer_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    _publish(root, "snap-1")
    assert read_pointer(root) is None
    write_manifest(
        root,
        {"snapshot_id": "snap-2", "run_id": "run-9"},
        dataset="test_ds",
        phase="test_phase",
        set_current=True,
    )
    pointer = read_pointer(root)
    assert pointer is not None
    assert pointer["snapshot_id"] == "snap-2"
    assert pointer["run_id"] == "run-9"


def test_read_manifest_raises_for_an_unknown_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        read_manifest(tmp_path / "snapshots", "absent")


def test_snapshot_identity_is_deterministic_and_order_independent() -> None:
    kwargs = {
        "operation": "consolidate",
        "artifact_hashes": ["a", "b"],
        "schema_version": "1",
    }
    assert snapshot_identity(source_snapshot_ids=["s2", "s1"], **kwargs) == (
        snapshot_identity(source_snapshot_ids=["s1", "s2"], **kwargs)
    )
    assert snapshot_identity(source_snapshot_ids=["s1"], **kwargs) != (
        snapshot_identity(source_snapshot_ids=["s1", "s2"], **kwargs)
    )


def test_dependents_of_detects_shared_parts(tmp_path: Path) -> None:
    """Two snapshots sharing a part are entangled; deleting either breaks the other."""
    root = tmp_path / "snapshots"
    shared = (("shared/0000.parquet", PART_KIND_INDEX),)
    _publish(root, "snap-1", parts=shared)
    _publish(root, "snap-2", parts=shared)
    _publish(root, "solo", parts=(("own/0000.parquet", PART_KIND_INDEX),))
    manifests = list_snapshots(root)
    assert dependents_of(manifests, {"snap-1"}) == {"snap-1": {"snap-2"}}
    assert dependents_of(manifests, {"solo"}) == {}


def test_dependency_closure_expands_transitively(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    shared = (("shared/0000.parquet", PART_KIND_INDEX),)
    _publish(root, "a", parts=shared)
    _publish(root, "b", parts=shared)
    _publish(root, "c", parts=shared)
    closure = expand_dependency_closure(root, {"a"})
    assert closure == {"a", "b", "c"}


def test_snapshot_part_round_trips_through_dict() -> None:
    part = SnapshotPart(path="index/0.parquet", kind=PART_KIND_INDEX, doc_ids=("d1",))
    assert SnapshotPart.from_dict(part.to_dict()) == part


def test_snapshot_part_from_tolerates_a_sparse_dict() -> None:
    part = SnapshotPart.from_dict({"path": "p.parquet", "kind": "index"})
    assert part.doc_ids == ()
    assert part.row_count == 0
