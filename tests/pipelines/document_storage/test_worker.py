"""Tests for chunk acquisition, publication, and the process pool."""

from __future__ import annotations

import pickle
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document.acquisition import (
    AcquiredSubmission,
    AcquisitionSource,
    AcquisitionSourceKind,
    BundleFetchResult,
    FetchResult,
    direct_acquisition,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    FilingOccurrence,
    derive_occurrence_id,
)
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import accession_hyphenated
from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.document_storage.checkpoint import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    chunk_fingerprint,
    is_chunk_complete,
    validate_chunk_snapshot,
)
from edgar_sec.pipelines.document_storage.fetching import (
    FixtureArchiveFetcher,
    extract_from_sgml_envelope,
)
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
from edgar_sec.pipelines.document_storage.processor import (
    FilingProcessor,
    PassThroughProcessor,
    ProcessedDocument,
)
from edgar_sec.pipelines.document_storage.execution import (
    ChunkError,
    process_chunk,
    process_chunks,
    resolved_worker_count,
)
from edgar_sec.pipelines.document_storage.summary import candidate_summary

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


def _acquired(payload: bytes, locator: DocumentLocator) -> AcquiredSubmission:
    """An acquisition whose route follows the requested path, as a direct fetch does."""
    return direct_acquisition(locator, payload)


def _occurrence(locator: DocumentLocator) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            "1234567", str(locator.accession), locator.document_path
        ),
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
            return FetchResult(locator, "failed", error=str(response))
        return FetchResult(
            locator, "ok", acquired=direct_acquisition(locator, response)
        )

    def fetch_bundle(self, locator: DocumentLocator) -> BundleFetchResult:
        return BundleFetchResult(status="missing", error="no test bundle")


def _seed_fixture(db_path: Path, locator: DocumentLocator, payload: bytes) -> None:
    with FixtureStore(db_path) as store:
        store.put_many([(locator.document_locator_key, payload)])


_PAPER_STUB = (
    b"<SEC-HEADER>\n<DOCUMENT>\n<TYPE>19B-4E\n<SEQUENCE>1\n"
    b"<FILENAME>9999999997-25-001505.paper\n"
    b"<DESCRIPTION>AUTO-GENERATED PAPER DOCUMENT\n<TEXT>\n"
    b"This document was generated as part of a paper submission.\n"
    b"Please reference the Document Control Number 25000522 for access to "
    b"the original document.\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
)


def test_bypassed_paper_document_is_still_recorded(tmp_path: Path) -> None:
    """Skipping the form-driven stages must not drop the row from the corpus."""
    path = "9999999997-25-001505.paper"
    locator = _locator(document_path=path, form="REGDEX")

    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=DictFetcher({path: _PAPER_STUB}),
        chunks_dir=tmp_path,
    )

    table = read_parquet_table(result.output_path)
    assert table.num_rows == 1
    assert table.column("status").to_pylist() == ["ok"]
    assert table.column("form").to_pylist() == ["10-K"]
    assert table.column("filing_date").to_pylist() == ["2012-02-15"]
    assert table.column("document_locator_key").to_pylist() == [
        locator.document_locator_key
    ]
    assert (
        "Document Control Number 25000522"
        in table.column("normalized_text").to_pylist()[0]
    )


# --- acquisition model at the worker boundary ------------------------------

#: Sequence 1 is an exhibit and the 10-K is at sequence 3. EDGAR SGML is
#: line-oriented, so header tags must start a line to be parsed.
_INVERTED_BUNDLE = (
    b"<SEC-DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>EX-21\n<SEQUENCE>1\n<FILENAME>ex21.txt\n"
    b"<DESCRIPTION>CERTIFICATION OF INCORPORATION\n"
    b"<TEXT>\nEXHIBIT TWENTY ONE BODY\n</TEXT>\n</DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>2\n<FILENAME>acme-10k.htm\n"
    b"<DESCRIPTION>ANNUAL REPORT\n"
    b"<TEXT>\n<HTML><BODY>PRIMARY DOCUMENT BODY</BODY></HTML>\n</TEXT>\n"
    b"</DOCUMENT>\n</SEC-DOCUMENT>\n"
)

#: A bundle requested as ``<accession>.txt`` whose selected primary is XML.
_XML_CHILD_BUNDLE = (
    b"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>4\n<SEQUENCE>1\n"
    b"<FILENAME>ownership.xml\n<TEXT>\n"
    b'<?xml version="1.0"?><ownershipDocument><x>1</x></ownershipDocument>\n'
    b"</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
)


