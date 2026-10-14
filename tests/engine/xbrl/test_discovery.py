"""Tests for linkbase classification and index page extraction."""

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    InventoryEntry,
    inventory_entry_id,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.xbrl.discovery import (
    LinkbaseType,
    classify_linkbase_entry,
    extract_filing_linkbases,
)
from tests.support import fixture_path


def _make_entry(doc_type: str, filename: str, desc: str) -> InventoryEntry:
    acc = AccessionNumber.from_any("0000950170-24-087843")
    return InventoryEntry(
        entry_id=inventory_entry_id(acc, "data_file", 1, "digest"),
        accession=acc,
        table_kind="data_file",
        row_ordinal=1,
        sequence=1,
        document_type=doc_type,
        document_label=filename,
        description=desc,
        filename=filename,
        href=f"/Archives/{filename}",
        archive_url=f"https://www.sec.gov/Archives/{filename}",
        byte_size=1024,
    )


def test_classify_linkbase_types() -> None:
    """Verify classification across all standard linkbase variants."""
    assert (
        classify_linkbase_entry(_make_entry("EX-101.CAL", "f_cal.xml", ""))
        == LinkbaseType.CALCULATION
    )
    assert (
        classify_linkbase_entry(_make_entry("EX-101.PRE", "f_pre.xml", ""))
        == LinkbaseType.PRESENTATION
    )
    assert (
        classify_linkbase_entry(_make_entry("EX-101.DEF", "f_def.xml", ""))
        == LinkbaseType.DEFINITION
    )
    assert (
        classify_linkbase_entry(_make_entry("EX-101.LAB", "f_lab.xml", ""))
        == LinkbaseType.LABEL
    )
    assert (
        classify_linkbase_entry(_make_entry("EX-101.SCH", "f.xsd", ""))
        == LinkbaseType.SCHEMA
    )
    assert (
        classify_linkbase_entry(
            _make_entry("XML", "f_htm.xml", "EXTRACTED XBRL INSTANCE")
        )
        == LinkbaseType.INSTANCE
    )
    assert (
        classify_linkbase_entry(_make_entry("ZIP", "f-xbrl.zip", ""))
        == LinkbaseType.PACKAGE
    )
    assert classify_linkbase_entry(_make_entry("10-K", "f.htm", "Primary")) is None


def test_extract_filing_linkbases_from_parsed_fixture() -> None:
    """Verify end-to-end linkbase extraction from real index HTML."""
    html = fixture_path("xbrl/msft_index_page.html").read_bytes()
    acc = AccessionNumber.from_any("0000950170-24-087843")
    page = parse_html_index(IndexPageInput(acc, "https://example.com/idx.html", html))
    assert hasattr(page, "entries")

    linkbases = extract_filing_linkbases(page, Cik(789019))
    types = {lb.linkbase_type for lb in linkbases}
    assert LinkbaseType.CALCULATION in types
    assert LinkbaseType.PRESENTATION in types
    assert LinkbaseType.DEFINITION in types
    assert LinkbaseType.LABEL in types
    assert LinkbaseType.SCHEMA in types
    assert LinkbaseType.INSTANCE in types
    assert LinkbaseType.PACKAGE in types
