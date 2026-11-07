from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
from edgar_sec.infra.storage.member_index import MemberIndex, ensure_member_index

SOURCE_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"

MEMBERS = {
    "CIK0000000020.json": b'{"name": "FORD MOTOR CO"}' * 40,
    "CIK0000000020-submissions-001.json": b'{"filings": {}}' * 25,
    "CIK0000000007.json": b'{"name": "SEVEN"}',
    "CIK0000000003.json": b'{"name": "THREE"}' * 10,
}


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("CIK0000000020.json", "CIK0000000003.json"):
            archive.writestr(name, members[name], compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(
            "CIK0000000020-submissions-001.json",
            members["CIK0000000020-submissions-001.json"],
            compress_type=zipfile.ZIP_STORED,
        )
        with archive.open("CIK0000000007.json", "w", force_zip64=True) as handle:
            handle.write(members["CIK0000000007.json"])
    return path


def _open_index(zip_path: Path) -> MemberIndex:
    return MemberIndex(ensure_member_index(zip_path, file_sha256(zip_path)))


def test_index_matches_infolist_and_reads_every_member(tmp_path: Path) -> None:
    zip_path = _write_zip(tmp_path / "bulk.zip", MEMBERS)
    index = _open_index(zip_path)
    zip_fd = os.open(zip_path, os.O_RDONLY)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            assert len(index) == len(archive.infolist())
            for info in archive.infolist():
                entry = index.find(info.filename)
                assert entry is not None
                assert entry.header_offset == info.header_offset
                assert entry.compressed_size == info.compress_size
                assert entry.uncompressed_size == info.file_size
                assert entry.crc32 == info.CRC
                assert index.read_member(zip_fd, info.filename) == archive.read(info)
        assert index.find("CIK9999999999.json") is None
        assert index.read_member(zip_fd, "CIK9999999999.json") is None
    finally:
        os.close(zip_fd)
        index.close()


def test_index_reuse_is_a_noop_and_corruption_rebuilds(tmp_path: Path) -> None:
    zip_path = _write_zip(tmp_path / "bulk.zip", MEMBERS)
    first = ensure_member_index(zip_path, file_sha256(zip_path))
    stamp = first.stat().st_mtime_ns
    assert ensure_member_index(zip_path, file_sha256(zip_path)) == first
    assert first.stat().st_mtime_ns == stamp

    with open(first, "r+b") as handle:
        handle.write(b"GARBAGE!")
    rebuilt = _open_index(zip_path)
    try:
        assert rebuilt.find("CIK0000000007.json") is not None
    finally:
        rebuilt.close()


def test_index_builds_from_the_store_member_index(tmp_path: Path) -> None:
    source = _write_zip(tmp_path / "incoming.zip", MEMBERS)
    store = BulkArchiveStore(tmp_path / "store")
    reference = store.put_file("submissions_bulk", source, source_url=SOURCE_URL)

    index = _open_index(reference.path)
    zip_fd = os.open(reference.path, os.O_RDONLY)
    try:
        assert len(index) == reference.manifest.member_count
        for name, payload in MEMBERS.items():
            assert index.read_member(zip_fd, name) == payload
    finally:
        os.close(zip_fd)
        index.close()


def test_read_member_refuses_a_corrupt_member(tmp_path: Path) -> None:
    zip_path = _write_zip(tmp_path / "bulk.zip", MEMBERS)
    index_path = ensure_member_index(zip_path, file_sha256(zip_path))
    index = MemberIndex(index_path)
    entry = index.find("CIK0000000020-submissions-001.json")
    assert entry is not None
    with open(zip_path, "r+b") as handle:
        handle.seek(entry.header_offset + 100)
        handle.write(b"XX")
    zip_fd = os.open(zip_path, os.O_RDONLY)
    try:
        with pytest.raises(ValueError):
            index.read_member(zip_fd, "CIK0000000020-submissions-001.json")
    finally:
        os.close(zip_fd)
        index.close()
