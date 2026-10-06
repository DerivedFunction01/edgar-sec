"""Shared inventory records: S1 cohort projections and S3 parser outcomes.

These frozen, slotted dataclasses are the only inventory vocabulary that crosses a
stage boundary; pipeline readers and checkpoint code import them rather than
redefining them. Nothing here fetches, parses, or writes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Literal

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.serialization import canonical_json

__all__ = [
    "AccessionInventory",
    "AccessionSource",
    "CohortObservation",
    "InventoryCohort",
    "InventoryEntry",
    "IndexPageInput",
    "ParserDiagnostic",
    "ParserDiagnostics",
    "ParsedIndexPage",
    "UnrecognizedIndexPage",
    "IndexParseFailure",
    "IndexParseOutcome",
    "IndexWorkItem",
    "inventory_entry_id",
]


@dataclass(frozen=True, slots=True)
class CohortObservation:
    """One filing-cohort row projected to validated inventory values.

    Retained so provenance of each source contribution is auditable;
    projection collapses it into one work item per accession.
    """

    cohort_source_id: str
    accession: AccessionNumber
    source_cik: Cik
    form: str
    filing_date: date
    report_date: date | None


@dataclass(frozen=True, slots=True)
class AccessionInventory:
    """One row per canonical accession after filing-fact validation."""

    accession: AccessionNumber
    filing_cik: Cik
    source_ciks: tuple[Cik, ...]
    form: str
    filing_date: date
    report_date: date | None
    cohort_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccessionSource:
    """One row per unique (accession, source_cik) relationship."""

    accession: AccessionNumber
    source_cik: Cik
    first_seen_by: str


@dataclass(frozen=True, slots=True)
class IndexWorkItem:
    """One unit of physical work: observe one index page for one accession."""

    accession: AccessionNumber
    index_url: str


@dataclass(frozen=True, slots=True)
class InventoryCohort:
    """Projection of a catalog bundle or fixture to accession-level work."""

    observations: tuple[CohortObservation, ...]
    accessions: tuple[AccessionInventory, ...]
    sources: tuple[AccessionSource, ...]
    work_items: tuple[IndexWorkItem, ...]


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """One observed child-file row, excluding the full-submission envelope row."""

    entry_id: str
    accession: AccessionNumber
    table_kind: Literal["document_format", "data_file"]
    row_ordinal: int
    sequence: int | None
    document_type: str | None
    document_label: str | None
    description: str | None
    filename: str | None
    href: str | None
    archive_url: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class IndexPageInput:
    """One parsed index page: accession, source URL, and exact response bytes.

    The URL and exact bytes are inputs, not side effects.
    """

    accession: AccessionNumber
    source_url: str
    response_bytes: bytes


@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    """A finding the parser could not or would not resolve."""

    code: Literal[
        "unknown_table",
        "missing_column",
        "missing_sequence",
        "invalid_sequence",
        "duplicate_sequence",
        "out_of_order_sequence",
        "duplicate_filename",
        "invalid_size",
        "unsafe_href",
        "malformed_html",
        "unsupported_encoding",
    ]
    row_key: tuple[Literal["document_format", "data_file"], int] | None
    detail: str


@dataclass(frozen=True, slots=True)
class ParserDiagnostics:
    """Bounded diagnostics for a parse result."""

    items: tuple[ParserDiagnostic, ...]
    suppressed_count: int


@dataclass(frozen=True, slots=True)
class ParsedIndexPage:
    """A recognized and parsed ``-index.html`` page.

    ``entries`` preserves child-file rows; the complete-submission row is metadata.
    """

    accession: AccessionNumber
    source_url: str
    page_sha256: str
    entries: tuple[InventoryEntry, ...]
    bundle_url: str | None
    bundle_size: int | None
    xbrl_candidate_url: str | None
    diagnostics: ParserDiagnostics


@dataclass(frozen=True, slots=True)
class UnrecognizedIndexPage:
    """No recognized source table was found in the page.

    This is an intentional refusal state, distinct from a parsed page with zero
    entries.
    """

    accession: AccessionNumber
    source_url: str
    page_sha256: str
    diagnostics: ParserDiagnostics


@dataclass(frozen=True, slots=True)
class IndexParseFailure:
    """The page could not be decoded or parsed structurally."""

    accession: AccessionNumber
    source_url: str
    page_sha256: str
    diagnostic: ParserDiagnostic


IndexParseOutcome = ParsedIndexPage | UnrecognizedIndexPage | IndexParseFailure


def inventory_entry_id(
    accession: AccessionNumber,
    table_kind: str,
    row_ordinal: int,
    index_sha256: str,
) -> str:
    """Deterministic entry identity: SHA-256 of canonical JSON for the four fields."""
    payload = [str(accession), table_kind, row_ordinal, index_sha256]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
