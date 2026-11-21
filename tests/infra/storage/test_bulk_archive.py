from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore

SOURCE_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            # Fixed timestamp: a wall-clock entry time would make the
            # "identical bytes" payloads differ across a 2 s boundary.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            archive.writestr(info, payload)
    return buffer.getvalue()


def _put(store: BulkArchiveStore, tmp_path: Path, tag: str, fetched_at: str):
    payload = _zip_bytes({f"CIK{tag}.json": json.dumps({"cik": tag}).encode()})
    source = tmp_path / f"incoming-{tag}.zip"
    source.write_bytes(payload)
    return store.put_file(
        "submissions_bulk", source, source_url=SOURCE_URL, fetched_at=fetched_at
    )


def test_put_stores_payload_manifest_and_member_index(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store")
    reference = _put(store, tmp_path, "0000000001", "2026-11-06T08:00:00+00:00")

    assert reference.path.is_file()
    assert reference.member_index_path.is_file()
    assert reference.path.parent.name == reference.sha256
    assert reference.path.parent.parent.name == "submissions_bulk"
    manifest = reference.manifest
    assert manifest.source_url == SOURCE_URL
    assert manifest.sha256 == reference.sha256
    assert manifest.member_count == 1
    assert manifest.byte_size == reference.path.stat().st_size
    assert manifest.fetched_at == "2026-11-06T08:00:00+00:00"

    index = store.member_index(reference)
    assert index.column("member_name").to_pylist() == ["CIK0000000001.json"]
    with zipfile.ZipFile(reference.path) as archive:
        expected_crc = archive.getinfo("CIK0000000001.json").CRC
    assert index.column("crc32").to_pylist() == [expected_crc]
    assert (
        store.read_member(reference, "CIK0000000001.json")
        == json.dumps({"cik": "0000000001"}).encode()
    )


def test_put_identical_bytes_is_a_noop(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store")
    first = _put(store, tmp_path, "0000000002", "2026-11-06T08:00:00+00:00")
    second = _put(store, tmp_path, "0000000002", "2026-11-07T08:00:00+00:00")

    assert second == first
    assert second.manifest.fetched_at == "2026-11-06T08:00:00+00:00"
    assert len(store.list_archives("submissions_bulk")) == 1


def test_open_returns_newest_and_absence_is_none(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store")
    assert store.open("submissions_bulk") is None
    _put(store, tmp_path, "0000000003", "2026-11-05T08:00:00+00:00")
    newest = _put(store, tmp_path, "0000000004", "2026-11-06T08:00:00+00:00")

    assert store.open("submissions_bulk") == newest
    assert store.open("submissions_bulk", newest.sha256) == newest
    assert store.open("submissions_bulk", "0" * 64) is None
    assert store.open("companyfacts_bulk") is None


def test_pruning_keeps_exactly_the_retention_count(tmp_path: Path) -> None:
    for retention, expected_kept in ((2, 2), (5, 3)):
        store = BulkArchiveStore(tmp_path / f"store-{retention}", retention=retention)
        kept = [
            _put(store, tmp_path, f"000000001{i}", f"2026-11-0{i}T08:00:00+00:00")
            for i in (1, 2, 3)
        ]
        archives = store.list_archives("submissions_bulk")
        assert [ref.sha256 for ref in archives] == [
            ref.sha256 for ref in kept[-expected_kept:][::-1]
        ]


def test_retention_resolves_from_the_environment_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEC_BULK_ARCHIVE_RETENTION", "1")
    store = BulkArchiveStore(tmp_path / "store")
    _put(store, tmp_path, "0000000021", "2026-11-05T08:00:00+00:00")
    newest = _put(store, tmp_path, "0000000022", "2026-11-06T08:00:00+00:00")

    assert store.retention == 1
    assert store.list_archives("submissions_bulk") == [newest]


def test_read_member_rejects_an_unknown_member(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store")
    reference = _put(store, tmp_path, "0000000031", "2026-11-06T08:00:00+00:00")

    with pytest.raises(ValueError, match="not in archive"):
        store.read_member(reference, "CIK9999999999.json")


def test_distinct_sources_do_not_share_retention(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store", retention=1)
    payload = _zip_bytes({"x.json": b"{}"})
    source = tmp_path / "incoming.zip"
    source.write_bytes(payload)
    digest = sha256_bytes(payload)
    for source_id in ("submissions_bulk", "companyfacts_bulk"):
        reference = store.put_file(
            source_id,
            source,
            source_url=SOURCE_URL,
            fetched_at="2026-11-06T08:00:00+00:00",
        )
        assert reference.sha256 == digest
        assert store.open(source_id) == reference


def test_read_member_inflates_a_deflated_member(tmp_path: Path) -> None:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CIK0000000041.json", b'{"cik": "0000000041"}' * 50)
    source = tmp_path / "incoming-deflated.zip"
    source.write_bytes(buffer.getvalue())
    store = BulkArchiveStore(tmp_path / "store")
    reference = store.put_file(
        "submissions_bulk",
        source,
        source_url=SOURCE_URL,
        fetched_at="2026-11-06T08:00:00+00:00",
    )

    assert store.read_member(reference, "CIK0000000041.json") == (
        b'{"cik": "0000000041"}' * 50
    )


def test_put_non_zip_payload_stores_with_empty_member_index(tmp_path: Path) -> None:
    store = BulkArchiveStore(tmp_path / "store")
    source = tmp_path / "report.csv"
    source.write_bytes(b"CIK,Registrant_Name\n12345,EXAMPLE BDC\n")
    reference = store.put_file(
        "bdc_report",
        source,
        source_url="https://www.sec.gov/example.csv",
        fetched_at="2026-11-08T00:00:00+00:00",
    )
    assert reference.path.is_file()
    assert reference.manifest.member_count == 0
    assert store.member_index(reference).num_rows == 0
