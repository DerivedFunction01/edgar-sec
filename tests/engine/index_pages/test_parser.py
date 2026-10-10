"""Tests for structural index-page parsing."""

import ast
import typing

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseFailure,
    IndexParseOutcome,
    ParsedIndexPage,
    ParserDiagnostic,
    UnrecognizedIndexPage,
)
from edgar_sec.engine.index_pages.parser import (
    PARSER_FINGERPRINT,
    parse_html_index,
)
from tests.support import fixture_path

ACCESSION = AccessionNumber("0000123456-26-000016")
INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/"
    "0000123456-26-000016-index.html"
)


def _parse(source: bytes) -> IndexParseOutcome:
    return parse_html_index(IndexPageInput(ACCESSION, INDEX_URL, source))


def test_standard_index_page_extracts_tables_and_bundle() -> None:
    page = _parse(fixture_path("document_inventory_index_page.html").read_bytes())

    assert isinstance(page, ParsedIndexPage)
    assert page.page_sha256
    assert [
        (row.table_kind, row.row_ordinal, row.sequence) for row in page.entries
    ] == [
        ("document_format", 0, 1),
        ("document_format", 1, 2),
        ("data_file", 0, 3),
    ]
    primary = page.entries[0]
    assert primary.filename == "report.htm"
    assert primary.document_label == "report.htm iXBRL"
    assert primary.href == (
        "/ix?doc=/Archives/edgar/data/123456/000012345626000016/report.htm"
    )
    assert primary.archive_url == (
        "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/report.htm"
    )
    assert page.bundle_url == (
        "https://www.sec.gov/Archives/edgar/data/123456/"
        "000012345626000016/0000123456-26-000016.txt"
    )
    assert page.bundle_size == 24_877_468
    assert page.xbrl_candidate_url is None
    assert page.diagnostics.items == ()


def test_unlinked_child_row_is_preserved() -> None:
    source = b"""<table summary='Document Format Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td>1</td><td>EX-99</td><td>not linked</td><td>EX-99</td><td>12</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert len(page.entries) == 1
    assert page.entries[0].filename is None
    assert page.entries[0].href is None
    assert page.entries[0].archive_url is None


def test_non_accession_link_is_preserved_but_not_promoted() -> None:
    source = b"""<table summary='Data Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td>1</td><td>Data</td><td><a href='https://example.test/file.xml'>file.xml</a></td><td>XML</td><td>10</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert page.entries[0].href == "https://example.test/file.xml"
    assert page.entries[0].archive_url is None
    assert [item.code for item in page.diagnostics.items] == ["unsafe_href"]


def test_empty_and_other_accession_hrefs_are_not_promoted() -> None:
    source = b"""<table summary='Data Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td>1</td><td>Blank</td><td><a href=''>blank</a></td><td>XML</td><td>10</td></tr>
    <tr><td>2</td><td>Other accession</td><td><a href='/Archives/edgar/data/123456/000012345626000099/other.xml'>other.xml</a></td><td>XML</td><td>10</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert [entry.archive_url for entry in page.entries] == [None, None]
    assert [item.code for item in page.diagnostics.items] == [
        "unsafe_href",
        "unsafe_href",
    ]


def test_archive_href_policy_rejects_traversal_and_empty_delimiters() -> None:
    hrefs = [
        "/Archives/edgar/data/123456/000012345626000016/../report.htm",
        "/ix?doc=/Archives/edgar/data/123456/000012345626000016/../report.htm",
        "https://attacker.example/ix?doc=/Archives/edgar/data/123456/"
        "000012345626000016/report.htm",
    ]
    source = (
        """<table summary='Data Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    """
        + "".join(
            f"<tr><td>{index}</td><td>File</td><td><a href='{href}'>report.htm</a></td>"
            "<td>XML</td><td>10</td></tr>"
            for index, href in enumerate(hrefs, start=1)
        )
        + "</table>"
    )

    page = _parse(source.encode())

    assert isinstance(page, ParsedIndexPage)
    assert [entry.archive_url for entry in page.entries] == [None] * len(hrefs)
    assert sum(item.code == "unsafe_href" for item in page.diagnostics.items) == len(
        hrefs
    )


