from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from defs.sql import Select, SqlDialect, Star, Table, make_sql_executor

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
worker_module = importlib.import_module("phases.025_webpage_storage.core.chunk_worker")
persistence_module = importlib.import_module(
    "phases.025_webpage_storage.core.chunk_persistence"
)
processor_module = importlib.import_module("phases.025_webpage_storage.processors")
NoOpDocumentProcessor = processor_module.NoOpDocumentProcessor


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


def _canonical_locator(key="a", path="index.htm"):
    return schemas.DocumentLocator(
        key, "0000000123-24-000001", path, f"https://example/{key}", "10-K"
    )


def _canonical_occurrence(cik="0000000001", path="index.htm"):
    return schemas.build_occurrence(
        cik, "0000000123-24-000001", path, "10-K", "2024-01-02", "2023-12-31"
    )


def _rows(path, table):
    executor = make_sql_executor(path, dialect=SqlDialect.SQLITE)
    try:
        query = Select(source=Table(table), projection=(Star(),))
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def test_prefetch_byte_budget_tracks_payload_sizes():
    budget = persistence_module._ByteBudget(10)
    budget.acquire(7)
    assert budget.used == 7
    budget.release(7)
    assert budget.used == 0


def test_prefetch_byte_budget_allows_one_oversized_payload():
    budget = persistence_module._ByteBudget(10)
    budget.acquire(11)
    assert budget.used == 11
    budget.release(11)
    assert budget.used == 0


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


def test_blob_metadata_is_stored(tmp_path):
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
    assert "raw_payload" not in stored
    assert stored["raw_payload_sha256"] == __import__("hashlib").sha256(raw).hexdigest()
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
    failures_in_db = _rows(result.path, schemas.ACQUISITION_FAILURES_TABLE)
    assert len(failures_in_db) == 1
    assert failures_in_db[0]["document_path"] == "missing.htm"
    assert failures_in_db[0]["status"] == "missing"


def test_processor_failure_keeps_raw_and_records_normalization_failure(tmp_path):
    class FailingProcessor:
        processor_fingerprint = "failing:v1"

        async def process(self, raw_bytes, locator):
            raise ValueError("cannot normalize")

    result = worker_module.process_chunk(
        "failed-normalization",
        "worker",
        [_locator()],
        [_occurrence()],
        FakeFetcher({"a": b"raw"}),
        tmp_path / "failed.db",
        processor=FailingProcessor(),
    )
    stored = _rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)[0]
    assert (
        stored["raw_payload_sha256"] == __import__("hashlib").sha256(b"raw").hexdigest()
    )
    assert len(_rows(result.path, schemas.FILING_OCCURRENCES_TABLE)) == 1
    failures = _rows(result.path, schemas.NORMALIZATION_FAILURES_TABLE)
    assert failures[0]["error_message"] == "cannot normalize"


