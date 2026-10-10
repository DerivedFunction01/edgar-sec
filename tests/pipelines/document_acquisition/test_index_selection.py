from __future__ import annotations

from edgar_sec.domain.document_inventory.models import (
    IndexParseFailure,
    InventoryEntry,
    ParserDiagnostic,
    ParsedIndexPage,
    ParserDiagnostics,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.pipelines.document_acquisition.index_selection import (
    select_index_entry,
)

ACCESSION = AccessionNumber("0000000001-24-000001")
INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/"
    "0000000001-24-000001-index.html"
)
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/report.htm"
BUNDLE_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/0000000001-24-000001.txt"


def _entry(
    entry_id: str,
    document_type: str | None,
    *,
    sequence: int | None = 1,
    archive_url: str | None = DOCUMENT_URL,
    table_kind: str = "document_format",
) -> InventoryEntry:
    return InventoryEntry(
        entry_id=entry_id,
        accession=ACCESSION,
        table_kind=table_kind,
        row_ordinal=0,
        sequence=sequence,
        document_type=document_type,
        document_label=None,
        description=None,
        filename="report.htm",
        href="report.htm",
        archive_url=archive_url,
        byte_size=1,
    )


def _page(
    *entries: InventoryEntry,
    source_url: str = INDEX_URL,
    bundle_url: str | None = None,
) -> ParsedIndexPage:
    return ParsedIndexPage(
        accession=ACCESSION,
        source_url=source_url,
        page_sha256="a" * 64,
        entries=entries,
        bundle_url=bundle_url,
        bundle_size=None,
        xbrl_candidate_url=None,
        diagnostics=ParserDiagnostics((), 0),
    )


def test_selects_only_exact_document_format_type() -> None:
    selected = _entry("exact", " 10-k ")
    page = _page(
        _entry("amendment", "10-K/A"),
        _entry("data-file", "10-K", table_kind="data_file"),
        selected,
    )

    result = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert result.result == "selected"
    assert result.entry == selected
    assert result.matching_entry_ids == ("exact",)
    assert result.retrieval_mode == "direct_url"
    assert result.selected_url == DOCUMENT_URL


def test_unlinked_exact_type_uses_accession_bundle_and_sequence() -> None:
    selected = _entry("exact", "10-K", sequence=3, archive_url=None)
    page = _page(selected, bundle_url=BUNDLE_URL)

    result = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert result.result == "selected"
    assert result.entry == selected
    assert result.retrieval_mode == "bundle_sequence"
    assert result.selected_url == BUNDLE_URL


def test_duplicate_exact_types_are_ambiguous_independent_of_sequence() -> None:
    page = _page(_entry("one", "10-K", sequence=1), _entry("two", "10-K", sequence=2))

    result = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert result.result == "ambiguous"
    assert result.matching_entry_ids == ("one", "two")
    assert result.entry is None


def test_no_exact_type_maps_to_optional_or_required_absence() -> None:
    page = _page(_entry("amendment", "10-K/A"))

    optional = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=True
    )
    required = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert optional.result == "not_filed"
    assert required.result == "required_missing"


def test_refuses_unrecognized_index_and_wrong_source_scope() -> None:
    unrecognized = UnrecognizedIndexPage(
        ACCESSION, INDEX_URL, "a" * 64, ParserDiagnostics((), 0)
    )
    wrong_source = _page(source_url=DOCUMENT_URL)

    assert (
        select_index_entry(
            unrecognized, accession=ACCESSION, expected_form="10-K", optional=False
        ).error_code
        == "index_unrecognized"
    )
    assert (
        select_index_entry(
            wrong_source, accession=ACCESSION, expected_form="10-K", optional=False
        ).error_code
        == "index_scope_mismatch"
    )


def test_index_selection_binds_entries_to_source_archive_cik() -> None:
    source_url = INDEX_URL.replace("/data/1/", "/data/2/")
    document_url = DOCUMENT_URL.replace("/data/1/", "/data/2/")
    page = _page(
        _entry("same-cik", "10-K", archive_url=document_url), source_url=source_url
    )
    wrong_cik_page = _page(_entry("other-cik", "10-K"), source_url=source_url)

    selected = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )
    rejected = select_index_entry(
        wrong_cik_page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert selected.result == "selected"
    assert rejected.result == "failed"
    assert rejected.error_code == "index_entry_unaddressable"


def test_refuses_matching_row_without_safe_retrieval_locator() -> None:
    page = _page(_entry("unaddressable", "10-K", sequence=None, archive_url=None))

    result = select_index_entry(
        page, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert result.result == "failed"
    assert result.error_code == "index_entry_unaddressable"
    assert result.matching_entry_ids == ("unaddressable",)


def test_refuses_parser_failure() -> None:
    failed = IndexParseFailure(
        ACCESSION,
        INDEX_URL,
        "a" * 64,
        diagnostic=ParserDiagnostic("unknown_table", None, "unrecognized"),
    )

    result = select_index_entry(
        failed, accession=ACCESSION, expected_form="10-K", optional=False
    )

    assert result.result == "failed"
    assert result.error_code == "index_unrecognized"