def test_bundle_row_is_not_a_child_entry_and_needs_no_sequence() -> None:
    source = b"""<table summary='Document Format Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td></td><td>Complete submission text file</td><td><a href='/Archives/edgar/data/123456/000012345626000016/0000123456-26-000016.txt'>0000123456-26-000016.txt</a></td><td></td><td>100</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert page.entries == ()
    assert page.bundle_size == 100
    assert page.diagnostics.items == ()


def test_tables_use_header_labels_instead_of_column_positions() -> None:
    source = b"""<table summary='Data Files'>
    <tr><th>Type</th><th>Document</th><th>Size</th><th>Seq</th><th>Description</th></tr>
    <tr><td>EX-99</td><td><a href='/Archives/edgar/data/123456/000012345626000016/a.xml'>a.xml</a></td><td>1,234</td><td>4</td><td>Data</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert page.entries[0].sequence == 4
    assert page.entries[0].byte_size == 1234
    assert page.entries[0].document_type == "EX-99"
    assert page.entries[0].description == "Data"


def test_duplicate_sequence_and_filename_are_retained_and_diagnosed() -> None:
    source = b"""<table summary='Document Format Files'>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td>2</td><td>One</td><td><a href='/Archives/edgar/data/123456/000012345626000016/a.htm'>a.htm</a></td><td>EX-1</td><td>10</td></tr>
    <tr><td>2</td><td>Two</td><td><a href='/Archives/edgar/data/123456/000012345626000016/a.htm'>a.htm</a></td><td>EX-2</td><td>20</td></tr>
    <tr><td>1</td><td>Three</td><td><a href='/Archives/edgar/data/123456/000012345626000016/b.htm'>b.htm</a></td><td>EX-3</td><td>30</td></tr>
    </table>"""

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert len(page.entries) == 3
    codes = [item.code for item in page.diagnostics.items]
    assert "duplicate_sequence" in codes
    assert "duplicate_filename" in codes
    assert "out_of_order_sequence" in codes


def test_unknown_page_and_unsupported_encoding_are_typed() -> None:
    unrecognized = _parse(b"<html><body>no filing tables</body></html>")
    unsupported = _parse(b"<html>\xff</html>")

    assert isinstance(unrecognized, UnrecognizedIndexPage)
    assert isinstance(unsupported, IndexParseFailure)
    assert unsupported.diagnostic.code == "unsupported_encoding"


def test_diagnostics_are_bounded() -> None:
    rows = b"".join(b"<tr><td>x</td></tr>" for _ in range(40))
    source = (
        b"<table summary='Data Files'><tr><th>Seq</th><th>Description</th>"
        b"<th>Document</th><th>Type</th><th>Size</th></tr>" + rows + b"</table>"
    )

    page = _parse(source)

    assert isinstance(page, ParsedIndexPage)
    assert len(page.diagnostics.items) == 32
    assert page.diagnostics.suppressed_count > 0


def test_diagnostic_codes_and_union_remain_explicit() -> None:
    hints = typing.get_type_hints(ParserDiagnostic)
    codes = typing.get_args(hints["code"])
    assert set(codes) == {
        "unknown_table",
        "missing_column",
        "missing_sequence",
        "invalid_sequence",
        "duplicate_sequence",
        "out_of_order_sequence",
        "duplicate_filename",
        "invalid_size",
        "unsafe_href",
        "malformed_html",
        "unsupported_encoding",
    }
    assert set(typing.get_args(IndexParseOutcome)) == {
        ParsedIndexPage,
        UnrecognizedIndexPage,
        IndexParseFailure,
    }
    assert PARSER_FINGERPRINT == "index-page-v1"


def test_parser_imports_only_lower_layers_and_pipeline_siblings() -> None:
    import edgar_sec.engine.index_pages.parser as module

    tree = ast.parse(module.__loader__.get_source(module.__name__))
    allowed = ("edgar_sec.domain", "edgar_sec.engine", "edgar_sec.foundation")
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("edgar_sec.")
    }
    assert all(
        any(path == root or path.startswith(root + ".") for root in allowed)
        for path in imports
    )