def test_multi_registrant_locators_deduplicate_before_fetch(tmp_path):
    fetcher = FakeFetcher({"loc-reg1": b"shared", "loc-reg2": b"shared"})
    # Two different locator keys sharing same accession + document_path
    loc1 = schemas.DocumentLocator(
        "loc-reg1", "0001-0001", "shared.htm", "https://example/loc1", "10-K"
    )
    loc2 = schemas.DocumentLocator(
        "loc-reg2", "0001-0001", "shared.htm", "https://example/loc2", "10-K"
    )
    occ1 = schemas.build_occurrence(
        "0000000001", "0001-0001", "shared.htm", "10-K", "2024-01-02", "2023-12-31"
    )
    occ2 = schemas.build_occurrence(
        "0000000002", "0001-0001", "shared.htm", "10-K", "2024-01-02", "2023-12-31"
    )
    result = worker_module.process_chunk(
        "chunk-dedup",
        "worker",
        [loc1, loc2],
        [occ1, occ2],
        fetcher,
        tmp_path / "dedup.db",
    )
    # Only fetched once because they identify the same document
    assert len(_rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    assert len(_rows(result.path, schemas.FILING_OCCURRENCES_TABLE)) == 2


def test_sub_chunk_resumption(tmp_path):
    db_path = tmp_path / "sub_chunk.db"
    loc_a = _locator("a", "a.htm")
    loc_b = _locator("b", "b.htm")
    occ_a = _occurrence("0000000001", "a.htm")
    occ_b = _occurrence("0000000001", "b.htm")

    # Step 1: Initial run with only locator 'a' stored (simulating interruption before 'b')
    fetcher1 = FakeFetcher({"a": b"payload-a"})
    worker_module.process_chunk(
        "chunk-resume",
        "worker-1",
        [loc_a],
        [occ_a],
        fetcher1,
        db_path,
    )
    assert fetcher1.calls == ["a"]
    assert len(_rows(db_path, schemas.DOCUMENT_BLOBS_TABLE)) == 1

    # Remove the _committed_chunks record so it acts like an interrupted chunk
    executor = make_sql_executor(db_path, dialect="sqlite")
    from defs.sql import Commit, Delete

    executor.exec(
        executor.compiler.compile(Delete(table=schemas.COMMITTED_CHUNKS_TABLE))
    )
    executor.exec(executor.compiler.compile(Commit()))
    executor.close()

    # Step 2: Resume with both 'a' and 'b'
    fetcher2 = FakeFetcher({"a": b"payload-a", "b": b"payload-b"})
    resumed = worker_module.process_chunk(
        "chunk-resume",
        "worker-1",
        [loc_a, loc_b],
        [occ_a, occ_b],
        fetcher2,
        db_path,
    )

    # 'a' was skipped because it was already stored; only 'b' was fetched
    assert fetcher2.calls == ["b"]
    assert resumed.blob_count == 2
    assert resumed.occurrence_count == 2
    assert len(_rows(db_path, schemas.DOCUMENT_BLOBS_TABLE)) == 2
    assert len(_rows(db_path, schemas.COMMITTED_CHUNKS_TABLE)) == 1


def test_process_chunk_progress_events(tmp_path):
    events: list[dict] = []
    fetcher = FakeFetcher({"a": b"payload-a"})
    worker_module.process_chunk(
        "chunk-p",
        "worker-1",
        [_locator("a")],
        [_occurrence()],
        fetcher,
        tmp_path / "p.db",
        progress=events.append,
    )
    assert len(events) == 1
    assert events[0]["type"] == "document_done"
    assert events[0]["status"] == "ok"


def test_process_chunk_with_async_processor(tmp_path):
    proc_module = importlib.import_module("phases.025_webpage_storage.processors")
    ProcessedDocument = proc_module.ProcessedDocument

    class AsyncPipelineProcessor:
        async def process(self, raw_bytes, locator):
            import asyncio

            await asyncio.sleep(0.001)
            # Example: clean HTML scripts & transform text
            cleaned = raw_bytes.replace(b"<script>ad()</script>", b"").upper()
            return ProcessedDocument(
                doc_id=schemas.doc_id(locator.accession, locator.document_path),
                payload=cleaned,
                byte_size=len(cleaned),
                mime_type="text/html",
                metadata={"cleaned": True},
            )

    fetcher = FakeFetcher({"a": b"<html><body><script>ad()</script>text</body></html>"})
    result = worker_module.process_chunk(
        "chunk-async-proc",
        "worker-1",
        [_locator("a")],
        [_occurrence()],
        fetcher,
        tmp_path / "async_proc.db",
        processor=AsyncPipelineProcessor(),
    )
    stored = _rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)[0]
    assert stored["raw_payload_sha256"] == (
        __import__("hashlib")
        .sha256(b"<html><body><script>ad()</script>text</body></html>")
        .hexdigest()
    )
    normalized = _rows(result.path, schemas.NORMALIZED_DOCUMENTS_TABLE)
    assert (
        normalized[0]["payload_sha256"]
        == __import__("hashlib").sha256(b"<HTML><BODY>TEXT</BODY></HTML>").hexdigest()
    )
    assert normalized[0]["representation"] == "application/octet-stream"


