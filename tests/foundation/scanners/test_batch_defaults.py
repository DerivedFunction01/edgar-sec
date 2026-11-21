from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.base import ScannerFinding
from edgar_sec.foundation.scanners.batch_defaults import scan_batch_defaults


def _scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> list[ScannerFinding]:
    package = tmp_path / "edgar_sec"
    package.mkdir()
    (package / "sample.py").write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return scan_batch_defaults()


def _scan_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> list[ScannerFinding]:
    owner = tmp_path / "edgar_sec" / "foundation"
    owner.mkdir(parents=True)
    (owner / "io.py").write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return scan_batch_defaults()


def test_flags_shared_symbols_defined_outside_their_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        "DEFAULT_ROW_GROUP_SIZE = 128_000\n",
    )

    assert len(findings) == 1
    assert findings[0].message.startswith("DEFAULT_ROW_GROUP_SIZE is owned by")


def test_flags_known_batch_literals_but_allows_other_equal_or_local_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """def read(batch_size: int = 4096):
    return read_rows(batch_size=4096, row_group_size=128_000)

def stream(parquet):
    return parquet.iter_batches(batch_size=65_536)

def local_policy(chunk_size: int = 1000):
    return fetchmany(100), max_rows(10000)
""",
    )

    assert [(finding.line, finding.message) for finding in findings] == [
        (1, "literal 4096 duplicates the shared read batch default"),
        (2, "literal 4096 duplicates the shared read batch default"),
        (2, "literal 128000 duplicates the shared Parquet row group default"),
        (5, "literal 65536 duplicates the shared Parquet read batch default"),
    ]


def test_flags_repeated_sql_insert_batch_literals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        "for start in range(0, len(rows), 1000):\n    pass\n",
    )

    assert len(findings) == 1
    assert (
        findings[0].message
        == "literal 1000 duplicates the shared SQL insert batch default"
    )


def test_flags_duplicate_document_payload_target_expressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        "PAYLOAD_TARGET_BYTES: int = 96 * 1024 * 1024\n",
    )

    assert len(findings) == 1
    assert "duplicates the document payload target" in findings[0].message


def test_flags_the_io_chunk_symbol_defined_outside_its_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(tmp_path, monkeypatch, "DEFAULT_IO_CHUNK_SIZE = 64 * 1024\n")

    assert len(findings) == 1
    assert findings[0].message.startswith("DEFAULT_IO_CHUNK_SIZE is owned by")


def test_the_io_chunk_owner_may_define_its_own_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan_owner(tmp_path, monkeypatch, "DEFAULT_IO_CHUNK_SIZE = 64 * 1024\n")

    assert findings == []


def test_flags_io_chunk_literals_at_streaming_buffer_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """def stream(source, response):
    return source.read(65536), response.iter_content(chunk_size=64 * 1024)

def compress(staged):
    return staged.read(read_size=65536), staged.write(write_size=65536)
""",
    )

    assert [(finding.line, finding.message) for finding in findings] == [
        (2, "literal 65536 duplicates the shared I/O chunk buffer default"),
        (2, "literal 65536 duplicates the shared I/O chunk buffer default"),
        (5, "literal 65536 duplicates the shared I/O chunk buffer default"),
        (5, "literal 65536 duplicates the shared I/O chunk buffer default"),
    ]


def test_equal_valued_limits_are_not_io_chunk_buffers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """MAX_TEXT_BYTES = 64 * 1024
MAX_HEADER_SIZE = 64 * 1024

def read(parquet):
    return parquet.iter_batches(batch_size=65_536)
""",
    )

    assert [(finding.line, finding.message) for finding in findings] == [
        (5, "literal 65536 duplicates the shared Parquet read batch default"),
    ]
