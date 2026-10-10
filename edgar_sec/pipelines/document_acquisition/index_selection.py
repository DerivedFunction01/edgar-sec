from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from edgar_sec.domain.document_inventory.models import (
    IndexParseOutcome,
    InventoryEntry,
    ParsedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url


@dataclass(frozen=True, slots=True)
class IndexSelection:
    result: Literal["selected", "not_filed", "required_missing", "ambiguous", "failed"]
    matching_entry_ids: tuple[str, ...]
    entry: InventoryEntry | None
    error_code: str | None
    retrieval_mode: Literal["direct_url", "bundle_sequence"] | None = None
    selected_url: str | None = None


def select_index_entry(
    outcome: IndexParseOutcome,
    *,
    accession: AccessionNumber,
    expected_form: str,
    optional: bool,
) -> IndexSelection:
    if not isinstance(outcome, ParsedIndexPage):
        return IndexSelection("failed", (), None, "index_unrecognized")
    if outcome.accession != accession:
        return IndexSelection("failed", (), None, "index_scope_mismatch")
    try:
        source_archive = validate_archive_url(outcome.source_url, accession)
    except ValueError:
        return IndexSelection("failed", (), None, "index_scope_mismatch")
    if source_archive.document_path != f"{accession}-index.html":
        return IndexSelection("failed", (), None, "index_scope_mismatch")

    matching = tuple(
        entry
        for entry in outcome.entries
        if entry.accession == accession
        and entry.table_kind == "document_format"
        and entry.document_type is not None
        and entry.document_type.strip().casefold() == expected_form.strip().casefold()
    )
    entry_ids = tuple(entry.entry_id for entry in matching)
    if not matching:
        return IndexSelection(
            "not_filed" if optional else "required_missing", (), None, None
        )
    if len(matching) > 1:
        return IndexSelection("ambiguous", entry_ids, None, None)

    selected = matching[0]
    if selected.archive_url:
        try:
            validate_archive_url(
                selected.archive_url,
                accession,
                expected_archive_cik=source_archive.archive_cik,
            )
        except ValueError:
            return IndexSelection(
                "failed", entry_ids, None, "index_entry_unaddressable"
            )
        return IndexSelection(
            "selected", entry_ids, selected, None, "direct_url", selected.archive_url
        )
    if selected.sequence is None or not outcome.bundle_url:
        return IndexSelection("failed", entry_ids, None, "index_entry_unaddressable")
    try:
        archive = validate_archive_url(
            outcome.bundle_url,
            accession,
            expected_archive_cik=source_archive.archive_cik,
        )
    except ValueError:
        return IndexSelection("failed", entry_ids, None, "index_entry_unaddressable")
    if archive.document_path != f"{accession}.txt":
        return IndexSelection("failed", entry_ids, None, "index_entry_unaddressable")
    return IndexSelection(
        "selected", entry_ids, selected, None, "bundle_sequence", outcome.bundle_url
    )


__all__ = ["IndexSelection", "select_index_entry"]
