"""Tests for chunk acquisition, publication, and the process pool."""

from __future__ import annotations

import pickle
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document.acquisition import FetchResult
from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.pipelines.document_storage.checkpoint import validate_chunk_snapshot
from edgar_sec.pipelines.document_storage.fetching import FixtureArchiveFetcher
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
from edgar_sec.pipelines.document_storage.processor import (
    FilingProcessor,
    PassThroughProcessor,
    ProcessedDocument,
)
from edgar_sec.pipelines.document_storage.worker import (
    ChunkError,
    chunk_fingerprint,
    is_chunk_complete,
    process_chunk,
    process_chunks,
    resolved_worker_count,
)

ACCESSION = "0001234567-11-000001"
BODY = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION

FORM 10-K

ACME INDUSTRIAL WIDGETS, INC.
(Exact name of registrant as specified in its charter)

Delaware
(State or other jurisdiction of incorporation)

Commission File Number: 001-14103
(Exact name of registrant as specified in its charter)

Trading Symbol(s)
ACMX

PART I

ITEM 1. Business

The Company was founded in 1994 and is a leading provider of industrial \
widgets. It operates three manufacturing facilities and employs \
approximately 4,200 people worldwide.

SIGNATURES

/s/ Jane Q. Registrant
"""


def _locator(
    document_path: str = "acme-10k.htm", form: str = "10-K"
) -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        document_path,
        archive_url=f"https://www.sec.gov/x/{document_path}",
        form=form,
        source_cik="1234567",
    )


def _occurrence(locator: DocumentLocator) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id="occ-1",
        source_cik=Cik.from_raw("1234567"),
        accession=locator.accession,
        document_path=locator.document_path,
        form="10-K",
        filing_date="2012-02-15",
        report_date="2011-12-31",
        doc_id=locator.document_locator_key,
    )


class DictFetcher:
    """In-memory fetcher: maps document path to bytes or to a failure."""

    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        self.calls.append(locator.document_path)
        response = self.responses.get(locator.document_path, KeyError("absent"))
        if isinstance(response, Exception):
            return FetchResult(locator, None, "failed", error=str(response))
        return FetchResult(locator, response, "ok")


def _seed_fixture(db_path: Path, locator: DocumentLocator, payload: bytes) -> None:
    with FixtureStore(db_path) as store:
        store.put_many([(locator.document_locator_key, payload)])


# --- single chunk ---------------------------------------------------------


def test_chunk_writes_a_valid_parquet_checkpoint(tmp_path: Path) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.chunk_id == "c1"
    assert result.worker_id == "w1"
    assert result.document_count == 1
    assert result.normalized_count == 1
    assert result.failed_count == 0
    assert result.missing_count == 0
    assert result.ok is True
    meta = validate_chunk_snapshot(result.output_path)
    assert meta["num_rows"] == 1


def test_checkpoint_lands_at_the_named_path(tmp_path: Path) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.output_path == chunk_checkpoint_path(tmp_path, "c1")
    assert result.output_path.is_file()


def test_normalized_text_is_stored(tmp_path: Path) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    table = pq.read_table(result.output_path)
    text = table.column("normalized_text").to_pylist()[0]
    assert "ACME INDUSTRIAL WIDGETS" in text
    assert "founded in 1994" in text


def test_missing_documents_are_recorded_not_dropped(tmp_path: Path) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({}),
        chunks_dir=tmp_path,
    )
    assert result.missing_count == 1
    assert result.normalized_count == 0
    assert result.ok is False
    table = pq.read_table(result.output_path)
    assert table.column("status").to_pylist() == ["missing"]
    assert table.column("error_message").to_pylist()[0]


def test_one_failing_document_does_not_fail_the_chunk(tmp_path: Path) -> None:
    good = _locator("good.htm")
    bad = _locator("bad.htm")
    result = process_chunk(
        "c1",
        "w1",
        [good, bad],
        [_occurrence(good), _occurrence(bad)],
        fetcher=DictFetcher({"good.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.normalized_count == 1
    assert result.missing_count == 1
    assert result.failed_count == 0
    assert result.ok is False
    assert pq.read_table(result.output_path).num_rows == 2


def test_duplicate_locators_are_fetched_once(tmp_path: Path) -> None:
    locator = _locator()
    fetcher = DictFetcher({"acme-10k.htm": BODY.encode()})
    result = process_chunk(
        "c1",
        "w1",
        [locator, locator, locator],
        [_occurrence(locator)],
        fetcher=fetcher,
        chunks_dir=tmp_path,
    )
    assert fetcher.calls == ["acme-10k.htm"]
    assert result.document_count == 1


def test_locator_without_a_recorded_occurrence_is_still_emitted(
    tmp_path: Path,
) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.occurrences == 1
    table = pq.read_table(result.output_path)
    assert table.num_rows == 1
    assert table.column("source_cik").to_pylist() == ["0001234567"]


def test_one_occurrence_under_several_locators(tmp_path: Path) -> None:
    a = _locator("a.htm")
    b = _locator("b.htm")
    result = process_chunk(
        "c1",
        "w1",
        [a, b],
        [_occurrence(a), _occurrence(b)],
        fetcher=DictFetcher({"a.htm": BODY.encode(), "b.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.occurrences == 2
    assert pq.read_table(result.output_path).num_rows == 2


def test_pass_through_processor_stores_raw_bytes(tmp_path: Path) -> None:
    raw = b"<html>raw</html>"
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": raw}),
        processor=PassThroughProcessor(),
        chunks_dir=tmp_path,
    )
    assert result.processor_fingerprint == "raw-pass-through"
    table = pq.read_table(result.output_path)
    assert table.column("raw_payload").to_pylist()[0] == raw


def test_empty_chunk_is_valid(tmp_path: Path) -> None:
    result = process_chunk(
        "c1", "w1", [], [], fetcher=DictFetcher({}), chunks_dir=tmp_path
    )
    assert result.document_count == 0
    assert result.ok is True
    assert validate_chunk_snapshot(result.output_path)["num_rows"] == 0


def test_chunk_and_worker_ids_are_required(tmp_path: Path) -> None:
    with pytest.raises(ChunkError):
        process_chunk("", "w1", [], [], fetcher=DictFetcher({}), chunks_dir=tmp_path)
    with pytest.raises(ChunkError):
        process_chunk("c1", "", [], [], fetcher=DictFetcher({}), chunks_dir=tmp_path)


def test_result_is_reproducible_for_the_same_input(tmp_path: Path) -> None:
    locator = _locator()
    kwargs = {
        "fetcher": DictFetcher({"acme-10k.htm": BODY.encode()}),
        "chunks_dir": tmp_path,
    }
    first = process_chunk("c1", "w1", [locator], [_occurrence(locator)], **kwargs)
    second = process_chunk("c1", "w2", [locator], [_occurrence(locator)], **kwargs)
    assert first.payload_sha256 == second.payload_sha256


def test_payload_sink_receives_every_acquired_payload(tmp_path: Path) -> None:
    locator = _locator()
    seen: list[tuple[str, bytes]] = []
    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
        payload_sink=lambda loc, payload: seen.append((loc.document_path, payload)),
    )
    assert seen == [("acme-10k.htm", BODY.encode())]


def test_payload_sink_is_not_called_for_missing_documents(tmp_path: Path) -> None:
    locator = _locator()
    seen: list[str] = []
    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({}),
        chunks_dir=tmp_path,
        payload_sink=lambda loc, payload: seen.append(loc.document_path),
    )
    assert seen == []


# --- fingerprinting and reuse --------------------------------------------


def test_fingerprint_is_stamped_on_the_checkpoint(tmp_path: Path) -> None:
    locator = _locator()
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert (
        chunk_fingerprint(result.output_path) == FilingProcessor().processor_fingerprint
    )


def test_absent_checkpoint_is_not_complete(tmp_path: Path) -> None:
    assert is_chunk_complete(tmp_path, "missing", processor_fingerprint="any") is False


def test_completed_checkpoint_is_reusable(tmp_path: Path) -> None:
    locator = _locator()
    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    fingerprint = FilingProcessor().processor_fingerprint
    assert is_chunk_complete(tmp_path, "c1", processor_fingerprint=fingerprint) is True


def test_checkpoint_from_another_processor_is_not_reusable(tmp_path: Path) -> None:
    """Reusing another processor's chunk would mix two text conventions."""
    locator = _locator()
    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({"acme-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert is_chunk_complete(tmp_path, "c1", processor_fingerprint="other:v9") is False


def test_corrupt_checkpoint_is_not_complete(tmp_path: Path) -> None:
    path = chunk_checkpoint_path(tmp_path, "c1")
    path.write_bytes(b"not parquet")
    assert is_chunk_complete(tmp_path, "c1", processor_fingerprint="x") is False


# --- pool orchestration ---------------------------------------------------


def test_process_chunks_runs_every_chunk(tmp_path: Path) -> None:
    locators = {"c1": [_locator("a.htm")], "c2": [_locator("b.htm")]}
    occurrences = {"c1": [_occurrence(locators["c1"][0])], "c2": []}
    results = process_chunks(
        ["c1", "c2"],
        locators,
        occurrences,
        fetcher=DictFetcher({"a.htm": BODY.encode(), "b.htm": BODY.encode()}),
        chunks_dir=tmp_path,
        workers=1,
    )
    assert [result.chunk_id for result in results] == ["c1", "c2"]
    assert all(result.ok for result in results)


def test_process_chunks_skips_completed_chunks(tmp_path: Path) -> None:
    locator = _locator("a.htm")
    locators = {"c1": [locator]}
    occurrences = {"c1": [_occurrence(locator)]}
    first = process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=DictFetcher({"a.htm": BODY.encode()}),
        chunks_dir=tmp_path,
        workers=1,
    )
    fetcher = DictFetcher({"a.htm": BODY.encode()})
    second = process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=fetcher,
        chunks_dir=tmp_path,
        workers=1,
    )
    assert first[0].worker_id != "skipped"
    assert second[0].worker_id == "skipped"
    assert fetcher.calls == []


