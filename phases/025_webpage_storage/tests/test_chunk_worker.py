from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from defs.sql import Select, SqlDialect, Star, Table, make_sql_executor

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
worker_module = importlib.import_module("phases.025_webpage_storage.core.chunk_worker")


@dataclass
class FakeFetcher:
    payloads: dict[str, bytes | None]
    calls: list[str] = field(default_factory=list)

    def fetch(self, locator):
        self.calls.append(locator.locator_key)
        payload = self.payloads.get(locator.locator_key)
        if payload is None:
            return schemas.FetchResult(locator, None, "missing", "not archived")
        return schemas.FetchResult(locator, payload, "ok")


def _locator(key="a", path="index.htm"):
    return schemas.DocumentLocator(
        key, "0001-0001", path, f"https://example/{key}", "10-K"
    )


def _occurrence(cik="0000000001", path="index.htm"):
    return schemas.build_occurrence(
        cik, "0001-0001", path, "10-K", "2024-01-02", "2023-12-31"
    )


def _rows(path, table):
    executor = make_sql_executor(path, dialect=SqlDialect.SQLITE)
    try:
        query = Select(source=Table(table), projection=(Star(),))
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def test_chunks_are_isolated(tmp_path):
    fetcher = FakeFetcher({"a": b"one", "b": b"two"})
    first = worker_module.process_chunk(
        "chunk-1",
        "worker-1",
        [_locator("a")],
        [_occurrence()],
        fetcher,
        tmp_path / "one.db",
    )
    second_locator = _locator("b", "other.htm")
    second_occurrence = _occurrence(path="other.htm")
    worker_module.process_chunk(
        "chunk-2",
        "worker-2",
        [second_locator],
        [second_occurrence],
        fetcher,
        tmp_path / "two.db",
    )

    assert first.path != tmp_path / "two.db"
    assert (
        _rows(first.path, schemas.DOCUMENT_BLOBS_TABLE)[0]["accession"] == "0001-0001"
    )
    assert (
        _rows(first.path, schemas.FILING_OCCURRENCES_TABLE)[0]["document_path"]
        == "index.htm"
    )
    assert (
        _rows(tmp_path / "two.db", schemas.FILING_OCCURRENCES_TABLE)[0]["document_path"]
        == "other.htm"
    )


def test_payload_is_zstd_compressed_and_roundtrips(tmp_path):
    raw = b"<html>deterministic payload</html>"
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator()],
        [_occurrence()],
        FakeFetcher({"a": raw}),
        tmp_path / "chunk.db",
    )
    stored = _rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)[0]
    assert stored["raw_payload"] != raw
    assert schemas.decompress_payload(stored["raw_payload"]) == raw
    assert stored["byte_size"] == len(raw)


def test_duplicate_locators_are_fetched_once_and_stored_once(tmp_path):
    fetcher = FakeFetcher({"a": b"same"})
    occurrence = _occurrence()
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator(), _locator()],
        [occurrence, occurrence],
        fetcher,
        tmp_path / "chunk.db",
    )
    assert fetcher.calls == ["a"]
    assert result.locator_count == result.blob_count == result.fetched_count == 1
    assert result.occurrence_count == 1
    assert len(_rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    assert len(_rows(result.path, schemas.FILING_OCCURRENCES_TABLE)) == 1


def test_fetch_failures_are_reported_and_successes_commit(tmp_path):
    fetcher = FakeFetcher({"a": b"available", "missing": None})
    missing = _locator("missing", "missing.htm")
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator(), missing],
        [_occurrence(), _occurrence(path="missing.htm")],
        fetcher,
        tmp_path / "chunk.db",
    )
    assert len(result.failures) == 1
    assert result.failures[0].locator.locator_key == "missing"
    assert result.failures[0].status == "missing"
    assert result.occurrence_count == result.blob_count == 1
    assert _rows(result.path, schemas.COMMITTED_CHUNKS_TABLE)[0]["record_count"] == 1
