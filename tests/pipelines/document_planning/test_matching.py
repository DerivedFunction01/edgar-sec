from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogOccurrence,
    CatalogScopeAccession,
)
from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    _entry_candidate,
    catalog_only_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget


def _occurrence(url: str | None, *, source_cik: str = "1") -> CatalogOccurrence:
    return CatalogOccurrence(
        occurrence_id="occ-1",
        document_locator_key="locator-1",
        source_cik=source_cik,
        primary_document="primary.htm",
        document_path="primary.htm",
        archive_url=url,
        document_path_source="primary_document",
        reported_size=10,
        is_xbrl=True,
        is_inline_xbrl=False,
        is_xbrl_numeric=True,
    )


def _scope(url: str | None, *, source_cik: str = "1") -> CatalogScopeAccession:
    return CatalogScopeAccession(
        "000000000124000001",
        "10-K",
        "2024-01-02",
        (_occurrence(url, source_cik=source_cik),),
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


def test_inventory_locator_uses_index_archive_cik_not_filing_cik() -> None:
    accession = "0000950134-01-500666"
    index_url = (
        "https://www.sec.gov/Archives/edgar/data/4515/"
        "000095013401500666/0000950134-01-500666-index.html"
    )
    target_url = (
        "https://www.sec.gov/Archives/edgar/data/4515/"
        "000095013401500666/d86404e10-q.txt"
    )
    candidate = _entry_candidate(
        {"entry_id": "entry-1", "archive_url": target_url},
        {
            "filing_cik": "0000950134",
            "index_url": index_url,
        },
        accession,
        ProfileTarget("primary", "primary", False, "primary:primary"),
    )

    assert candidate.target_url == target_url
