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


def test_enumeration_outcome_union_has_three_states() -> None:
    import typing

    from edgar_sec.domain.document_inventory.models import (
        EnumeratedDocuments,
        EnumerationFailure,
        EnumerationOutcome,
        UnrecognizedEnumeration,
    )

    assert set(typing.get_args(EnumerationOutcome)) == {
        EnumeratedDocuments,
        UnrecognizedEnumeration,
        EnumerationFailure,
    }


def test_enumerated_documents_carry_entries_and_constructed_bundle() -> None:
    from edgar_sec.domain.document_inventory.models import (
        EnumeratedDocuments,
        EnumerationInput,
        ParserDiagnostics,
    )

    accession = AccessionNumber("0000320193-23-000106")
    document = EnumerationInput(
        accession=accession,
        source_url="https://www.sec.gov/Archives/edgar/data/320193/FilingSummary.xml",
        response_bytes=b"<FilingSummary/>",
        archive_cik="320193",
        form="10-K",
        primary_document="aapl-20230930.htm",
        is_inline_xbrl=True,
    )
    page = EnumeratedDocuments(
        accession=document.accession,
        source_url=document.source_url,
        vehicle="summary",
        page_sha256="d" * 64,
        entries=(),
        bundle_url="https://www.sec.gov/Archives/edgar/data/320193/bundle.txt",
        diagnostics=ParserDiagnostics((), 0),
    )

    assert page.entries == ()
    assert page.bundle_url is not None
    assert document.is_inline_xbrl is True
