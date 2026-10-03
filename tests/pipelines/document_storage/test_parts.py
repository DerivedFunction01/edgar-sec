"""Unit tests for document_storage.parts."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.manifests import SnapshotPart
from edgar_sec.pipelines.document_storage.parts import (
    INDEX_COLUMNS,
    PAYLOAD_COLUMNS,
    PartError,
    PlannedPart,
    payload_doc_ids,
    plan_parts,
    quarter_path,
    read_part,
    relation_for_parts,
    validate_part_paths,
    write_index_part,
    write_payload_part,
)


def _part(kind: str = "index") -> PlannedPart:
    return PlannedPart(
        path=quarter_path(2024, "Q1", kind),
        kind=kind,
        doc_ids=("doc-a", "doc-b"),
        estimated_bytes=128,
    )


def test_quarter_path_is_snapshot_relative() -> None:
    """A part only has meaning with the snapshot that owns it, so the recorded
    path omits the snapshot id rather than resolving against a shared root."""
    assert quarter_path(2024, "Q1", "index") == "parts/index/2024-Q1.parquet"


def test_plan_parts_splits_on_the_byte_budget_not_the_row_count() -> None:
    """Normalized text is wildly uneven, so a row-count split produces parts
    differing by orders of magnitude in bytes."""
    parts = plan_parts(
        [("small", 10), ("big", 5_000), ("medium", 100)],
        year=2024,
        quarter="Q1",
        target_bytes=1_000,
        kind="payload",
    )
    assert [part.doc_ids for part in parts] == [("small",), ("big",), ("medium",)]


def test_plan_parts_coalesces_within_budget() -> None:
    parts = plan_parts(
        [("a", 10), ("b", 20), ("c", 30)],
        year=2024,
        quarter="Q1",
        target_bytes=1_000,
        kind="index",
    )
    assert len(parts) == 1
    assert parts[0].doc_ids == ("a", "b", "c")


def test_plan_parts_rejects_an_empty_budget() -> None:
    with pytest.raises(PartError, match="target_bytes must be positive"):
        plan_parts(
            [("a", 1)],
            year=2024,
            quarter="Q1",
            target_bytes=0,
            kind="index",
        )


def test_plan_parts_of_nothing_is_no_parts() -> None:
    assert (
        plan_parts([], year=2024, quarter="Q1", target_bytes=1_000, kind="index") == []
    )


def test_index_and_payload_parts_round_trip(tmp_path: Path) -> None:
    part = _part("index")
    written = write_index_part(
        tmp_path,
        part,
        [
            {
                "occurrence_id": "occ-a",
                "doc_id": "doc-a",
                "clean_text": "unused",
                "byte_size": "12",
            }
        ],
    )
    assert written.kind == "index"
    assert written.row_count == 1
    assert read_part(tmp_path, written).column("occurrence_id").to_pylist() == ["occ-a"]


def test_payload_part_records_its_document_ids(tmp_path: Path) -> None:
    part = _part("payload")
    written = write_payload_part(
        tmp_path, part, [("doc-a", "text a"), ("doc-b", "text b")]
    )
    assert payload_doc_ids(read_part(tmp_path, written).to_pylist()) == (
        "doc-a",
        "doc-b",
    )
    assert written.doc_ids == ("doc-a", "doc-b")


def test_part_kinds_project_disjoint_column_sets() -> None:
    """Index and payload are two projections of one logical record, split so a
    consumer can read metadata without the text."""
    assert "clean_text" in PAYLOAD_COLUMNS
    assert "clean_text" not in INDEX_COLUMNS
    assert "occurrence_id" in INDEX_COLUMNS


def test_validate_part_paths_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PartError, match="part file is missing"):
        validate_part_paths(
            [SnapshotPart(path="parts/index/2024-Q1.parquet", kind="index")],
            tmp_path,
        )


def test_validate_part_paths_rejects_an_escaping_path(tmp_path: Path) -> None:
    with pytest.raises(PartError, match="escapes the snapshots root"):
        validate_part_paths(
            [SnapshotPart(path="../outside.parquet", kind="index")], tmp_path
        )


def test_validate_part_paths_rejects_quote_shaped_paths(tmp_path: Path) -> None:
    """A recorded path is interpolated into SQL and a manifest can be edited on
    disk, so the injection surface is checked at the boundary."""
    for hostile in ("it's.parquet", 'a"b.parquet', "a;b.parquet"):
        with pytest.raises(PartError, match="unsafe character"):
            validate_part_paths([SnapshotPart(path=hostile, kind="index")], tmp_path)


def test_relation_for_parts_escapes_its_own_file_list(tmp_path: Path) -> None:
    (tmp_path / "it's.parquet").write_bytes(b"")
    relation = relation_for_parts(
        [SnapshotPart(path="it's.parquet", kind="index")], tmp_path
    )
    assert "it''s.parquet" in relation
    assert f"read_parquet(['{tmp_path}/it''s.parquet'])" in relation


def test_relation_for_parts_refuses_an_empty_part_list(tmp_path: Path) -> None:
    with pytest.raises(PartError, match="zero parts"):
        relation_for_parts([], tmp_path)


def test_read_part_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PartError, match="snapshot part not found"):
        read_part(
            tmp_path, SnapshotPart(path="parts/index/2024-Q1.parquet", kind="index")
        )