def test_process_chunks_recomputes_a_stale_fingerprint(tmp_path: Path) -> None:
    locator = _locator("a.htm")
    locators = {"c1": [locator]}
    occurrences = {"c1": [_occurrence(locator)]}
    process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=DictFetcher({"a.htm": BODY.encode()}),
        chunks_dir=tmp_path,
        workers=1,
    )
    fetcher = DictFetcher({"a.htm": BODY.encode()})
    results = process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=fetcher,
        processor=PassThroughProcessor(),
        chunks_dir=tmp_path,
        workers=1,
    )
    assert results[0].processor_fingerprint == "raw-pass-through"
    assert fetcher.calls == ["a.htm"]


def test_process_chunks_returns_one_result_per_chunk_in_order(tmp_path: Path) -> None:
    locators = {f"c{i}": [_locator(f"d{i}.htm")] for i in range(4)}
    occurrences: dict[str, list] = {}
    results = process_chunks(
        ["c3", "c1", "c2", "c0"],
        locators,
        occurrences,
        fetcher=DictFetcher({}),
        chunks_dir=tmp_path,
        workers=1,
    )
    assert [result.chunk_id for result in results] == ["c3", "c1", "c2", "c0"]


def test_no_pending_chunks_avoids_a_pool(tmp_path: Path) -> None:
    results = process_chunks([], {}, {}, fetcher=DictFetcher({}), chunks_dir=tmp_path)
    assert results == ()


