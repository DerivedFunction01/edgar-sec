from edgar_sec.domain.document.models import (
    DocumentKind,
    DocumentLocator,
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
