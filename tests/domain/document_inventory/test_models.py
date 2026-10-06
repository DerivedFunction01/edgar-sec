"""Tests for inventory-domain model identity contracts."""

import hashlib
import json

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document_inventory.models import inventory_entry_id


def test_inventory_entry_id_matches_canonical_fields() -> None:
    accession = AccessionNumber("0000320193-23-000106")
    digest = "a" * 64
    expected = hashlib.sha256(
        json.dumps(
            [str(accession), "document_format", 0, digest],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()

    assert inventory_entry_id(accession, "document_format", 0, digest) == expected


def test_inventory_entry_id_is_stable_and_input_sensitive() -> None:
    accession = AccessionNumber("0000320193-23-000106")
    base = inventory_entry_id(accession, "document_format", 0, "d" * 64)
    variants = {
        inventory_entry_id(accession, "data_file", 0, "d" * 64),
        inventory_entry_id(accession, "document_format", 1, "d" * 64),
        inventory_entry_id(accession, "document_format", 0, "e" * 64),
    }

    assert base == inventory_entry_id(accession, "document_format", 0, "d" * 64)
    assert len(base) == 64
    assert base not in variants


def test_inventory_entry_id_normalizes_accession() -> None:
    hyphenated = AccessionNumber("0000320193-23-000106")
    compact = AccessionNumber.from_any("000032019323000106")

    assert inventory_entry_id(hyphenated, "document_format", 0, "d" * 64) == (
        inventory_entry_id(compact, "document_format", 0, "d" * 64)
    )