class RecordingProcessor:
    """Processor that records the acquisition it was handed, then passes through."""

    def __init__(self) -> None:
        self.seen: list[AcquiredSubmission] = []
        self.processor_fingerprint = "recording:test"

    def process(self, acquired: AcquiredSubmission) -> ProcessedDocument:
        self.seen.append(acquired)
        return PassThroughProcessor().process(acquired)


class BundleFetcher:
    """Production-shaped fetcher answering an SGML bundle with its own source record."""

    def __init__(self, bundle: bytes) -> None:
        self.bundle = bundle

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        if not locator.document_path.endswith(".txt"):
            return FetchResult(locator, "missing")
        source = AcquisitionSource(
            AcquisitionSourceKind.ARCHIVE_URL,
            f"https://www.sec.gov/x/{locator.document_path}",
        )
        extraction = extract_from_sgml_envelope(self.bundle, locator, source=source)
        if extraction.payload is None:
            return FetchResult(locator, "failed", error="no sub-document")
        return FetchResult(
            locator,
            "ok",
            acquired=extraction.submission,
            source_payload=extraction.bundle,
        )


def test_worker_hands_the_processor_the_selected_payload(tmp_path: Path) -> None:
    """Only the selected sub-document reaches normalization, never the bundle."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")
    processor = RecordingProcessor()

    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        processor=processor,
        chunks_dir=tmp_path,
    )

    assert len(processor.seen) == 1
    assert (
        processor.seen[0].selected_payload
        == b"<HTML><BODY>PRIMARY DOCUMENT BODY</BODY></HTML>"
    )


def test_worker_keeps_the_requested_locator_on_the_acquisition(tmp_path: Path) -> None:
    """The child filename must not become the document's identity."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")
    processor = RecordingProcessor()

    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        processor=processor,
        chunks_dir=tmp_path,
    )

    assert processor.seen[0].requested_locator.document_path == locator.document_path
    assert processor.seen[0].document_locator_key == locator.document_locator_key


def test_worker_projects_the_row_on_the_requested_locator(tmp_path: Path) -> None:
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")

    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        chunks_dir=tmp_path,
    )

    table = read_parquet_table(result.output_path)
    assert table.column("document_path").to_pylist() == [locator.document_path]
    assert table.column("document_locator_key").to_pylist() == [
        locator.document_locator_key
    ]


def test_worker_gives_the_processor_the_acquisition_source(tmp_path: Path) -> None:
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")
    processor = RecordingProcessor()

    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        processor=processor,
        chunks_dir=tmp_path,
    )

    assert processor.seen[0].source is not None
    assert processor.seen[0].source.kind is AcquisitionSourceKind.ARCHIVE_URL


def test_worker_gives_the_processor_every_sub_document(tmp_path: Path) -> None:
    """Every header reaches the processor, but no sibling payload does."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")
    processor = RecordingProcessor()

    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        processor=processor,
        chunks_dir=tmp_path,
    )

    acquired = processor.seen[0]
    assert [doc.document_path for doc in acquired.documents] == [
        "ex21.txt",
        "acme-10k.htm",
    ]
    assert acquired.selected_document.document_path == "acme-10k.htm"
    assert acquired.selected_index == 1
    assert b"EXHIBIT TWENTY ONE BODY" not in acquired.selected_payload


def test_worker_does_not_persist_acquisition_provenance(tmp_path: Path) -> None:
    """Source and headers are in-memory only; the snapshot schema is unchanged."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt")

    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_INVERTED_BUNDLE),
        chunks_dir=tmp_path,
    )

    table = read_parquet_table(result.output_path)
    assert table.column_names == DOCUMENT_SNAPSHOT_SCHEMA.names


