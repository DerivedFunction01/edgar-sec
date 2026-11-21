from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    _entry_candidate,
    inventory_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

from tests.pipelines.document_planning.matching_support import (
    _ACCESSION,
    _ARCHIVE_ROOT,
    _BUNDLE_URL,
    _inventory_row,
)


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
