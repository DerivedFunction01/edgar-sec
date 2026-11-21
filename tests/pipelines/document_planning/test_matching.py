from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.catalog_scope import (
    CatalogScopeAccession,
)
from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    _filing_year,
    _is_placeholder_primary_path,
    catalog_only_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

from tests.pipelines.document_planning.matching_support import (
    _ACCESSION,
    _ARCHIVE_ROOT,
    _occurrence,
    _scope,
)


def test_filing_year_is_range_ruled() -> None:
    """Delta pin: the filing-year recognizer is the homed token;
    the deleted private copy accepted any leading 4 digits."""
    assert _filing_year("2023-05-01") == 2023
    assert _filing_year("1899-05-01") is None
    assert _filing_year(None) is None


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


def test_catalog_primary_cofilres_sharing_same_path_reconciles_to_single_url() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    scope = CatalogScopeAccession(
        "000000000124000001",
        "3",
        "2024-01-02",
        (
            _occurrence(None, source_cik="20", primary_document="doc.xml"),
            _occurrence(None, source_cik="10", primary_document="doc.xml"),
        ),
    )

    rows = catalog_only_rows("plan-1", scope, (target,))

    assert len(rows) == 1
    assert rows[0]["status"] == "matched"
    assert rows[0]["target_url"] == (
        "https://www.sec.gov/Archives/edgar/data/10/000000000124000001/doc.xml"
    )


def test_catalog_primary_cofilres_conflicting_paths_raises_matching_error() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    scope = CatalogScopeAccession(
        "000000000124000001",
        "3",
        "2024-01-02",
        (
            _occurrence(None, source_cik="10", primary_document="doc1.xml"),
            _occurrence(None, source_cik="20", primary_document="doc2.xml"),
        ),
    )

    with pytest.raises(TargetMatchingError, match="conflicting catalog primary paths"):
        catalog_only_rows("plan-1", scope, (target,))


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


def test_catalog_zero_primary_is_ignored_as_no_primary() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    rows = catalog_only_rows(
        "plan-1",
        _scope(None, primary_document="0000.htm"),
        (target,),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["target_url"] is None
    assert rows[0]["status_reason"] == "no_usable_primary_path"