def _upper_processor_class(fingerprint: str):
    proc_module = importlib.import_module("phases.025_webpage_storage.processors")
    ProcessedDocument = proc_module.ProcessedDocument

    class UpperProcessor:
        processor_fingerprint = fingerprint

        async def process(self, raw_bytes, locator):
            return ProcessedDocument(
                doc_id=schemas.doc_id(locator.accession, locator.document_path),
                payload=raw_bytes.upper(),
                byte_size=len(raw_bytes),
                mime_type="text/plain",
                metadata={},
                processor_fingerprint=self.processor_fingerprint,
                representation="text",
            )

    return UpperProcessor


def _clear_committed_audit(db_path):
    from defs.sql import Commit, Delete

    executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
    try:
        executor.exec(
            executor.compiler.compile(Delete(table=schemas.COMMITTED_CHUNKS_TABLE))
        )
        executor.exec(executor.compiler.compile(Commit()))
    finally:
        executor.close()


def test_resume_with_changed_processor_reprocesses_normalized_blobs(tmp_path):
    db_path = tmp_path / "resume-normalize.db"
    loc = _locator("a", "a.htm")
    occ = _occurrence("0000000001", "a.htm")

    worker_module.process_chunk(
        "chunk-norm",
        "worker-1",
        [loc],
        [occ],
        FakeFetcher({"a": b"payload-a"}),
        db_path,
        processor=NoOpDocumentProcessor(),
    )
    assert len(_rows(db_path, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    initial_normalized = _rows(db_path, schemas.NORMALIZED_DOCUMENTS_TABLE)
    assert len(initial_normalized) == 1
    assert (
        _rows(db_path, schemas.COMMITTED_CHUNKS_TABLE)[0]["processor_fingerprint"]
        != "raw-only"
    )

    _clear_committed_audit(db_path)

    UpperProcessor = _upper_processor_class("upper:v1")
    resumed_fetcher = FakeFetcher({"a": b"payload-a"})
    worker_module.process_chunk(
        "chunk-norm",
        "worker-1",
        [loc],
        [occ],
        resumed_fetcher,
        db_path,
        processor=UpperProcessor(),
    )

    assert resumed_fetcher.calls == ["a"]
    normalized = _rows(db_path, schemas.NORMALIZED_DOCUMENTS_TABLE)
    assert len(normalized) == 2
    selected = [row for row in normalized if row["processor_fingerprint"] == "upper:v1"]
    assert len(selected) == 1
    assert selected[0]["processor_fingerprint"] == "upper:v1"
    assert schemas.decompress_payload(selected[0]["normalized_payload"]) == b"PAYLOAD-A"
    assert selected[0]["source_doc_id"] == schemas.doc_id("0001-0001", "a.htm")
    audit = _rows(db_path, schemas.COMMITTED_CHUNKS_TABLE)[0]
    assert audit["processor_fingerprint"] == "upper:v1"


def test_committed_chunk_with_different_processor_is_reprocessed(tmp_path):
    db_path = tmp_path / "stale-fingerprint.db"
    loc = _locator("a", "a.htm")
    occ = _occurrence()

    UpperProcessor = _upper_processor_class("upper:v1")
    first = worker_module.process_chunk(
        "chunk-stale",
        "worker-1",
        [loc],
        [occ],
        FakeFetcher({"a": b"payload-a"}),
        db_path,
        processor=UpperProcessor(),
    )
    assert first.audit is not None
    assert first.audit.processor_fingerprint == "upper:v1"

    class ReversingProcessor:
        processor_fingerprint = "reverse:v1"

        async def process(self, raw_bytes, locator):
            proc_module = importlib.import_module(
                "phases.025_webpage_storage.processors"
            )
            payload = raw_bytes[::-1]
            return proc_module.ProcessedDocument(
                doc_id=schemas.doc_id(locator.accession, locator.document_path),
                payload=payload,
                byte_size=len(payload),
                mime_type="text/plain",
                metadata={},
                processor_fingerprint=self.processor_fingerprint,
                representation="text",
            )

    second = worker_module.process_chunk(
        "chunk-stale",
        "worker-1",
        [loc],
        [occ],
        FakeFetcher({"a": b"payload-a"}),
        db_path,
        processor=ReversingProcessor(),
    )

    assert second.audit is not None
    assert second.audit.processor_fingerprint == "reverse:v1"
    assert len(_rows(db_path, schemas.COMMITTED_CHUNKS_TABLE)) == 1
    normalized = _rows(db_path, schemas.NORMALIZED_DOCUMENTS_TABLE)
    assert {row["processor_fingerprint"] for row in normalized} == {
        "upper:v1",
        "reverse:v1",
    }
    reversed_row = next(
        row for row in normalized if row["processor_fingerprint"] == "reverse:v1"
    )
    assert (
        schemas.decompress_payload(reversed_row["normalized_payload"]) == b"a-daolyap"
    )


def test_processor_failure_keeps_raw_blob_and_records_normalization_failure(tmp_path):
    db_path = tmp_path / "norm-failure.db"
    loc = _locator("a")
    occ = _occurrence()

    class FailingProcessor:
        processor_fingerprint = "failing:v1"

        async def process(self, raw_bytes, locator):
            raise RuntimeError("normalization exploded")

    result = worker_module.process_chunk(
        "chunk-norm-fail",
        "worker-1",
        [loc],
        [occ],
        FakeFetcher({"a": b"payload-a"}),
        db_path,
        processor=FailingProcessor(),
    )

    assert result.succeeded
    assert len(_rows(db_path, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    assert _rows(db_path, schemas.NORMALIZED_DOCUMENTS_TABLE) == []
    failures = _rows(db_path, schemas.NORMALIZATION_FAILURES_TABLE)
    assert len(failures) == 1
    assert failures[0]["processor_fingerprint"] == "failing:v1"
    assert "normalization exploded" in failures[0]["error_message"]
    assert len(_rows(db_path, schemas.FILING_OCCURRENCES_TABLE)) == 1


def _stub_bundle_10k() -> bytes:
    return (
        b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>10k.htm\n<TEXT>\n"
        b"ITEM 15. Exhibits.\n"
        b"The financial statements are incorporated herein by reference to "
        b"Exhibit 13.\n"
        b"</TEXT>\n</DOCUMENT>\n"
        b"<DOCUMENT>\n<TYPE>EX-13\n<SEQUENCE>2\n<FILENAME>ex13.htm\n<TEXT>\n"
        b"ANNUAL REPORT BODY with Item 1 Business content\n"
        b"</TEXT>\n</DOCUMENT>\n"
    )


class _StubRefetchProcessor:
    """Processor mimicking a 10-K evaluator stub decision for EX-13."""

    processor_fingerprint = "stub-refetch:v1"
    representation = "normalized-text"

    async def process(self, raw_bytes, locator):
        return processor_module.ProcessedDocument(
            doc_id=schemas.doc_id(locator.accession, locator.document_path),
            payload=raw_bytes,
            byte_size=len(raw_bytes),
            mime_type="text/plain",
            metadata={
                "decision_action": "refetch_sub_doc",
                "target_exhibit": "EX-13",
                "is_stub": True,
            },
            processor_fingerprint=self.processor_fingerprint,
            representation=self.representation,
        )


class _BundleFetcher(FakeFetcher):
    """Fetcher returning PEM-stripped bundle context like the real fetcher."""

    def __init__(self, bundles, **kw):
        super().__init__(bundles, **kw)

    def fetch(self, locator):
        result = super().fetch(locator)
        if result.status == "ok":
            return schemas.FetchResult(
                result.locator,
                result.payload,
                "ok",
                source_payload=result.payload,
            )
        return result


def test_stub_second_pass_persists_exhibit_from_bundle(tmp_path):
    bundle = _stub_bundle_10k()
    fetcher = _BundleFetcher({"a": bundle})
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator()],
        [_occurrence()],
        fetcher,
        tmp_path / "chunk.db",
        processor=_StubRefetchProcessor(),
    )
    blobs = _rows(result.path, schemas.DOCUMENT_BLOBS_TABLE)
    normalized = _rows(result.path, schemas.NORMALIZED_DOCUMENTS_TABLE)
    assert len(blobs) == 2
    assert len(normalized) == 2
    exhibit_blob = [row for row in blobs if row["document_path"] == "ex13.htm"]
    assert len(exhibit_blob) == 1
    # No extra fetch calls: exhibit came from the retained bundle.
    assert fetcher.calls == ["a"]


def test_stub_without_exhibit_in_bundle_fetches_bundle(tmp_path):
    # Primary payload has no bundle context; the worker fetches the bundle.
    class SingleDocFetcher(FakeFetcher):
        def fetch(self, locator):
            if (
                locator.document_path.endswith(".txt")
                and locator.document_path[:10].isdigit()
            ):
                self.calls.append(locator.locator_key)
                return schemas.FetchResult(
                    locator,
                    _stub_bundle_10k(),
                    "ok",
                    source_payload=_stub_bundle_10k(),
                )
            return super().fetch(locator)

    fetcher = SingleDocFetcher({"a": b"stub text", "bundle": _stub_bundle_10k()})
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_canonical_locator()],
        [_canonical_occurrence()],
        fetcher,
        tmp_path / "chunk.db",
        processor=_StubRefetchProcessor(),
    )
    assert len(_rows(result.path, schemas.NORMALIZED_DOCUMENTS_TABLE)) == 2
    assert sum(1 for call in fetcher.calls if call.endswith(":full-submission")) == 1


