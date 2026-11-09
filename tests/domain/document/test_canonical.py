"""Tests for the canonical attachment row and role derivation."""

from __future__ import annotations

from edgar_sec.domain.document.aggregate import is_exhibit_attachment
from edgar_sec.domain.document.canonical import (
    CanonicalAttachmentRow,
    attachment_role,
)
from edgar_sec.domain.document_inventory.models import InventoryEntry
from edgar_sec.domain.identity import AccessionNumber


def _entry(**overrides) -> InventoryEntry:
    fields = {
        "entry_id": "entry-abc",
        "accession": AccessionNumber.from_any("0000320193-23-000106"),
        "table_kind": "document_format",
        "row_ordinal": 1,
        "sequence": 2,
        "document_type": "EX-21",
        "document_label": None,
        "description": "SUBSIDIARIES",
        "filename": "ex21.htm",
        "href": "ex21.htm",
        "archive_url": "https://www.sec.gov/Archives/edgar/data/320193/ex21.htm",
        "byte_size": 45020,
    }
    fields.update(overrides)
    return InventoryEntry(**fields)


def test_row_projects_entry_identity() -> None:
    row = CanonicalAttachmentRow.from_inventory_entry(_entry())
    assert row.entry_id == "entry-abc"
    assert row.accession == "0000320193-23-000106"
    assert row.table_kind == "document_format"
    assert row.sequence == 2
    assert row.document_type == "EX-21"
    assert row.byte_size == 45020


def test_to_attachment_carries_canonical_identity() -> None:
    row = CanonicalAttachmentRow.from_inventory_entry(_entry())
    att = row.to_attachment(form="10-K")
    assert att.attachment_id == "entry-abc"
    assert att.entry_id == "entry-abc"
    assert att.sequence == 2
    assert att.table_kind == "document_format"
    assert att.role == "exhibit"
    assert att.size == 45020
    assert att.sha256 is None


def test_unsequenced_entry_serves_none_sequence_and_type() -> None:
    entry = _entry(sequence=None, document_type=None, description=None)
    row = CanonicalAttachmentRow.from_inventory_entry(entry)
    att = row.to_attachment(form="10-K")
    assert row.sequence is None
    assert row.document_type is None
    assert att.sequence is None
    assert att.document_type == ""
    assert att.role is None


def test_attachment_role_matrix() -> None:
    assert attachment_role("document_format", "10-K", form="10-K") == "primary"
    assert attachment_role("document_format", "10KSB", form="10-K") == "primary"
    assert attachment_role("document_format", "EX-21", form="10-K") == "exhibit"
    assert attachment_role("data_file", "EX-101.INS", form="10-K") == "data_file"
    assert attachment_role("data_file", "10-K", form="10-K") == "data_file"
    assert attachment_role("document_format", "GRAPHIC", form="10-K") == "graphic"
    assert attachment_role("document_format", "8-K", form="10-K") is None
    assert attachment_role(None, "EX-99.1", form="10-K") == "exhibit"
    assert attachment_role(None, None, form="10-K") is None


def test_is_exhibit_attachment_derivation() -> None:
    assert is_exhibit_attachment("EX-21", "doc.htm") is True
    assert is_exhibit_attachment("10-K", "ex99.htm") is True
    assert is_exhibit_attachment("", "exhibit10.htm") is True
    assert is_exhibit_attachment("10-K", "aapl_ex21.htm") is False
    assert is_exhibit_attachment("10-K", "report.htm") is False
