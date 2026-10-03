from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.atomic import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)


def test_atomic_text_and_bytes_writes(tmp_path: Path) -> None:
    text_file = tmp_path / "sample.txt"
    bytes_written = atomic_write_text(text_file, "hello atomic world")
    assert bytes_written > 0
    assert text_file.read_text(encoding="utf-8") == "hello atomic world"

    bin_file = tmp_path / "sample.bin"
    atomic_write_bytes(bin_file, b"\x00\x01\x02\x03")
    assert bin_file.read_bytes() == b"\x00\x01\x02\x03"


def test_atomic_json_write_is_canonical(tmp_path: Path) -> None:
    json_file = tmp_path / "sample.json"
    atomic_write_json(json_file, {"b": 2, "a": 1})
    assert json_file.read_text(encoding="utf-8") == '{"a":1,"b":2}'


def test_atomic_json_create_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "sample.json"
    atomic_write_json(nested, {"k": "v"})
    assert nested.is_file()
