from __future__ import annotations

import re

import pytest

from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogOccurrence,
    CatalogScopeAccession,
)
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    InventoryEvidenceRow,
)
from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    _entry_candidate,
    _is_placeholder_primary_path,
    catalog_only_rows,
    inventory_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

# Source example: https://www.sec.gov/Archives/edgar/data/898015/000089968100000405/0000899681-00-000405-index.html
_ACCESSION = "0000899681-00-000405"
_ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data/898015/000089968100000405"
_INDEX_URL = f"{_ARCHIVE_ROOT}/{_ACCESSION}-index.html"
_BUNDLE_URL = f"{_ARCHIVE_ROOT}/{_ACCESSION}.txt"


@pytest.mark.parametrize(
    "path", ["0001.txt", "0001.htm", "0000.txt", "0000.htm", "/0001.htm"]
)
def test_placeholder_primary_path_signals(path: str) -> None:
    assert _is_placeholder_primary_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "0000320193-20-000001.txt",
        "documents/0000320193-20-000001.txt",
        "nested/0001.htm",
        "0001.HTM",
        "a10-k.htm",
        None,
    ],
)
def test_non_placeholder_paths_do_not_signal(path: str | None) -> None:
    assert not _is_placeholder_primary_path(path)


def _occurrence(
    url: str | None,
    *,
    source_cik: str = "1",
    primary_document: str = "primary.htm",
) -> CatalogOccurrence:
    return CatalogOccurrence(
        occurrence_id="occ-1",
        document_locator_key="locator-1",
        source_cik=source_cik,
        primary_document=primary_document,
        document_path=primary_document,
        archive_url=url,
        document_path_source="primary_document",
        reported_size=10,
        is_xbrl=True,
        is_inline_xbrl=False,
        is_xbrl_numeric=True,
    )


def _scope(
    url: str | None,
    *,
    source_cik: str = "1",
    primary_document: str = "primary.htm",
    accession: str = "000000000124000001",
) -> CatalogScopeAccession:
    return CatalogScopeAccession(
        accession,
        "10-K",
        "2024-01-02",
        (
            _occurrence(
                url,
                source_cik=source_cik,
                primary_document=primary_document,
            ),
        ),
    )


def test_catalog_primary_locator_becomes_direct_target() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/primary.htm"
        ),
        (target,),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "direct_url"


def test_catalog_primary_url_outside_accession_is_refused() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")

    with pytest.raises(TargetMatchingError, match="outside accession"):
        catalog_only_rows(
            "plan-1",
            _scope(
                "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/primary.htm"
            ),
            (target,),
        )


def test_catalog_primary_url_uses_cofiler_cik_not_accession_prefix() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    url = "https://www.sec.gov/Archives/edgar/data/4515/000000000124000001/primary.htm"

    rows = catalog_only_rows("plan-1", _scope(url, source_cik="2"), (target,))

    assert rows[0]["target_url"] == url


def test_catalog_primary_fallback_uses_source_cik() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")

    rows = catalog_only_rows("plan-1", _scope(None, source_cik="2"), (target,))

    assert rows[0]["target_url"] == (
        "https://www.sec.gov/Archives/edgar/data/2/000000000124000001/primary.htm"
    )


@pytest.mark.parametrize(
    "filename",
    ["0001.txt", "0002.txt", "0004.pdf", "0007.htm", "0026.htm"],
)
def test_catalog_numbered_primary_constructs_accession_prefixed_child(
    filename: str,
) -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            None, source_cik="898015", primary_document=filename, accession=_ACCESSION
        ),
        (target,),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == f"{_ARCHIVE_ROOT}/{_ACCESSION}-{filename}"


def test_catalog_numbered_primary_accepts_observed_accession_prefixed_archive_url() -> (
    None
):
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    url = f"{_ARCHIVE_ROOT}/{_ACCESSION}-0001.txt"
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            url,
            source_cik="898015",
            primary_document="0001.txt",
            accession=_ACCESSION,
        ),
        (target,),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == url


