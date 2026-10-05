"""Tests for document acquisition domain records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from edgar_sec.domain.document.acquisition import (
    AcquiredDocument,
    AcquisitionFailure,
    AcquisitionSource,
    AcquisitionSourceKind,
    FetchResult,
    SgmlEnvelopeResolution,
    SgmlSubDocumentHeader,
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


def test_fetch_result_ok_requires_payload() -> None:
    assert FetchResult(LOCATOR, b"x", "ok").ok is True
    assert FetchResult(LOCATOR, None, "ok").ok is False
    assert FetchResult(LOCATOR, b"x", "missing").ok is False
    assert FetchResult(LOCATOR, b"x", "failed").ok is False


def test_fetch_result_byte_size() -> None:
    assert FetchResult(LOCATOR, b"12345", "ok").byte_size == 5
    assert FetchResult(LOCATOR, None, "failed").byte_size == 0


def test_fetch_result_carries_the_source_bundle() -> None:
    result = FetchResult(LOCATOR, b"body", "ok", source_payload=b"bundle")
    assert result.source_payload == b"bundle"
    assert result.error is None


def _header(
    filename: str, doc_type: str, sequence: int | None
) -> SgmlSubDocumentHeader:
    return SgmlSubDocumentHeader(
        sequence=sequence,
        doc_type=doc_type,
        filename=filename,
        description=None,
    )


def _resolved_result(envelope: SgmlEnvelopeResolution) -> FetchResult:
    return FetchResult(LOCATOR, b"<html>body</html>", "ok", envelope=envelope)


def test_acquired_document_is_absent_for_a_failed_fetch() -> None:
    assert FetchResult(LOCATOR, None, "failed").acquired is None
    assert FetchResult(LOCATOR, None, "missing").acquired is None


def test_acquired_document_is_absent_when_payload_is_missing() -> None:
    """A success status without bytes is not an acquisition."""
    assert FetchResult(LOCATOR, None, "ok").acquired is None


def test_direct_acquisition_routes_from_the_requested_path() -> None:
    acquired = FetchResult(LOCATOR, b"<html>x</html>", "ok").acquired
    assert acquired is not None
    assert acquired.content_route is DocumentRoute.MARKUP


def test_rendered_acquisition_keeps_the_rendered_route() -> None:
    """An archive-root URL may serve a .xml name; the requested path is still rendered."""
    rendered = DocumentLocator.from_parts(
        "0001234567-11-000001", "xslF345X02/edgar.xml", archive_url="https://x"
    )
    acquired = FetchResult(rendered, b"<html>x</html>", "ok").acquired
    assert acquired is not None
    assert acquired.content_route is DocumentRoute.RENDERED


def test_sgml_child_route_follows_the_child_filename() -> None:
    """A bundle's .txt suffix says nothing about the sub-document it delivered."""
    envelope = SgmlEnvelopeResolution(
        selected=_header("ownership.xml", "4", 1), siblings=()
    )
    acquired = _resolved_result(envelope).acquired
    assert acquired is not None
    assert acquired.content_route is DocumentRoute.XML


def test_sgml_child_filename_with_a_directory_is_not_read_as_rendered() -> None:
    """A slash in an SGML filename is not an XSL directory."""
    envelope = SgmlEnvelopeResolution(
        selected=_header("xslF345X02/edgar.xml", "4", 1), siblings=()
    )
    acquired = _resolved_result(envelope).acquired
    assert acquired is not None
    assert acquired.content_route is DocumentRoute.XML


def test_acquired_document_keeps_the_requested_locator_key() -> None:
    """The child's filename must never become the document's identity."""
    envelope = SgmlEnvelopeResolution(
        selected=_header("ownership.xml", "4", 1), siblings=()
    )
    acquired = _resolved_result(envelope).acquired
    assert acquired is not None
    assert acquired.document_locator_key == LOCATOR.document_locator_key
    assert acquired.locator.document_path == LOCATOR.document_path


def test_acquired_document_reports_the_acquisition_source() -> None:
    source = AcquisitionSource(
        kind=AcquisitionSourceKind.ARCHIVE_URL, reference="https://x/acme-10k.htm"
    )
    acquired = FetchResult(LOCATOR, b"<html>x</html>", "ok", source=source).acquired
    assert acquired is not None
    assert acquired.source is source
    assert acquired.source.kind is AcquisitionSourceKind.ARCHIVE_URL


def test_acquired_document_source_is_optional() -> None:
    acquired = FetchResult(LOCATOR, b"<html>x</html>", "ok").acquired
    assert acquired is not None
    assert acquired.source is None


def test_direct_acquisition_carries_no_envelope() -> None:
    acquired = FetchResult(LOCATOR, b"<html>x</html>", "ok").acquired
    assert acquired is not None
    assert acquired.envelope is None


def test_acquired_document_carries_no_source_bundle() -> None:
    """A 200MB envelope is released; only the selected payload survives."""
    acquired = FetchResult(
        LOCATOR, b"<html>x</html>", "ok", source_payload=b"envelope bytes"
    ).acquired
    assert acquired is not None
    assert not hasattr(acquired, "source_payload")


def test_acquired_document_is_frozen() -> None:
    acquired = FetchResult(LOCATOR, b"<html>x</html>", "ok").acquired
    assert acquired is not None
    with pytest.raises(FrozenInstanceError):
        acquired.payload = b"other"  # type: ignore[misc]


def test_acquisition_record_can_be_built_directly() -> None:
    acquired = AcquiredDocument(
        locator=LOCATOR, payload=b"x", content_route=DocumentRoute.TEXT
    )
    assert acquired.document_locator_key == LOCATOR.document_locator_key
    assert acquired.envelope is None


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
