from edgar_sec.domain.document.models import (
    DocumentKind,
    DocumentLocator,
    DocumentPathSource,
    FilingOccurrence,
    RawDocumentBlob,
    derive_document_locator_key,
    derive_occurrence_id,
)
from edgar_sec.domain.identity import AccessionNumber, Cik


def test_document_locator_creation() -> None:
    acc = AccessionNumber("0000320193-23-000106")
    path = "aapl-20230930.htm"
    loc = DocumentLocator.from_parts(acc, path)

    assert loc.accession == acc
    assert loc.document_path == path
    assert loc.document_locator_key == derive_document_locator_key(str(acc), path)


def test_raw_document_blob_serialization() -> None:
    blob = RawDocumentBlob(
        doc_id="abc12345",
        accession="0000320193-23-000106",
        document_path="aapl-20230930.htm",
        byte_size=123456,
        mime_type="text/html",
        raw_payload_sha256="deadbeef",
    )
    row = blob.to_row()
    assert row["doc_id"] == "abc12345"
    assert row["byte_size"] == 123456

    restored = RawDocumentBlob.from_row(row)
    assert restored == blob


def test_filing_occurrence_creation() -> None:
    occ_id = derive_occurrence_id("0000320193", "0000320193-23-000106", "form10k.htm")
    occ = FilingOccurrence(
        occurrence_id=occ_id,
        source_cik=Cik.from_raw("0000320193"),
        accession=AccessionNumber("0000320193-23-000106"),
        document_path="form10k.htm",
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        doc_id="doc_xyz",
    )
    row = occ.to_row()
    assert row["source_cik"] == "0000320193"
    assert row["accession"] == "0000320193-23-000106"

    restored = FilingOccurrence.from_row(row)
    assert restored == occ
    assert DocumentKind.HTML == "html"


def test_document_path_source_values() -> None:
    """DocumentPathSource covers catalog metadata, the bundle fallback, and recovery."""
    assert DocumentPathSource.PRIMARY_DOCUMENT.value == "primary_document"
    assert DocumentPathSource.SUBMISSION_BUNDLE.value == "submission_bundle"
    assert (
        DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE.value
        == "recovered_submission_bundle"
    )


def test_document_locator_from_parts_sets_path_source() -> None:
    """from_parts carries the provenance value into the locator."""
    locator = DocumentLocator.from_parts(
        "0000320193-23-000106",
        "aapl-20230930.htm",
        document_path_source=DocumentPathSource.PRIMARY_DOCUMENT,
    )
    assert locator.document_path_source is DocumentPathSource.PRIMARY_DOCUMENT
    assert locator.document_path == "aapl-20230930.htm"
    assert locator.document_locator_key == derive_document_locator_key(
        "000032019323000106", "aapl-20230930.htm"
    )


def test_document_locator_path_source_defaults_to_none() -> None:
    """A locator constructed without provenance leaves the field absent."""
    locator = DocumentLocator.from_parts(
        "0000320193-23-000106",
        "aapl-20230930.htm",
    )
    assert locator.document_path_source is None


def test_path_source_does_not_change_the_locator_key() -> None:
    """Provenance travels with the path; the content key stays accession+path."""
    base = DocumentLocator.from_parts(
        "0000320193-23-000106",
        "aapl-20230930.htm",
    )
    provenanced = DocumentLocator.from_parts(
        "0000320193-23-000106",
        "aapl-20230930.htm",
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    assert base.document_locator_key == provenanced.document_locator_key
    assert base.document_path_source != provenanced.document_path_source
