"""Tests for the canonical raw fixture SQLite store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import derive_document_locator_key
from edgar_sec.infra.storage.fixture_store import FixtureStore, FixtureStoreError


def test_fixture_store_round_trips_and_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "fixture.sqlite"
    with FixtureStore(path) as store:
        assert store.put_many([("doc-1", b"original")]) == 1
        assert store.put_many([("doc-1", b"replacement")]) == 0
        assert store.get("doc-1") == b"original"
        assert store.count() == 1
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables == {
        "fixture_payloads",
        # v1-compatible identity rows, and the v2 per-document form table.
        "document_blobs",
        "fixture_document_forms",
    }


def test_read_only_store_does_not_create_or_modify_database(tmp_path: Path) -> None:
    path = tmp_path / "fixture.sqlite"
    with FixtureStore(path) as store:
        store.put_many([("doc-1", b"payload")])
    before = path.read_bytes()
    with FixtureStore(path, read_only=True) as store:
        assert store.get("doc-1") == b"payload"
        with pytest.raises(FixtureStoreError, match="read-only"):
            store.put_many([("doc-2", b"payload")])
    assert path.read_bytes() == before


def test_existing_phase_2_5_fixture_is_read_without_migration() -> None:
    path = Path(".artifacts/fixtures/fix-99fdcf53/fixture.sqlite")
    if not path.is_file():
        pytest.skip("local Phase 2.5 fixture artifact is not present")

    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        tables_before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        accession, document_path, doc_id = connection.execute(
            "SELECT accession, document_path, doc_id FROM document_blobs ORDER BY doc_id LIMIT 1"
        ).fetchone()
    assert doc_id == derive_document_locator_key(accession, document_path)

    with FixtureStore(path, read_only=True) as store:
        payload = store.get(doc_id)
        assert payload
        assert store.count() == 10_000

    with sqlite3.connect(uri, uri=True) as connection:
        tables_after = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables_after == tables_before
    assert "document_payloads" not in tables_after


def test_document_metadata_round_trips_and_never_overwrites(tmp_path: Path) -> None:
    from edgar_sec.domain.document.models import RawDocumentBlob

    first = RawDocumentBlob(
        doc_id="doc-1",
        accession="0001234567-11-000001",
        document_path="alpha.htm",
        byte_size=11,
        mime_type="text/html",
        raw_payload_sha256="a" * 64,
    )
    replacement = RawDocumentBlob(
        doc_id="doc-1",
        accession="changed",
        document_path="changed.htm",
        byte_size=99,
        mime_type="text/plain",
        raw_payload_sha256="b" * 64,
    )
    with FixtureStore(tmp_path / "fixture.sqlite") as store:
        assert store.put_documents([first], {"doc-1": "10-K"}) == 1
        assert store.put_documents([replacement], {"doc-1": "10-Q"}) == 1
        assert store.has_document("doc-1")
        assert not store.has_document("doc-2")
        # Insert-ignore, like payloads: a recorded document is evidence.
        assert store.documents() == (first,)
        assert store.document_forms() == {"doc-1": "10-K"}


def test_documents_selection_is_ordered_and_filtered(tmp_path: Path) -> None:
    from edgar_sec.domain.document.models import RawDocumentBlob

    def blob(doc_id: str, document_path: str) -> RawDocumentBlob:
        return RawDocumentBlob(
            doc_id=doc_id,
            accession="0001234567-11-000001",
            document_path=document_path,
            byte_size=1,
            mime_type="text/html",
            raw_payload_sha256="c" * 64,
        )

    documents = [
        blob("doc-c", "c.htm"),
        blob("doc-a", "a.htm"),
        blob("doc-b", "b.txt"),
    ]
    with FixtureStore(tmp_path / "fixture.sqlite") as store:
        store.put_documents(documents)
        # A limit must take the first N of a stable order, or two runs with the
        # same limit could review different documents and diff against each other.
        assert [item.doc_id for item in store.documents(limit=2)] == ["doc-a", "doc-b"]
        assert [item.doc_id for item in store.documents(ids=["doc-c"])] == ["doc-c"]
        assert [item.doc_id for item in store.documents(extensions=["txt"])] == [
            "doc-b"
        ]


def test_store_without_document_metadata_reads_as_empty_not_corrupt(
    tmp_path: Path,
) -> None:
    """A payload-only fixture is incomplete, not unusable.

    A store written before document metadata existed must still open and still
    serve payloads; refusing to open would turn a repairable gap into a dead
    fixture.
    """
    path = tmp_path / "fixture.sqlite"
    with FixtureStore(path) as store:
        store.put_many([("doc-1", b"payload")])
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE document_blobs")
        connection.commit()
    with FixtureStore(path, read_only=True) as store:
        assert store.has_document_metadata is False
        assert store.get("doc-1") == b"payload"
        assert store.documents() == ()
        assert store.has_document("doc-1") is False


def test_committed_fixture_replays_through_the_offline_fetcher() -> None:
    """The recorded artifact is readable by the v2 fetch path, not just the store.

    The locator key is derived from the catalog's *unhyphenated* accession while
    a caller naturally holds the hyphenated EDGAR spelling. Replay matching zero
    rows against a valid fixture is silent, so this asserts actual payload bytes
    for both spellings of the same document.
    """
    from edgar_sec.domain.document.models import DocumentLocator
    from edgar_sec.domain.sec_urls import accession_hyphenated
    from edgar_sec.pipelines.document_storage.fetching import FixtureArchiveFetcher

    path = Path(".artifacts/fixtures/fix-99fdcf53/fixture.sqlite")
    if not path.is_file():
        pytest.skip("local Phase 2.5 fixture artifact is not present")

    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT accession, document_path FROM document_blobs ORDER BY doc_id LIMIT 3"
        ).fetchall()

    fetcher = FixtureArchiveFetcher([path])
    try:
        for accession, document_path in rows:
            unhyphenated = DocumentLocator.from_parts(accession, document_path)
            hyphenated = DocumentLocator.from_parts(
                accession_hyphenated(accession), document_path
            )
            for locator in (unhyphenated, hyphenated):
                result = fetcher.fetch(locator)
                assert result.ok is True, f"{document_path} was not replayed"
                assert result.payload
    finally:
        fetcher.close()


def test_writable_store_refuses_to_claim_an_unrelated_database(tmp_path: Path) -> None:
    path = tmp_path / "other.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    with pytest.raises(FixtureStoreError, match="not a fixture store"):
        FixtureStore(path)