def test_non_sequence_numeric_primary_keeps_its_observed_path() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    url = f"{_ARCHIVE_ROOT}/00049371.TXT"
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            url,
            source_cik="898015",
            primary_document="00049371.TXT",
            accession=_ACCESSION,
        ),
        (target,),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == url


def test_catalog_stub_primary_is_unresolved_without_sequence_evidence() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    rows = catalog_only_rows(
        "plan-1",
        _scope(None, primary_document="0000.htm"),
        (target,),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["target_url"] is None
    assert rows[0]["status_reason"] == "placeholder_primary_requires_bundle_sequence"


def test_catalog_stub_link_is_not_selected_without_sequence_evidence() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    placeholder_url = f"{_ARCHIVE_ROOT}/{_ACCESSION}-0000.htm"
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            placeholder_url,
            source_cik="898015",
            primary_document="0000.htm",
            accession=_ACCESSION,
        ),
        (target,),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["target_url"] is None


def _inventory_row(
    entry: dict[str, object], *, bundle_url: str | None = None
) -> InventoryEvidenceRow:
    return InventoryEvidenceRow(
        accession=_ACCESSION,
        catalog_form="10-Q",
        catalog_filing_date="2000-11-14",
        indexed=True,
        accession_row={
            "bundle_url": bundle_url,
            "bundle_size": 67488,
            "filing_cik": "1",
            "index_url": _INDEX_URL,
        },
        entry_row=entry,
    )


def _placeholder_entry(
    *, sequence: object = 1, filename: str = "0001.htm", entry_id: str = "entry-1"
) -> dict[str, object]:
    archive_filename = (
        f"{_ACCESSION}-{filename}"
        if re.fullmatch(r"\d{4}\.[A-Za-z0-9]+", filename, re.ASCII)
        else filename
    )
    return {
        "entry_id": entry_id,
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": filename,
        "archive_url": f"{_ARCHIVE_ROOT}/{archive_filename}",
        "sequence": sequence,
        "byte_size": 63833,
    }


@pytest.mark.parametrize("filename", ["0001.txt", "0001.htm"])
def test_numbered_primary_uses_accession_prefixed_observed_child(filename: str) -> None:
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(_placeholder_entry(filename=filename), bundle_url=_BUNDLE_URL)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "direct_url"
    assert rows[0]["target_url"] == f"{_ARCHIVE_ROOT}/{_ACCESSION}-{filename}"
    assert rows[0]["sequence"] is None


@pytest.mark.parametrize("filename", ["0000.txt", "0000.htm"])
def test_zero_primary_stub_uses_observed_sequence_and_pinned_bundle(
    filename: str,
) -> None:
    bundle_url = _BUNDLE_URL
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(_placeholder_entry(filename=filename), bundle_url=bundle_url)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "bundle_sequence"
    assert rows[0]["target_url"] == bundle_url
    assert rows[0]["sequence"] == 1
    assert rows[0]["byte_size"] == 63833