# --- real process pool ----------------------------------------------------


def test_process_chunks_runs_across_processes(tmp_path: Path) -> None:
    """The pool boundary is the real test: a fetcher must survive pickling."""
    db_path = tmp_path / "fixture.sqlite"
    locators = {f"c{i}": [_locator(f"d{i}.htm")] for i in range(3)}
    for locator in locators.values():
        _seed_fixture(db_path, locator[0], BODY.encode())

    results = process_chunks(
        ["c0", "c1", "c2"],
        locators,
        {name: [] for name in locators},
        fetcher=FixtureArchiveFetcher([db_path]),
        chunks_dir=tmp_path,
        workers=2,
    )
    assert len(results) == 3
    assert all(result.ok for result in results)
    assert all(result.normalized_count == 1 for result in results)
    for name in locators:
        assert chunk_checkpoint_path(tmp_path, name).is_file()


def test_fetcher_survives_the_pool_boundary(tmp_path: Path) -> None:
    fetcher = FixtureArchiveFetcher([tmp_path / "fixture.sqlite"])
    assert isinstance(pickle.loads(pickle.dumps(fetcher)), FixtureArchiveFetcher)


# --- resource budgeting ---------------------------------------------------


def test_worker_count_comes_from_resources_not_cpu_count() -> None:
    count = resolved_worker_count()
    assert count >= 1
    assert count < 1024


