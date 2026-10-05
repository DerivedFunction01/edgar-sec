"""Tests for document acquisition domain records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from edgar_sec.domain.document.acquisition import (
    AcquiredSubmission,
    AcquisitionFailure,
    AcquisitionSource,
    AcquisitionSourceKind,
    FetchResult,
    SubmissionFormat,
    describe_submission_document,
    direct_acquisition,
    is_stub_document_path,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    derive_document_locator_key,
)
from edgar_sec.domain.document.route import DocumentRoute

LOCATOR = DocumentLocator.from_parts(
    "0001234567-11-000001",
    "acme-10k.htm",
    archive_url="https://www.sec.gov/Archives/edgar/data/1234567/x/acme-10k.htm",
    form="10-K",
    source_cik="1234567",
)


def _ok(payload: bytes = b"<html>body</html>") -> FetchResult:
    return FetchResult(
        locator=LOCATOR, status="ok", acquired=direct_acquisition(LOCATOR, payload)
    )


def _document(filename: str | None, doc_type: str | None, sequence: int | None):
    return describe_submission_document(
        document_path=filename,
        content_route=DocumentRoute.TEXT,
        sequence=sequence,
        doc_type=doc_type,
    )


def _sgml(documents, selected_index: int, payload: bytes = b"body") -> FetchResult:
    return FetchResult(
        locator=LOCATOR,
        status="ok",
        acquired=AcquiredSubmission(
            requested_locator=LOCATOR,
            source_format=SubmissionFormat.SGML,
            documents=tuple(documents),
            selected_index=selected_index,
            selected_payload=payload,
        ),
    )


def test_locator_key_is_derived_not_supplied() -> None:
    same = DocumentLocator.from_parts(
        "0001234567-11-000001", "acme-10k.htm", archive_url="https://other"
    )
    assert LOCATOR.document_locator_key == same.document_locator_key
    assert LOCATOR.document_locator_key == derive_document_locator_key(
        "0001234567-11-000001", "acme-10k.htm"
    )


def test_locator_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        LOCATOR.accession = "other"  # type: ignore[misc]


def test_locator_exposes_stub_state() -> None:
    assert LOCATOR.is_stub_path is False
    stub = DocumentLocator.from_parts(
        "0001234567-11-000001", "acme-10k-0001.htm", archive_url="u"
    )
    assert stub.is_stub_path is True


def test_ok_requires_an_acquired_submission() -> None:
    assert _ok().ok is True
    assert FetchResult(LOCATOR, "missing").ok is False
    assert FetchResult(LOCATOR, "failed").ok is False


def test_ok_without_an_acquired_submission_is_rejected() -> None:
    """A success status with nothing acquired is a contradiction, not a fetch."""
    with pytest.raises(ValueError, match="ok fetch"):
        FetchResult(LOCATOR, "ok")


def test_an_unsuccessful_fetch_carries_no_acquisition() -> None:
    with pytest.raises(ValueError, match="no acquired submission"):
        FetchResult(LOCATOR, "failed", acquired=direct_acquisition(LOCATOR, b"x"))


def test_an_acquired_submission_must_name_the_requested_locator() -> None:
    other = DocumentLocator.from_parts(
        "0001234567-11-000002", "other.htm", archive_url="u"
    )
    with pytest.raises(ValueError, match="requested locator"):
        FetchResult(LOCATOR, "ok", acquired=direct_acquisition(other, b"x"))


def test_byte_size_counts_only_the_selected_payload() -> None:
    assert _ok(b"12345").byte_size == 5
    assert FetchResult(LOCATOR, "failed").byte_size == 0


def test_fetch_result_carries_the_source_bundle_separately() -> None:
    result = FetchResult(
        LOCATOR,
        "ok",
        acquired=direct_acquisition(LOCATOR, b"body"),
        source_payload=b"bundle",
    )
    assert result.source_payload == b"bundle"
    assert result.error is None


def test_direct_acquisition_routes_from_the_requested_path() -> None:
    acquired = _ok().acquired
    assert acquired is not None
    assert acquired.source_format is SubmissionFormat.DIRECT
    assert acquired.selected_document.content_route is DocumentRoute.MARKUP


def test_rendered_acquisition_keeps_the_rendered_route() -> None:
    """An archive-root URL may serve a .xml name; the requested path is still rendered."""
    rendered = DocumentLocator.from_parts(
        "0001234567-11-000001", "xslF345X02/edgar.xml", archive_url="https://x"
    )
    acquired = direct_acquisition(rendered, b"<html>x</html>")
    assert acquired.selected_document.content_route is DocumentRoute.RENDERED


def test_every_document_carries_its_own_route() -> None:
    acquired = _sgml(
        [
            describe_submission_document(
                document_path="ownership.xml", content_route=DocumentRoute.XML
            ),
            describe_submission_document(
                document_path="ex99.htm", content_route=DocumentRoute.MARKUP
            ),
        ],
        selected_index=0,
    ).acquired
    assert acquired is not None
    assert [doc.content_route for doc in acquired.documents] == [
        DocumentRoute.XML,
        DocumentRoute.MARKUP,
    ]


def test_selected_index_identifies_the_loaded_body() -> None:
    """Duplicated filenames cannot identify it; position is the only link."""
    acquired = _sgml(
        [_document("a.xml", "4", 1), _document("a.xml", "4", 2)],
        selected_index=1,
        payload=b"second",
    ).acquired
    assert acquired is not None
    assert acquired.selected_document.sequence == 2
    assert acquired.selected_payload == b"second"


def test_missing_headers_are_recorded_as_absent() -> None:
    acquired = _sgml([_document(None, None, None)], 0).acquired
    assert acquired is not None
    assert acquired.selected_document.document_path is None
    assert acquired.selected_document.doc_type is None
    assert acquired.selected_document.sequence is None


def test_an_unrecognized_filename_suffix_stays_unknown() -> None:
    """No XML is inferred from the payload or the form."""
    descriptor = describe_submission_document(
        document_path="ownership", content_route=DocumentRoute.UNKNOWN
    )
    assert descriptor.content_route is DocumentRoute.UNKNOWN


def test_sgml_child_route_follows_the_child_filename() -> None:
    """A bundle's .txt suffix says nothing about the sub-document it delivered."""
    descriptor = describe_submission_document(
        document_path="ownership.xml", content_route=DocumentRoute.XML
    )
    assert _sgml([descriptor], 0).acquired is not None


