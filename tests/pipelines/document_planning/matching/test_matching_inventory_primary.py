from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.matching import (
    TargetMatchingError,
    inventory_rows,
)
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

from tests.pipelines.document_planning.matching.matching_support import (
    _ACCESSION,
    _ARCHIVE_ROOT,
    _BUNDLE_URL,
    _inventory_row,
    _placeholder_entry,
)


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