def test_explicit_worker_count_wins() -> None:
    assert resolved_worker_count(requested=3) == 3
    assert resolved_worker_count(requested=0) >= 1


def test_resource_profile_bounds_the_worker_count() -> None:
    from edgar_sec.foundation.runtime.resources import derive_resources

    profile = derive_resources()
    assert resolved_worker_count(profile) >= 1
    assert resolved_worker_count(profile, requested=1) == 1


# --- processor contract ---------------------------------------------------


def test_processed_document_exposes_its_text() -> None:
    processed = ProcessedDocument(
        document_locator_key="k", payload=b"one two three", byte_size=13, mime_type="t"
    )
    assert processed.text == "one two three"
    assert processed.word_count == 3


def test_filing_processor_records_the_cover_boundary() -> None:
    locator = _locator()
    processed = FilingProcessor().process(BODY.encode(), locator)
    assert processed.metadata["cover_boundary_method"] != "disabled"
    assert processed.metadata["representation"] == "ascii"
    assert processed.metadata["word_count"] > 20
    # The detected boundary is exclusive and pre-reflow, so it lands on "PART I".
    assert processed.metadata["cover_boundary_detected_line"] == 17
    assert processed.metadata["cover_boundary_line"] is not None
    assert processed.metadata["cover_start_detected_line"] == 1


def test_filing_processor_survives_a_payload_carrying_page_markers() -> None:
    """`PageMarkerAction` has no STRIP, so any payload with page furniture raised."""
    payload = b"\n".join(
        [
            b"UNITED STATES SECURITIES AND EXCHANGE COMMISSION",
            b"FORM 10-K",
            b"ACME INDUSTRIES, INC.",
            b"<PAGE>",
            b"PART I",
            b"ITEM 1. BUSINESS",
            b"The Company manufactures widgets and services for customers.",
            b"</PAGE>",
        ]
    )
    processed = FilingProcessor().process(payload, _locator())

    assert "page_marker_count" in processed.metadata
    assert processed.metadata["page_marker_count"] > 0
    assert processed.metadata["page_marker_stripped_count"] > 0


