"""Locator-to-occurrence mapping and the keys that bind them.

A locator is a requested document; an occurrence is a catalog row for it.
Durable keys are derived from an accession plus a document path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.domain.document.models import (
    Cik,
    DocumentLocator,
    FilingOccurrence,
    derive_document_locator_key,
    derive_occurrence_id,
)
from edgar_sec.pipelines.document_storage.candidates import candidate_for
from edgar_sec.pipelines.document_storage.work_order import FilingWork


def document_key_of(occurrence: FilingOccurrence) -> str:
    """Return the content-addressed key an occurrence's document is stored under."""
    return derive_document_locator_key(
        str(occurrence.accession), occurrence.document_path
    )


def key_of(locator: DocumentLocator) -> str:
    """Return the content hash a locator's payload is stored under."""
    return derive_document_locator_key(str(locator.accession), locator.document_path)


def _unique_locators(
    locators: Sequence[DocumentLocator],
) -> list[DocumentLocator]:
    """Deduplicate locators by key, preserving order for stable rows."""
    seen: set[str] = set()
    unique: list[DocumentLocator] = []
    for locator in locators:
        if locator.document_locator_key in seen:
            continue
        seen.add(locator.document_locator_key)
        unique.append(locator)
    return unique


def _occurrences_by_key(
    occurrences: Sequence[FilingOccurrence],
) -> dict[str, list[FilingOccurrence]]:
    """Group provenance rows by the locator key they reference."""
    by_key: dict[str, list[FilingOccurrence]] = {}
    for occurrence in occurrences:
        by_key.setdefault(occurrence.doc_id, []).append(occurrence)
    return by_key


def _synthetic_occurrence(locator: DocumentLocator) -> FilingOccurrence:
    """Build the provenance row for a locator the catalog did not describe."""
    document_key = locator.document_locator_key
    return FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            locator.source_cik or "0",
            str(locator.accession),
            locator.document_path,
        ),
        source_cik=Cik.from_raw(locator.source_cik or "0"),
        accession=locator.accession,
        document_path=locator.document_path,
        form=locator.form or "",
        filing_date="",
        report_date=None,
        doc_id=document_key,
    )


def _expand_occurrences(
    locators: Sequence[DocumentLocator],
    by_key: Mapping[str, list[FilingOccurrence]],
) -> list[FilingOccurrence]:
    """Pair each locator with the provenance rows that reference it.

    An undescribed locator and a document that failed to process both still get a row.
    """
    expanded: list[FilingOccurrence] = []
    for locator in locators:
        matches = by_key.get(locator.document_locator_key)
        if not matches:
            matches = [_synthetic_occurrence(locator)]
        expanded.extend(matches)
    return expanded


def _filing_work(
    locator: DocumentLocator, by_key: Mapping[str, list[FilingOccurrence]]
) -> FilingWork:
    """Build one work record, so the candidate gate sees the catalog's filing date."""
    occurrences = by_key.get(locator.document_locator_key) or [
        _synthetic_occurrence(locator)
    ]
    filing_date, candidate = candidate_for(locator, occurrences)
    return FilingWork(
        locator=locator,
        occurrences=tuple(occurrences),
        filing_date=filing_date,
        candidate=candidate,
    )


__all__ = [
    "document_key_of",
    "key_of",
    "_expand_occurrences",
    "_filing_work",
    "_occurrences_by_key",
    "_synthetic_occurrence",
]