@pytest.mark.parametrize(
    ("sequence", "bundle_url", "reason"),
    [
        (
            None,
            _BUNDLE_URL,
            "placeholder_primary_missing_positive_sequence",
        ),
        (1, None, "placeholder_primary_missing_bundle_url"),
        (
            0,
            _BUNDLE_URL,
            "placeholder_primary_missing_positive_sequence",
        ),
    ],
)
def test_stub_primary_without_bundle_evidence_stays_unresolved(
    sequence: object, bundle_url: str | None, reason: str
) -> None:
    rows = inventory_rows(
        "plan-1",
        [
            _inventory_row(
                _placeholder_entry(sequence=sequence, filename="0000.htm"),
                bundle_url=bundle_url,
            )
        ],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["target_url"] is None
    assert rows[0]["status_reason"] == reason


@pytest.mark.parametrize(
    "filename",
    ["nested/0001.htm", f"{_ACCESSION}.txt", "a10-k.htm"],
)
def test_non_exact_primary_name_retains_direct_link_behavior(filename: str) -> None:
    entry = _placeholder_entry(filename=filename)
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "direct_url"


def test_ix_viewer_href_matches_its_safe_archive_url() -> None:
    archive_url = f"{_ARCHIVE_ROOT}/primary.htm"
    entry = {
        "entry_id": "entry-inline-primary",
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": "primary.htm",
        "href": "/ix?doc=/Archives/edgar/data/898015/000089968100000405/primary.htm",
        "archive_url": archive_url,
        "sequence": 1,
        "byte_size": 2000,
    }

    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == archive_url


def test_relative_inventory_href_uses_index_url_without_bundle() -> None:
    archive_url = f"{_ARCHIVE_ROOT}/primary.htm"
    entry = {
        "entry_id": "entry-relative-primary",
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": "primary.htm",
        "href": "/Archives/edgar/data/898015/000089968100000405/primary.htm",
        "archive_url": None,
        "sequence": 1,
        "byte_size": 2000,
    }

    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == archive_url


def test_relative_inventory_href_allows_archive_cik_different_from_index() -> None:
    entry = {
        "entry_id": "entry-wrong-cik-primary",
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": "primary.htm",
        "href": "/Archives/edgar/data/1307496/000089968100000405/primary.htm",
        "archive_url": None,
        "sequence": 1,
        "byte_size": 2000,
    }

    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry)],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == (
        "https://www.sec.gov/Archives/edgar/data/1307496/000089968100000405/primary.htm"
    )