def test_sgml_child_routes_by_its_own_filename(tmp_path: Path) -> None:
    """A bundle requested as .txt can deliver XML; the route follows the bytes."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt", form="4")
    processor = RecordingProcessor()

    process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_XML_CHILD_BUNDLE),
        processor=processor,
        chunks_dir=tmp_path,
    )

    assert processor.seen[0].selected_document.content_route is DocumentRoute.XML
    assert processor.seen[0].requested_locator.document_path == locator.document_path


def test_sgml_child_route_reaches_normalization(tmp_path: Path) -> None:
    """An XML primary is normalized as XML rather than reflowed as prose."""
    locator = _locator(document_path=f"{accession_hyphenated(ACCESSION)}.txt", form="4")

    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_occurrence(locator)],
        fetcher=BundleFetcher(_XML_CHILD_BUNDLE),
        chunks_dir=tmp_path,
    )

    text = (
        read_parquet_table(result.output_path).column("normalized_text").to_pylist()[0]
    )
    assert "ownershipDocument" in text


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
        document_locator_key="k",
        payload=b"one two three",
        byte_size=13,
        mime_type="t",
        representation="ascii",
    )
    assert processed.text == "one two three"
    assert processed.word_count == 3


def test_processed_document_raw_representation_has_no_text() -> None:
    """`raw` is the default, so it must mean "no normalized text exists"."""
    processed = ProcessedDocument(
        document_locator_key="k",
        payload=b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n",
        byte_size=15,
        mime_type="application/pdf",
    )
    assert processed.representation == "raw"
    assert processed.text == ""
    assert processed.word_count == 0


def test_filing_processor_records_the_cover_boundary() -> None:
    locator = _locator()
    processed = FilingProcessor().process(_acquired(BODY.encode(), locator))
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
    processed = FilingProcessor().process(_acquired(payload, _locator()))

    assert "page_marker_count" in processed.metadata
    assert processed.metadata["page_marker_count"] > 0
    assert processed.metadata["page_marker_stripped_count"] > 0


def test_chunk_resumes_from_partial_staging_file(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.parquet import StagedParquetWriter
    from edgar_sec.pipelines.document_storage.checkpoint import DOCUMENT_SNAPSHOT_SCHEMA
    from edgar_sec.pipelines.document_storage.processing import _build_snapshot_batch

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
    from edgar_sec.pipelines.document_storage.processing import _build_snapshot_batch

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


# --- the pre-2005 candidate gate -------------------------------------------

_ERA_ACCESSION = "0000890923-01-000002"


def _era_locator(document_path: str, form: str = "10-K") -> DocumentLocator:
    """A locator from the inversion era, so the candidate window is reachable."""
    return DocumentLocator.from_parts(
        _ERA_ACCESSION,
        document_path,
        archive_url=f"https://www.sec.gov/x/{document_path}",
        form=form,
        source_cik="890923",
    )


def _era_occurrence(
    locator: DocumentLocator,
    filing_date: str = "2001-03-01",
    occurrence_id: str = "occ-1",
) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id=occurrence_id,
        source_cik=Cik.from_raw("890923"),
        accession=locator.accession,
        document_path=locator.document_path,
        form="10-K",
        filing_date=filing_date,
        report_date=None,
        doc_id=locator.document_locator_key,
    )


def test_candidate_counts_follow_the_occurrence_filing_date(tmp_path: Path) -> None:
    """The 2001 exhibit is in the window; the 2012 primary is not."""
    exhibit = _era_locator("ex21.txt")
    primary = _locator("acme-10k.htm")
    result = process_chunk(
        "c1",
        "w1",
        [exhibit, primary],
        [_era_occurrence(exhibit), _occurrence(primary)],
        fetcher=DictFetcher(
            {"ex21.txt": b"EXHIBIT BODY", "acme-10k.htm": BODY.encode()}
        ),
        chunks_dir=tmp_path,
    )
    assert result.candidate_eligible_count == 1
    assert result.bundle_candidate_count == 1


def test_a_candidate_request_is_still_acquired_at_its_own_url(tmp_path: Path) -> None:
    """A positive candidate must not promote the request to the accession bundle."""
    locator = _era_locator("ex21.txt")
    payload = b"EXHIBIT TWENTY ONE BODY"
    fetcher = DictFetcher({"ex21.txt": payload})
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_era_occurrence(locator)],
        fetcher=fetcher,
        processor=PassThroughProcessor(),
        chunks_dir=tmp_path,
    )
    assert result.bundle_candidate_count == 1
    assert fetcher.calls == ["ex21.txt"]
    table = pq.read_table(result.output_path)
    assert table.column("document_locator_key").to_pylist() == [
        locator.document_locator_key
    ]
    assert table.column("document_path").to_pylist() == ["ex21.txt"]
    assert table.column("raw_payload").to_pylist() == [payload]
    assert table.column("status").to_pylist() == ["ok"]
    assert table.column("filing_date").to_pylist() == ["2001-03-01"]


def test_a_candidate_decision_adds_no_persisted_column(tmp_path: Path) -> None:
    locator = _era_locator("ex21.txt")
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_era_occurrence(locator)],
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
    )
    assert pq.read_schema(result.output_path).names == DOCUMENT_SNAPSHOT_SCHEMA.names


def test_a_locator_without_a_filing_date_is_not_a_candidate(tmp_path: Path) -> None:
    """An undescribed locator's synthetic row carries no date, so it cannot qualify."""
    locator = _era_locator("ex21.txt")
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [],
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
    )
    assert result.candidate_eligible_count == 0
    assert result.bundle_candidate_count == 0


