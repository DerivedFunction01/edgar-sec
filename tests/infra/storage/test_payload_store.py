"""Tests for the content-addressed raw-payload store."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.storage.payload_store import (
    PayloadStore,
    PayloadStoreError,
    compress_payload,
    decompress_payload,
    make_payload_store,
    make_payload_store_reader,
)

KEY = "a" * 64
OTHER_KEY = "b" * 64


def _put(store: PayloadStore, payload: bytes, *, key: str = KEY) -> bool:
    return store.put(
        document_locator_key=key,
        blob_hash=sha256_bytes(payload),
        accession="0001234567-11-000001",
        document_path="acme-10k.htm",
        raw_payload=payload,
        mime_type="text/html",
        stored_at="2024-01-01T00:00:00Z",
    )


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "payloads.sqlite") as store:
        payload = b"<html><body>ACME</body></html>"
        assert _put(store, payload) is True
        assert store.get(KEY) == payload


def test_store_creates_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "deeper" / "payloads.sqlite"
    with make_payload_store(db_path) as store:
        _put(store, b"x")
    assert db_path.is_file()


def test_identical_bytes_are_idempotent(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        payload = b"same bytes"
        assert _put(store, payload) is True
        assert _put(store, payload) is False
        assert store.count() == 1


def test_changed_bytes_are_stored_alongside_the_old(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, b"v1")
        _put(store, b"v2")
        assert store.count() == 2
        assert store.get(KEY, sha256_bytes(b"v1")) == b"v1"
        assert store.get(KEY, sha256_bytes(b"v2")) == b"v2"


def test_latest_revision_wins_without_blob_hash(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, b"v1")
        _put(
            store,
            b"v2",
        )
        # Both share stored_at, so ordering falls back to insertion order.
        assert store.get(KEY) == b"v2"


def test_missing_payload_returns_none(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        assert store.get(OTHER_KEY) is None
        assert store.get(KEY, "0" * 64) is None
        assert store.has(OTHER_KEY) is False


def test_record_carries_identity_without_bytes(tmp_path: Path) -> None:
    payload = b"abc"
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, payload)
        record = store.get_record(KEY)
        assert record is not None
        assert record.document_locator_key == KEY
        assert record.blob_hash == sha256_bytes(payload)
        assert record.accession == "0001234567-11-000001"
        assert record.document_path == "acme-10k.htm"
        assert record.byte_size == len(payload)
        assert record.mime_type == "text/html"
        assert record.stored_at == "2024-01-01T00:00:00Z"


def test_locator_keys_are_distinct_and_sorted(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, b"a", key=OTHER_KEY)
        _put(store, b"b", key=KEY)
        _put(store, b"c", key=KEY)
        assert store.locator_keys() == tuple(sorted((KEY, OTHER_KEY)))


def test_binary_payloads_survive(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 4
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, payload)
        assert store.get(KEY) == payload


def test_empty_payload_round_trips(tmp_path: Path) -> None:
    with make_payload_store(tmp_path / "p.sqlite") as store:
        _put(store, b"")
        assert store.get(KEY) == b""


def test_compression_is_transparent() -> None:
    payload = b"repeat " * 500
    blob = compress_payload(payload)
    assert len(blob) < len(payload)
    assert decompress_payload(blob) == payload


def test_concurrent_writers_do_not_lose_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "p.sqlite"
    with make_payload_store(db_path) as store:
        errors: list[BaseException] = []

        def _writer(index: int) -> None:
            try:
                payload = f"payload-{index}".encode()
                store.put(
                    document_locator_key=f"{index:064d}",
                    blob_hash=sha256_bytes(payload),
                    accession="acc",
                    document_path=f"doc-{index}.htm",
                    raw_payload=payload,
                    stored_at="2024-01-01T00:00:00Z",
                )
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert store.count() == 16


def test_store_is_usable_after_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "p.sqlite"
    with make_payload_store(db_path) as store:
        _put(store, b"persisted")
    with make_payload_store(db_path) as store:
        assert store.get(KEY) == b"persisted"


def test_close_is_idempotent(tmp_path: Path) -> None:
    store = make_payload_store(tmp_path / "p.sqlite")
    store.close()
    store.close()


# --- reader ---------------------------------------------------------------


def test_reader_reads_existing_store(tmp_path: Path) -> None:
    db_path = tmp_path / "p.sqlite"
    with make_payload_store(db_path) as store:
        _put(store, b"readable")
    with make_payload_store_reader(db_path) as reader:
        assert reader.available is True
        assert reader.get(KEY) == b"readable"
        assert reader.has(KEY) is True
        assert reader.get_record(KEY) is not None


def test_reader_fails_open_on_absent_store(tmp_path: Path) -> None:
    reader = make_payload_store_reader(tmp_path / "missing.sqlite")
    assert reader.available is False
    assert reader.get(KEY) is None
    assert reader.has(KEY) is False
    assert reader.get_record(KEY) is None
    reader.close()


def test_reader_fails_open_on_corrupt_store(tmp_path: Path) -> None:
    db_path = tmp_path / "p.sqlite"
    db_path.write_bytes(b"this is not a sqlite database")
    reader = make_payload_store_reader(db_path)
    assert reader.available is False
    assert reader.get(KEY) is None
    reader.close()


def test_reader_close_is_idempotent(tmp_path: Path) -> None:
    reader = make_payload_store_reader(tmp_path / "missing.sqlite")
    reader.close()
    reader.close()


def test_error_type_is_exported() -> None:
    assert issubclass(PayloadStoreError, RuntimeError)


@pytest.mark.parametrize("payload", [b"", b"a", bytes(range(256))])
def test_round_trip_property(payload: bytes) -> None:
    assert decompress_payload(compress_payload(payload)) == payload


def test_unreadable_file_raises_sqlite_error(tmp_path: Path) -> None:
    db_path = tmp_path / "dir.sqlite"
    db_path.mkdir()
    with pytest.raises(sqlite3.Error):
        PayloadStore(db_path)
