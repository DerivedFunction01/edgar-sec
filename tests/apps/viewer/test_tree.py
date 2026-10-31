"""Tests for the lazy filesystem tree and text reader."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pytest

from edgar_sec.apps.viewer.model import DatasetError, artifact_id
from edgar_sec.apps.viewer.tree import read_text_file, tree_children


def _children(root: Path, relative: str) -> list[dict]:
    return tree_children(root, artifact_id(relative))


def test_tree_lists_supported_files_and_hides_binary(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    folder = root / "nested"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("hello", encoding="utf-8")
    (folder / "rows.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (folder / "rows.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (folder / "image.bin").write_bytes(b"\x00\x01\x02")

    nodes = _children(root, "nested")
    by_name = {node["name"]: node for node in nodes}
    assert by_name["notes.txt"]["format"] == "text"
    assert by_name["rows.csv"]["format"] == "csv"
    assert by_name["rows.jsonl"]["format"] == "jsonl"
    assert "image.bin" not in by_name


def test_tree_skips_symlinked_files_and_directories(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    (root / "linked.txt").symlink_to(secret)
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)

    assert tree_children(root) == []


def test_database_is_one_tree_node_with_lazy_table_children(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "sample.duckdb"
    conn = duckdb.connect(str(path))
    try:
        conn.execute("CREATE TABLE alpha (id INTEGER)")
        conn.execute("CREATE TABLE beta (id INTEGER)")
    finally:
        conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    nodes = tree_children(root)
    assert len(nodes) == 1
    assert nodes[0]["node_type"] == "database"
    assert nodes[0]["format"] == "duckdb"
    tables = _children(root, "sample.duckdb")
    assert [node["name"] for node in tables] == ["main.alpha", "main.beta"]
    assert all(node["node_type"] == "table" for node in tables)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_text_reader_returns_bounded_byte_pages(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "notes.txt").write_text("0123456789", encoding="utf-8")
    file_id = artifact_id("notes.txt")

    first = read_text_file(root, file_id, limit=4)
    second = read_text_file(root, file_id, offset=first["next_offset"], limit=4)
    third = read_text_file(root, file_id, offset=second["next_offset"], limit=4)

    assert first["text"] == "0123" and first["has_more"] is True
    assert second["text"] == "4567" and second["has_more"] is True
    assert third["text"] == "89" and third["has_more"] is False


def test_text_reader_rejects_database_files(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "rows.parquet").write_bytes(b"PAR1\x00")
    with pytest.raises(DatasetError, match="text document"):
        read_text_file(root, artifact_id("rows.parquet"))