def test_chunk_resumes_from_partial_staging_file(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.parquet import StagedParquetWriter
    from edgar_sec.pipelines.document_storage.checkpoint import DOCUMENT_SNAPSHOT_SCHEMA
    from edgar_sec.pipelines.document_storage.worker import _build_snapshot_batch

    loc1 = _locator("doc1.htm")
    occ1 = _occurrence(loc1)
    loc2 = _locator("doc2.htm")
    occ2 = FilingOccurrence(
        occurrence_id="occ-2",
        source_cik=Cik.from_raw("1234567"),
        accession=loc2.accession,
        document_path=loc2.document_path,
        form="10-K",
        filing_date="2012-02-15",
        report_date="2011-12-31",
        doc_id=loc2.document_locator_key,
    )

    chunk_path = chunk_checkpoint_path(tmp_path, "c_resume")
    with StagedParquetWriter(
        chunk_path, schema=DOCUMENT_SNAPSHOT_SCHEMA, id_column="occurrence_id"
    ) as writer:
        batch = _build_snapshot_batch(
            [occ1],
            raw_payload=b"DOC1 TEXT",
            norm_text="DOC1 TEXT",
            status="ok",
            error=None,
        )
        writer.write_batch(batch)

    assert (tmp_path / "chunk-c_resume.parquet.tmp").is_file()
    assert not chunk_path.is_file()

    fetcher = DictFetcher({"doc1.htm": b"DOC1 TEXT", "doc2.htm": b"DOC2 TEXT"})
    result = process_chunk(
        "c_resume",
        "w1",
        [loc1, loc2],
        [occ1, occ2],
        fetcher=fetcher,
        processor=PassThroughProcessor(),
        chunks_dir=tmp_path,
    )

    assert result.occurrences == 2
    assert result.normalized_count == 2
    assert result.failed_count == 0
    assert result.missing_count == 0
    assert result.ok is True
    assert chunk_path.is_file()
    assert not (tmp_path / "chunk-c_resume.parquet.tmp").exists()
    assert fetcher.calls == ["doc2.htm"]


def test_chunk_resumes_when_all_documents_already_staged(tmp_path: Path) -> None:
    """Interrupted before commit(), resuming must still report every document."""
    from edgar_sec.infra.storage.parquet import StagedParquetWriter
    from edgar_sec.pipelines.document_storage.checkpoint import DOCUMENT_SNAPSHOT_SCHEMA
    from edgar_sec.pipelines.document_storage.operator import _partial_ok
    from edgar_sec.pipelines.document_storage.worker import _build_snapshot_batch

    loc1 = _locator("doc1.htm")
    occ1 = _occurrence(loc1)
    loc2 = _locator("doc2.htm")
    occ2 = FilingOccurrence(
        occurrence_id="occ-2",
        source_cik=Cik.from_raw("1234567"),
        accession=loc2.accession,
        document_path=loc2.document_path,
        form="10-K",
        filing_date="2012-02-15",
        report_date="2011-12-31",
        doc_id=loc2.document_locator_key,
    )

    fresh_dir = tmp_path / "fresh"
    fresh_fetcher = DictFetcher({"doc1.htm": b"DOC1 TEXT", "doc2.htm": b"DOC2 TEXT"})
    fresh_result = process_chunk(
        "c_test",
        "w_fresh",
        [loc1, loc2],
        [occ1, occ2],
        fetcher=fresh_fetcher,
        processor=PassThroughProcessor(),
        chunks_dir=fresh_dir,
    )
    assert fresh_result.normalized_count == 2
    assert fresh_result.ok is True

    resume_dir = tmp_path / "resume"
    chunk_path = chunk_checkpoint_path(resume_dir, "c_test")
    with StagedParquetWriter(
        chunk_path, schema=DOCUMENT_SNAPSHOT_SCHEMA, id_column="occurrence_id"
    ) as writer:
        batch = _build_snapshot_batch(
            [occ1, occ2],
            raw_payload=b"DOC TEXT",
            norm_text="DOC TEXT",
            status="ok",
            error=None,
        )
        writer.write_batch(batch)

    assert (resume_dir / "chunk-c_test.parquet.tmp").is_file()

    resume_fetcher = DictFetcher({})
    resumed_result = process_chunk(
        "c_test",
        "w_resume",
        [loc1, loc2],
        [occ1, occ2],
        fetcher=resume_fetcher,
        processor=PassThroughProcessor(),
        chunks_dir=resume_dir,
    )

    assert resumed_result.normalized_count == 2
    assert resumed_result.failed_count == 0
    assert resumed_result.missing_count == 0
    assert resumed_result.ok is True

    assert _partial_ok([resumed_result]) is True

    assert resumed_result.payload_sha256 == fresh_result.payload_sha256
    assert resume_fetcher.calls == []
