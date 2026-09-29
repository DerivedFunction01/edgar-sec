"""Tests for the bounded exhibit second pass."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document.acquisition import FetchResult
from edgar_sec.domain.document.models import DocumentLocator
from edgar_sec.domain.sec_urls import accession_hyphenated
from edgar_sec.pipelines.document_storage.delegation import (
    exhibits_for,
    resolve_delegated_exhibit,
    write_exhibit_snapshot,
)
from edgar_sec.pipelines.document_storage.fetching import extract_from_sgml_envelope
from edgar_sec.pipelines.document_storage.processor import (
    FilingProcessor,
    ProcessedDocument,
)

ACCESSION = "0001234567-11-000001"

# EDGAR SGML is line-oriented: the unpacker anchors <TYPE>, <SEQUENCE>, and
# <FILENAME> at line starts, so the fixture must be laid out that way.
BUNDLE = (
    b"<SEC-DOCUMENT>\n"
    b"<SEC-HEADER>0001</SEC-HEADER>\n"
    b"<TYPE>10-K\n"
    b"<DOCUMENT>\n"
    b"<TYPE>10-K\n"
    b"<SEQUENCE>1\n"
    b"<FILENAME>acme-10k.htm\n"
    b"<TEXT>\n"
    b"<HTML><BODY>stub body</BODY></HTML>\n"
    b"</TEXT>\n"
    b"</DOCUMENT>\n"
    b"<DOCUMENT>\n"
    b"<TYPE>EX-13\n"
    b"<SEQUENCE>2\n"
    b"<FILENAME>acme-ex13.htm\n"
    b"<TEXT>\n"
    b"<HTML><BODY>annual report exhibit</BODY></HTML>\n"
    b"</TEXT>\n"
    b"</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


def _locator() -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        "acme-10k.htm",
        archive_url="https://www.sec.gov/x/acme-10k.htm",
        form="10-K",
        source_cik="1234567",
    )


def _bundle_locator() -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        f"{accession_hyphenated(ACCESSION)}.txt",
        form="10-K",
        source_cik="1234567",
    )


def _stub_processed(target: str | None) -> ProcessedDocument:
    metadata: dict[str, object] = {"word_count": 3}
    if target is not None:
        metadata["decision_action"] = "refetch_sub_doc"
        metadata["target_exhibit"] = target
    return ProcessedDocument(
        document_locator_key="k",
        payload=b"stub",
        byte_size=4,
        mime_type="text/plain",
        metadata=metadata,
    )


class BundleFetcher:
    """Serves the submission bundle for the bundle locator only."""

    def __init__(self, bundle: bytes | None = BUNDLE) -> None:
        self.bundle = bundle
        self.calls: list[str] = []

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        self.calls.append(locator.document_path)
        if self.bundle is None or not locator.document_path.endswith(".txt"):
            return FetchResult(locator, None, "missing")
        return FetchResult(locator, self.bundle, "ok", source_payload=self.bundle)


# --- gating ---------------------------------------------------------------


def test_a_non_refetch_decision_resolves_nothing() -> None:
    fetcher = BundleFetcher()
    exhibit = resolve_delegated_exhibit(
        _stub_processed(None),
        _locator(),
        fetcher=fetcher,
        processor=FilingProcessor(),
    )
    assert exhibit is None
    assert fetcher.calls == []


def test_a_refetch_without_a_target_resolves_nothing() -> None:
    fetcher = BundleFetcher()
    exhibit = resolve_delegated_exhibit(
        _stub_processed(None),
        _locator(),
        fetcher=fetcher,
        processor=FilingProcessor(),
    )
    assert exhibit is None


def test_a_held_bundle_is_used_without_a_fetch() -> None:
    fetcher = BundleFetcher()
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=fetcher,
        processor=FilingProcessor(),
        source_bundle=BUNDLE,
    )
    assert exhibit is not None
    assert exhibit.source == "in-bundle"
    assert fetcher.calls == []


def test_a_missing_bundle_is_fetched_once() -> None:
    fetcher = BundleFetcher()
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=fetcher,
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    assert exhibit.source == "bundle-fetch"
    assert len(fetcher.calls) == 1


def test_an_unavailable_bundle_yields_nothing() -> None:
    fetcher = BundleFetcher(bundle=None)
    assert (
        resolve_delegated_exhibit(
            _stub_processed("EX-13"),
            _locator(),
            fetcher=fetcher,
            processor=FilingProcessor(),
        )
        is None
    )


def test_an_absent_exhibit_yields_nothing() -> None:
    fetcher = BundleFetcher()
    assert (
        resolve_delegated_exhibit(
            _stub_processed("EX-99"),
            _locator(),
            fetcher=fetcher,
            processor=FilingProcessor(),
        )
        is None
    )


# --- resolution -----------------------------------------------------------


def test_exhibit_uses_the_bundles_own_filename() -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    assert exhibit.document_path == "acme-ex13.htm"
    assert "annual report exhibit" in exhibit.processed.text


def test_exhibit_carries_its_provenance() -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    assert str(exhibit.primary_accession) == ACCESSION
    assert exhibit.primary_form == "10-K"
    assert exhibit.primary_source_cik == "1234567"
    assert exhibit.primary_document_locator_key == _locator().document_locator_key
    metadata = exhibit.processed.metadata
    assert metadata["delegated_from_document_locator_key"] == (
        _locator().document_locator_key
    )
    assert metadata["delegated_from_source_cik"] == "1234567"
    assert metadata["target_exhibit"] == "EX-13"


def test_exhibit_keeps_its_own_normalization_metadata() -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    assert "cover_boundary_method" in exhibit.processed.metadata


def test_payload_sink_sees_the_exhibit() -> None:
    seen: list[tuple[str, bytes]] = []
    resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
        source_bundle=BUNDLE,
        payload_sink=lambda loc, payload: seen.append((loc.document_path, payload)),
    )
    assert [name for name, _ in seen] == ["acme-ex13.htm"]
    assert b"annual report exhibit" in seen[0][1]


def test_bundle_locator_uses_the_hyphenated_accession() -> None:
    fetcher = BundleFetcher()
    resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=fetcher,
        processor=FilingProcessor(),
    )
    assert fetcher.calls == [f"{accession_hyphenated(ACCESSION)}.txt"]


def test_envelope_selection_agrees_on_the_primary() -> None:
    """The resolver and the fetcher must agree on what the primary is."""
    extracted, source = extract_from_sgml_envelope(BUNDLE, _locator())
    assert extracted is not None
    assert b"stub body" in extracted
    assert source == BUNDLE


# --- grouping and publication --------------------------------------------


def test_exhibits_are_grouped_by_primary() -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    grouped = exhibits_for(
        _locator().document_locator_key, {exhibit.document_locator_key: exhibit}
    )
    assert grouped == (exhibit,)
    assert exhibits_for("other-key", {exhibit.document_locator_key: exhibit}) == ()


def test_exhibits_publish_as_a_parquet_chunk(tmp_path: Path) -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed("EX-13"),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
    path = write_exhibit_snapshot(tmp_path / "chunk-delegated.parquet", (exhibit,))
    assert path.is_file()

    table = pq.read_table(path)
    assert table.num_rows == 1
    assert table.column("document_path").to_pylist() == ["acme-ex13.htm"]
    assert table.column("accession").to_pylist() == [ACCESSION]
    assert "annual report exhibit" in table.column("normalized_text").to_pylist()[0]


def test_publishing_no_exhibits_writes_nothing(tmp_path: Path) -> None:
    path = write_exhibit_snapshot(tmp_path / "chunk-delegated.parquet", ())
    assert path.is_file()
    assert pq.read_table(path).num_rows == 0


@pytest.mark.parametrize("target", ["EX-13", "ex-13", " EX-13 "])
def test_target_matching_is_case_insensitive(target: str) -> None:
    exhibit = resolve_delegated_exhibit(
        _stub_processed(target),
        _locator(),
        fetcher=BundleFetcher(),
        processor=FilingProcessor(),
    )
    assert exhibit is not None
