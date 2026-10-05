"""Processor contract: route-driven normalization and checkpoint identity."""

from __future__ import annotations

from edgar_sec.domain.document.acquisition import (
    AcquiredSubmission,
    SubmissionFormat,
    describe_submission_document,
    direct_acquisition,
)
from edgar_sec.domain.document.models import DocumentLocator
from edgar_sec.domain.document.route import (
    REPRESENTATION_XML,
    DocumentRoute,
)
from edgar_sec.pipelines.document_storage.processor import (
    PROCESSOR_FINGERPRINT,
    PROCESSOR_SCHEMA_VERSION,
    FilingProcessor,
    PassThroughProcessor,
)

_PAPER_STUB = (
    b"<SEC-HEADER>\n"
    b"<DOCUMENT>\n"
    b"<TYPE>19B-4E\n"
    b"<SEQUENCE>1\n"
    b"<FILENAME>9999999997-25-001505.paper\n"
    b"<DESCRIPTION>AUTO-GENERATED PAPER DOCUMENT\n"
    b"<TEXT>\n"
    b"This document was generated as part of a paper submission.\n"
    b"Please reference the Document Control Number 25000522 for access to "
    b"the original document.\n"
    b"</TEXT>\n"
    b"</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


_OWNERSHIP_XML = (
    b'<?xml version="1.0"?>\n'
    b"<ownershipDocument>\n"
    b"  <issuerName>ACME INDUSTRIAL WIDGETS, INC.</issuerName>\n"
    b"  <periodOfReport>2011-12-31</periodOfReport>\n"
    b"</ownershipDocument>\n"
)

#: A minimal PDF whose non-ASCII bytes must survive verbatim when stored.
_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def _locator(document_path: str, form: str) -> DocumentLocator:
    return DocumentLocator.from_parts("0001234567-11-000001", document_path, form=form)


def _acquired(payload: bytes, document_path: str, form: str):
    """An acquisition whose route follows the requested path, as a direct fetch does."""
    return direct_acquisition(_locator(document_path, form), payload)


def test_schema_version_is_two() -> None:
    assert PROCESSOR_SCHEMA_VERSION == 2
    assert PROCESSOR_FINGERPRINT == "document-storage-normalizer:v2"


def test_fingerprint_changed_from_v1() -> None:
    """A v1 checkpoint must not be reusable after the normalization change."""
    assert PROCESSOR_FINGERPRINT != "document-storage-normalizer:v1"


def test_paper_stub_bypasses_the_evaluator() -> None:
    processed = FilingProcessor().process(
        _acquired(_PAPER_STUB, "9999999997-25-001505.paper", "REGDEX")
    )

    assert processed.decision is None
    assert processed.representation == "ascii"
    assert "Document Control Number 25000522" in processed.text


def test_paper_fast_path_is_not_family_specific() -> None:
    """The bypass keys on the route, so a cover-bearing family bypasses too."""
    processed = FilingProcessor().process(
        _acquired(_PAPER_STUB, "9999999997-25-001505.paper", "ARS")
    )

    assert processed.decision is None
    assert processed.metadata["word_count"] == len(processed.text.split())


def test_rendered_path_is_not_reported_as_xml() -> None:
    payload = b"<HTML><BODY><TABLE><TR><TD>OWNERSHIP</TD></TR></TABLE></BODY></HTML>"

    processed = FilingProcessor().process(
        _acquired(payload, "xslF345X03/doc4.xml", "4")
    )

    assert processed.representation == "html"


def test_flat_xml_path_is_reported_as_xml() -> None:
    payload = b'<?xml version="1.0"?><ownershipDocument><x>1</x></ownershipDocument>'

    processed = FilingProcessor().process(_acquired(payload, "ownership.xml", "4"))

    assert processed.representation == "xml"


def test_pass_through_stores_raw_bytes() -> None:
    processed = PassThroughProcessor().process(
        _acquired(b"\x00\x01raw", "acme.pdf", "CERT")
    )

    assert processed.payload == b"\x00\x01raw"
    assert processed.representation == "raw"


def test_binary_payload_is_stored_verbatim() -> None:
    """Decoding and re-encoding a PDF would replace the filed bytes with invented text."""
    processed = FilingProcessor().process(_acquired(_PDF_BYTES, "chart.pdf", "8-K"))

    assert processed.payload == _PDF_BYTES
    assert processed.byte_size == len(_PDF_BYTES)


def test_binary_payload_reports_raw_and_its_suffix_mime() -> None:
    processed = FilingProcessor().process(_acquired(_PDF_BYTES, "chart.pdf", "8-K"))

    assert processed.representation == "raw"
    assert processed.mime_type == "application/pdf"
    assert processed.text == ""


def test_binary_payload_records_the_deferral() -> None:
    processed = FilingProcessor().process(_acquired(_PDF_BYTES, "chart.pdf", "8-K"))

    assert processed.metadata["normalization"] == "deferred"
    assert processed.metadata["document_route"] == "binary"


def test_binary_payload_skips_the_evaluator() -> None:
    """Triage over bytes that carry no prose always reaches the same verdict."""
    processed = FilingProcessor().process(_acquired(_PDF_BYTES, "chart.pdf", "8-K"))

    assert processed.decision is None


def test_every_binary_suffix_is_stored_verbatim() -> None:
    for suffix, mime in (
        (".pdf", "application/pdf"),
        (".gif", "image/gif"),
        (".jpg", "image/jpeg"),
    ):
        processed = FilingProcessor().process(
            _acquired(_PDF_BYTES, f"chart{suffix}", "8-K")
        )

        assert processed.payload == _PDF_BYTES, suffix
        assert processed.mime_type == mime, suffix


def test_binary_locator_key_names_the_filed_path() -> None:
    """Storing bytes verbatim must not change the document's identity."""
    locator = _locator("chart.pdf", "8-K")

    processed = FilingProcessor().process(direct_acquisition(locator, _PDF_BYTES))

    assert processed.document_locator_key == locator.document_locator_key


def test_the_selected_document_route_drives_normalization() -> None:
    """A sibling's route never decides how the selected body is normalized."""
    locator = _locator("0001234567-11-000001.txt", "4")
    acquired = AcquiredSubmission(
        requested_locator=locator,
        source_format=SubmissionFormat.SGML,
        documents=(
            describe_submission_document(
                document_path="ex99.htm", content_route=DocumentRoute.MARKUP
            ),
            describe_submission_document(
                document_path="ownership.xml", content_route=DocumentRoute.XML
            ),
        ),
        selected_index=1,
        selected_payload=_OWNERSHIP_XML,
    )

    processed = FilingProcessor().process(acquired)

    assert processed.representation == REPRESENTATION_XML
    assert processed.document_locator_key == locator.document_locator_key