def test_an_empty_submission_is_rejected() -> None:
    with pytest.raises(ValueError, match="describe a document"):
        AcquiredSubmission(
            requested_locator=LOCATOR,
            source_format=SubmissionFormat.SGML,
            documents=(),
            selected_index=0,
            selected_payload=b"x",
        )


def test_an_out_of_range_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="selected_index"):
        AcquiredSubmission(
            requested_locator=LOCATOR,
            source_format=SubmissionFormat.SGML,
            documents=(_document("a.xml", "4", 1),),
            selected_index=1,
            selected_payload=b"x",
        )


def test_a_direct_acquisition_describes_one_document() -> None:
    with pytest.raises(ValueError, match="exactly one document"):
        AcquiredSubmission(
            requested_locator=LOCATOR,
            source_format=SubmissionFormat.DIRECT,
            documents=(_document("a.xml", "4", 1), _document("b.xml", "4", 2)),
            selected_index=0,
            selected_payload=b"x",
        )


def test_an_acquired_submission_is_scoped_to_its_locator() -> None:
    acquired = _ok().acquired
    assert acquired is not None
    assert acquired.accession == LOCATOR.accession
    assert acquired.document_locator_key == LOCATOR.document_locator_key
    assert acquired.requested_locator.document_path == LOCATOR.document_path


def test_the_requested_key_never_becomes_the_child_filename() -> None:
    descriptor = describe_submission_document(
        document_path="ownership.xml", content_route=DocumentRoute.XML
    )
    acquired = _sgml([descriptor], 0).acquired
    assert acquired is not None
    assert acquired.document_locator_key == LOCATOR.document_locator_key
    assert acquired.selected_document.document_path == "ownership.xml"


def test_the_acquisition_source_is_reported() -> None:
    source = AcquisitionSource(
        kind=AcquisitionSourceKind.ARCHIVE_URL, reference="https://x/acme-10k.htm"
    )
    acquired = direct_acquisition(LOCATOR, b"<html>x</html>", source=source)
    assert acquired.source is source
    assert acquired.source.kind is AcquisitionSourceKind.ARCHIVE_URL


def test_the_acquisition_source_is_optional() -> None:
    assert direct_acquisition(LOCATOR, b"x").source is None


def test_an_acquired_submission_carries_no_source_bundle() -> None:
    """A 200MB envelope stays transport data; only the selected payload survives."""
    assert not hasattr(_ok().acquired, "source_payload")


def test_acquired_submission_is_frozen() -> None:
    acquired = _ok().acquired
    assert acquired is not None
    with pytest.raises(FrozenInstanceError):
        acquired.selected_payload = b"other"  # type: ignore[misc]


def test_a_submission_document_carries_no_body() -> None:
    descriptor = describe_submission_document(
        document_path="a.xml", content_route=DocumentRoute.XML
    )
    assert not hasattr(descriptor, "payload")


def test_acquisition_failure_defaults() -> None:
    failure = AcquisitionFailure(
        document_locator_key="k", accession="a", document_path="p", error="boom"
    )
    assert failure.status == "failed"
    assert failure.metadata == {}


@pytest.mark.parametrize(
    "path",
    ["", None, "acme-10k-0001.htm", "acme-10k-0001.txt", "x-0000.htm", "x-0000.txt"],
)
def test_stub_paths(path: str | None) -> None:
    assert is_stub_document_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["acme-10k.htm", "0001234567-11-000001.txt", "xslF345X02/doc3.xml"],
)
def test_non_stub_paths(path: str) -> None:
    assert is_stub_document_path(path) is False
