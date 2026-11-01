"""Tests for FilingSummary and package enumeration synthesis."""

import hashlib
import io
import zipfile

from edgar_sec.domain.document_inventory.models import (
    EnumeratedDocuments,
    EnumerationFailure,
    EnumerationInput,
    UnrecognizedEnumeration,
    inventory_entry_id,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.filing_summary.parser import (
    ENUMERATOR_FINGERPRINT,
    parse_filing_summary,
    parse_xbrl_package,
)
from tests.support import fixture_path

ACCESSION = AccessionNumber("0000123456-26-000016")
ARCHIVE_CIK = "123456"
SUMMARY_URL = (
    "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/"
    "FilingSummary.xml"
)
PACKAGE_URL = (
    "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/"
    "0000123456-26-000016-xbrl.zip"
)
BUNDLE_URL = (
    "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/"
    "0000123456-26-000016.txt"
)


def _summary_input(source: bytes, *, primary: str, inline: bool) -> EnumerationInput:
    return EnumerationInput(
        accession=ACCESSION,
        source_url=SUMMARY_URL,
        response_bytes=source,
        archive_cik=ARCHIVE_CIK,
        form="10-K",
        primary_document=primary,
        is_inline_xbrl=inline,
    )


def _package_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _by_filename(page: EnumeratedDocuments) -> dict:
    return {entry.filename: entry for entry in page.entries}


def test_classic_summary_synthesizes_primary_and_xbrl_set() -> None:
    source = fixture_path("filing_summary_classic.xml").read_bytes()
    page = parse_filing_summary(
        _summary_input(source, primary="acme10k.htm", inline=False)
    )

    assert isinstance(page, EnumeratedDocuments)
    assert page.bundle_url == BUNDLE_URL
    assert page.page_sha256 == hashlib.sha256(source).hexdigest()
    entries = _by_filename(page)
    primary = entries["acme10k.htm"]
    assert (primary.table_kind, primary.row_ordinal) == ("document_format", 0)
    assert primary.document_type == "10-K"
    assert primary.archive_url == (
        "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/acme10k.htm"
    )
    expected_types = {
        "acme-20121231.xml": ("EX-101.INS", "XBRL INSTANCE DOCUMENT"),
        "acme-20121231.xsd": ("EX-101.SCH", "XBRL TAXONOMY EXTENSION SCHEMA"),
        "acme-20121231_cal.xml": (
            "EX-101.CAL",
            "XBRL TAXONOMY EXTENSION CALCULATION LINKBASE",
        ),
        "acme-20121231_def.xml": (
            "EX-101.DEF",
            "XBRL TAXONOMY EXTENSION DEFINITION LINKBASE",
        ),
        "acme-20121231_lab.xml": (
            "EX-101.LAB",
            "XBRL TAXONOMY EXTENSION LABEL LINKBASE",
        ),
        "acme-20121231_pre.xml": (
            "EX-101.PRE",
            "XBRL TAXONOMY EXTENSION PRESENTATION LINKBASE",
        ),
    }
    assert len(page.entries) == 1 + len(expected_types)
    for filename, (document_type, description) in expected_types.items():
        entry = entries[filename]
        assert entry.table_kind == "data_file"
        assert entry.document_type == document_type
        assert entry.description == description
        assert entry.sequence is None
        assert entry.byte_size is None
        assert entry.entry_id == inventory_entry_id(
            ACCESSION, "data_file", entry.row_ordinal, page.page_sha256
        )


def test_summary_without_input_files_is_unrecognized() -> None:
    source = fixture_path("filing_summary_classic_no_input_files.xml").read_bytes()
    outcome = parse_filing_summary(
        _summary_input(source, primary="acme10k.htm", inline=False)
    )

    assert isinstance(outcome, UnrecognizedEnumeration)
    assert outcome.page_sha256 == hashlib.sha256(source).hexdigest()


def test_inline_summary_dedupes_primary_and_synthesizes_extracted() -> None:
    source = fixture_path("filing_summary_inline.xml").read_bytes()
    page = parse_filing_summary(
        _summary_input(source, primary="acme-10k_20241231.htm", inline=True)
    )

    assert isinstance(page, EnumeratedDocuments)
    primaries = [e for e in page.entries if e.document_type == "10-K"]
    assert [e.filename for e in primaries] == ["acme-10k_20241231.htm"]
    entries = _by_filename(page)
    assert "acme-20121231.xml" not in entries
    assert not any(e.document_type == "EX-101.INS" for e in page.entries)
    for exhibit in ("acme-ex21_10.htm", "acme-ex311_8.htm", "acme-20241231_g1.jpg"):
        entry = entries[exhibit]
        assert entry.table_kind == "document_format"
        assert entry.document_type is None
        assert entry.description is None
    extracted = entries["acme-10k_20241231_htm.xml"]
    assert extracted.table_kind == "data_file"
    assert extracted.document_type == "XML"
    assert extracted.description == "EXTRACTED XBRL INSTANCE DOCUMENT"


def test_malformed_summary_is_a_failure() -> None:
    outcome = parse_filing_summary(
        _summary_input(b"<FilingSummary><InputFiles>", primary="a.htm", inline=False)
    )

    assert isinstance(outcome, EnumerationFailure)
    assert outcome.diagnostic.code == "malformed_xml"


def test_duplicate_listing_name_is_a_diagnostic_not_a_second_entry() -> None:
    source = (
        b"<FilingSummary><InputFiles>"
        b"<File>acme-20121231.xsd</File><File>acme-20121231.xsd</File>"
        b"</InputFiles></FilingSummary>"
    )
    page = parse_filing_summary(
        _summary_input(source, primary="acme10k.htm", inline=False)
    )

    assert isinstance(page, EnumeratedDocuments)
    assert [e.filename for e in page.entries].count("acme-20121231.xsd") == 1
    assert [d.code for d in page.diagnostics.items] == ["duplicate_filename"]


def test_classic_package_supplies_member_sizes() -> None:
    payload = _package_bytes(
        {
            "acme-20121231.xml": b"instance",
            "acme-20121231.xsd": b"schema!",
            "acme-20121231_cal.xml": b"cal",
        }
    )
    page = parse_xbrl_package(
        EnumerationInput(
            accession=ACCESSION,
            source_url=PACKAGE_URL,
            response_bytes=payload,
            archive_cik=ARCHIVE_CIK,
            form="10-K",
            primary_document="acme10k.htm",
            is_inline_xbrl=False,
        )
    )

    assert isinstance(page, EnumeratedDocuments)
    entries = _by_filename(page)
    assert entries["acme-20121231.xml"].byte_size == len(b"instance")
    assert entries["acme-20121231.xsd"].document_type == "EX-101.SCH"
    assert entries["acme10k.htm"].byte_size is None
    assert page.bundle_url == BUNDLE_URL


def test_inline_package_synthesizes_extracted_instance() -> None:
    payload = _package_bytes(
        {
            "acme-10k_20241231.htm": b"primary!",
            "acme-20241231.xsd": b"schema",
            "acme-20241231_pre.xml": b"pre",
            "acme-20241231_g1.jpg": b"graphic",
        }
    )
    page = parse_xbrl_package(
        EnumerationInput(
            accession=ACCESSION,
            source_url=PACKAGE_URL,
            response_bytes=payload,
            archive_cik=ARCHIVE_CIK,
            form="10-K",
            primary_document="acme-10k_20241231.htm",
            is_inline_xbrl=True,
        )
    )

    assert isinstance(page, EnumeratedDocuments)
    entries = _by_filename(page)
    assert entries["acme-10k_20241231.htm"].byte_size == len(b"primary!")
    assert not any(e.document_type == "EX-101.INS" for e in page.entries)
    assert entries["acme-10k_20241231_htm.xml"].document_type == "XML"
    assert entries["acme-20241231_g1.jpg"].document_type is None


def test_malformed_package_is_a_failure() -> None:
    outcome = parse_xbrl_package(
        EnumerationInput(
            accession=ACCESSION,
            source_url=PACKAGE_URL,
            response_bytes=b"not a zip",
            archive_cik=ARCHIVE_CIK,
            form="10-K",
            primary_document="acme10k.htm",
            is_inline_xbrl=False,
        )
    )

    assert isinstance(outcome, EnumerationFailure)
    assert outcome.diagnostic.code == "malformed_package"


def test_enumerator_fingerprint_is_pinned() -> None:
    assert ENUMERATOR_FINGERPRINT == "filing-summary-v1"
