from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogOccurrence,
    CatalogScopeAccession,
)
from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    catalog_only_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget


def _occurrence(url: str) -> CatalogOccurrence:
    return CatalogOccurrence(
        occurrence_id="occ-1",
        document_locator_key="locator-1",
        source_cik="1",
        primary_document="primary.htm",
        document_path="primary.htm",
        archive_url=url,
        document_path_source="primary_document",
        reported_size=10,
        is_xbrl=True,
        is_inline_xbrl=False,
        is_xbrl_numeric=True,
    )


def _scope(url: str) -> CatalogScopeAccession:
    return CatalogScopeAccession(
        "000000000124000001",
        "10-K",
        "2024-01-02",
        (_occurrence(url),),
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