def test_conflicting_co_filer_dates_fail_the_candidate_gate(tmp_path: Path) -> None:
    locator = _era_locator("ex21.txt")
    occurrences = [
        _era_occurrence(locator, "2001-03-01", "occ-1"),
        _era_occurrence(locator, "2004-03-01", "occ-2"),
    ]
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        occurrences,
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
    )
    assert result.candidate_eligible_count == 0
    assert result.occurrences == 2


def test_co_filer_occurrences_count_once(tmp_path: Path) -> None:
    locator = _era_locator("ex21.txt")
    occurrences = [
        _era_occurrence(locator, "2001-03-01", "occ-1"),
        _era_occurrence(locator, "2001-03-01", "occ-2"),
        _era_occurrence(locator, "2001-03-01", "occ-3"),
    ]
    result = process_chunk(
        "c1",
        "w1",
        [locator, locator],
        occurrences,
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
    )
    assert (result.candidate_eligible_count, result.bundle_candidate_count) == (1, 1)
    assert result.occurrences == 3


def test_a_form_named_document_is_not_a_candidate(tmp_path: Path) -> None:
    """``ex-10k.htm`` is in the window but names the primary form, not an exhibit."""
    locator = _era_locator("ex-10k.htm")
    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [_era_occurrence(locator)],
        fetcher=DictFetcher({"ex-10k.htm": BODY.encode()}),
        chunks_dir=tmp_path,
    )
    assert result.candidate_eligible_count == 1
    assert result.bundle_candidate_count == 0


def test_candidate_summary_matches_a_processed_chunk(tmp_path: Path) -> None:
    """The skip path's plan-derived summary must agree with the processed one."""
    exhibit = _era_locator("ex21.txt")
    ticker = _era_locator("exxon10k.htm")
    locators = [exhibit, ticker, exhibit]
    occurrences = [
        _era_occurrence(exhibit, "2001-03-01", "occ-1"),
        _era_occurrence(ticker, "2001-03-01", "occ-2"),
    ]
    processed = process_chunk(
        "c1",
        "w1",
        locators,
        occurrences,
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY", "exxon10k.htm": b"X"}),
        chunks_dir=tmp_path,
    )
    summary = candidate_summary(locators, occurrences)
    assert summary == (
        processed.candidate_eligible_count,
        processed.bundle_candidate_count,
        processed.candidate_date_unresolved_count,
    )
    assert summary == (2, 1, 0)


def test_a_skipped_chunk_reports_the_same_candidate_counts(tmp_path: Path) -> None:
    """Counts cover the requested plan, so a resumed chunk still reports them."""
    exhibit = _era_locator("ex21.txt")
    locators = {"c1": [exhibit]}
    occurrences = {"c1": [_era_occurrence(exhibit)]}
    first = process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
        workers=1,
    )
    resumed = process_chunks(
        ["c1"],
        locators,
        occurrences,
        fetcher=DictFetcher({}),
        chunks_dir=tmp_path,
        workers=1,
    )
    assert resumed[0].worker_id == "skipped"
    assert (resumed[0].candidate_eligible_count, resumed[0].bundle_candidate_count) == (
        first[0].candidate_eligible_count,
        first[0].bundle_candidate_count,
    )
    assert resumed[0].bundle_candidate_count == 1


def test_candidate_counts_survive_the_pool_boundary(tmp_path: Path) -> None:
    locator = _era_locator("ex21.txt")
    results = process_chunks(
        ["c1"],
        {"c1": [locator]},
        {"c1": [_era_occurrence(locator)]},
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=tmp_path,
        workers=2,
    )
    assert results[0].bundle_candidate_count == 1