def test_external_ix_viewer_cannot_redirect_to_an_archive_url() -> None:
    archive_url = f"{_ARCHIVE_ROOT}/primary.htm"
    entry = {
        "entry_id": "entry-external-inline-primary",
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": "primary.htm",
        "href": f"https://example.com/ix?doc={archive_url}",
        "archive_url": archive_url,
        "sequence": 1,
        "byte_size": 2000,
    }

    with pytest.raises(TargetMatchingError, match="unsafe SEC archive URL"):
        inventory_rows(
            "plan-1",
            [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
            (ProfileTarget("primary", "primary", False, "primary:primary"),),
        )


def test_duplicate_stub_primary_evidence_is_ambiguous() -> None:
    bundle_url = _BUNDLE_URL
    rows = inventory_rows(
        "plan-1",
        [
            _inventory_row(_placeholder_entry(), bundle_url=bundle_url),
            _inventory_row(
                _placeholder_entry(entry_id="entry-2", sequence=2),
                bundle_url=bundle_url,
            ),
        ],
        (ProfileTarget("primary", "primary", False, "primary:primary"),),
    )

    assert [row["status"] for row in rows] == ["ambiguous", "ambiguous"]


def test_exhibit_keeps_the_index_href_when_primary_name_is_a_stub() -> None:
    exhibit_url = f"{_ARCHIVE_ROOT}/{_ACCESSION}-0002.txt"
    exhibit = {
        "entry_id": "exhibit-27",
        "table_kind": "document_format",
        "document_type": "EX-27",
        "filename": "0002.txt",
        "archive_url": exhibit_url,
        "sequence": 2,
        "byte_size": 2077,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(exhibit, bundle_url=_BUNDLE_URL)],
        (ProfileTarget("exhibit", "EX-27", True, "exhibit:EX-27"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "direct_url"
    assert rows[0]["target_url"] == exhibit_url
    assert rows[0]["sequence"] is None


def test_numbered_exhibit_without_accession_prefix_uses_bundle_sequence() -> None:
    entry = {
        "entry_id": "entry-2",
        "table_kind": "document_format",
        "document_type": "EX-10",
        "filename": "0002.txt",
        "href": "0002.txt",
        "archive_url": f"{_ARCHIVE_ROOT}/0002.txt",
        "sequence": 2,
        "byte_size": 2000,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
        (ProfileTarget("exhibit", "EX-10", True, "exhibit:EX-10"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "bundle_sequence"
    assert rows[0]["target_url"] == _BUNDLE_URL
    assert rows[0]["sequence"] == 2


@pytest.mark.parametrize(
    ("sequence", "extension"),
    [(number, "txt") for number in range(2, 27)] + [(4, "pdf")],
)
def test_numbered_exhibits_keep_the_observed_child_link(
    sequence: int, extension: str
) -> None:
    filename = f"{sequence:04d}.{extension}"
    accession_filename = f"{_ACCESSION}-{filename}"
    observed_url = f"{_ARCHIVE_ROOT}/{accession_filename}"
    entry = {
        "entry_id": f"entry-{sequence}",
        "table_kind": "document_format",
        "document_type": "EX-10",
        "filename": filename,
        "href": f"/Archives/edgar/data/898015/000089968100000405/{accession_filename}",
        "archive_url": observed_url,
        "sequence": sequence,
        "byte_size": 2000,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
        (ProfileTarget("exhibit", "EX-10", True, f"exhibit:{sequence}"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "direct_url"
    assert rows[0]["target_url"] == observed_url
    assert rows[0]["sequence"] is None


def test_directory_only_href_uses_advertised_bundle_and_observed_sequence() -> None:
    entry = {
        "entry_id": "entry-directory",
        "table_kind": "document_format",
        "document_type": "EX-10",
        "filename": None,
        "href": "/Archives/edgar/data/898015/",
        "archive_url": None,
        "sequence": 2,
        "byte_size": 2000,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
        (ProfileTarget("exhibit", "EX-10", True, "exhibit:EX-10"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "bundle_sequence"
    assert rows[0]["target_url"] == _BUNDLE_URL
    assert rows[0]["sequence"] == 2


def test_directory_only_href_without_bundle_stays_unresolved() -> None:
    entry = {
        "entry_id": "entry-directory",
        "table_kind": "document_format",
        "document_type": "EX-10",
        "filename": None,
        "href": "/Archives/edgar/data/898015/",
        "archive_url": None,
        "sequence": 2,
        "byte_size": 2000,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry)],
        (ProfileTarget("exhibit", "EX-10", True, "exhibit:EX-10"),),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["status_reason"] == "no_usable_retrieval_locator"
    assert rows[0]["target_url"] is None


def test_directory_only_primary_does_not_widen_placeholder_policy() -> None:
    entry = {
        "entry_id": "entry-primary-directory",
        "table_kind": "document_format",
        "document_type": "10-Q",
        "filename": None,
        "href": "/Archives/edgar/data/898015/",
        "archive_url": None,
        "sequence": 1,
        "byte_size": 2000,
    }
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
        (ProfileTarget("primary", "10-Q", True, "primary"),),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["status_reason"] == "no_usable_retrieval_locator"
    assert rows[0]["target_url"] is None


def test_directory_only_href_does_not_enable_external_href_fallback() -> None:
    entry = {
        "entry_id": "entry-external",
        "table_kind": "document_format",
        "document_type": "EX-10",
        "filename": None,
        "href": "https://example.com/Archives/edgar/data/898015/",
        "archive_url": None,
        "sequence": 2,
        "byte_size": 2000,
    }

    with pytest.raises(TargetMatchingError, match="unsafe SEC archive URL"):
        inventory_rows(
            "plan-1",
            [_inventory_row(entry, bundle_url=_BUNDLE_URL)],
            (ProfileTarget("exhibit", "EX-10", True, "exhibit:EX-10"),),
        )


def test_inventory_locator_cik_can_differ_from_index_and_accession_prefix() -> None:
    accession = "0000902664-25-004119"
    index_url = (
        "https://www.sec.gov/Archives/edgar/data/1337634/"
        "000090266425004119/0000902664-25-004119-index.html"
    )
    target_url = (
        "https://www.sec.gov/Archives/edgar/data/1307496/"
        "000090266425004119/ownership.xml"
    )
    candidate = _entry_candidate(
        {"entry_id": "entry-1", "archive_url": target_url},
        {
            "filing_cik": "0000902664",
            "index_url": index_url,
        },
        accession,
        ProfileTarget("primary", "primary", False, "primary:primary"),
    )

    assert candidate.target_url == target_url