def test_proceed_decision_persists_single_row(tmp_path):
    class ProceedProcessor(_StubRefetchProcessor):
        async def process(self, raw_bytes, locator):
            doc = await super().process(raw_bytes, locator)
            return processor_module.ProcessedDocument(
                doc_id=doc.doc_id,
                payload=doc.payload,
                byte_size=doc.byte_size,
                mime_type=doc.mime_type,
                metadata={"decision_action": "proceed", "is_stub": False},
                processor_fingerprint=self.processor_fingerprint,
                representation=self.representation,
            )

    fetcher = _BundleFetcher({"a": _stub_bundle_10k()})
    result = worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator()],
        [_occurrence()],
        fetcher,
        tmp_path / "chunk.db",
        processor=ProceedProcessor(),
    )
    assert len(_rows(result.path, schemas.NORMALIZED_DOCUMENTS_TABLE)) == 1


def test_filing_year_injected_from_occurrence(tmp_path):
    captured = {}

    class CaptureProcessor:
        processor_fingerprint = "capture:v1"
        representation = "normalized-text"

        async def process(self, raw_bytes, locator):
            captured["filing_year"] = getattr(locator, "filing_year", None)
            return processor_module.ProcessedDocument(
                doc_id=schemas.doc_id(locator.accession, locator.document_path),
                payload=raw_bytes,
                byte_size=len(raw_bytes),
                mime_type="text/plain",
                metadata={"decision_action": "proceed"},
                processor_fingerprint=self.processor_fingerprint,
                representation=self.representation,
            )

    occurrence = schemas.build_occurrence(
        "0000000001", "0001-0001", "index.htm", "10-K", "2004-06-15", "2003-12-31"
    )
    fetcher = FakeFetcher({"a": b"payload"})
    worker_module.process_chunk(
        "chunk",
        "worker",
        [_locator()],
        [occurrence],
        fetcher,
        tmp_path / "chunk.db",
        processor=CaptureProcessor(),
    )
    assert captured["filing_year"] == 2004
