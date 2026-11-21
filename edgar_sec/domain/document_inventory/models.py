"""Shared inventory records: cohort projections and parser outcomes.

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
    "EnumeratedDocuments",
    "EnumerationFailure",
    "EnumerationInput",
    "EnumerationOutcome",
    "InventoryCohort",
    "InventoryEntry",
    "IndexPageInput",
    "ParserDiagnostic",
    "ParserDiagnostics",
    "ParsedIndexPage",
    "UnrecognizedEnumeration",
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
    is_xbrl: bool = False
    is_inline_xbrl: bool = False
    primary_document: str | None = None
    archive_url: str | None = None


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
    """One unit of physical work: observe one accession by its routed vehicle.

    ``vehicle`` is ``summary`` for catalog-flagged XBRL filings and ``index``
    otherwise; the routing fields carry the catalog facts enumeration needs.
    """

    accession: AccessionNumber
    index_url: str
    vehicle: Literal["index", "summary"] = "index"
    archive_cik: str | None = None
    primary_document: str | None = None
    is_inline_xbrl: bool = False
    form: str | None = None


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
        "malformed_json",
        "malformed_xml",
        "malformed_package",
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


@dataclass(frozen=True, slots=True)
class EnumerationInput:
    """One fetched enumeration vehicle: identity, catalog facts, exact bytes.

    The catalog facts are inputs because the vehicles do not all carry them;
    the primary entry and inline extracted instance are synthesized from them.
    """

    accession: AccessionNumber
    source_url: str
    response_bytes: bytes
    archive_cik: str
    form: str
    primary_document: str
    is_inline_xbrl: bool


@dataclass(frozen=True, slots=True)
class EnumeratedDocuments:
    """A recognized vehicle listing synthesized into inventory entries.

    ``bundle_url`` is constructed, not observed: it is a candidate like the
    index parser's constructed package row, never proof of existence.
    """

    accession: AccessionNumber
    source_url: str
    vehicle: Literal["summary", "package"]
    page_sha256: str
    entries: tuple[InventoryEntry, ...]
    bundle_url: str | None
    diagnostics: ParserDiagnostics


@dataclass(frozen=True, slots=True)
class UnrecognizedEnumeration:
    """The summary parsed but carries no InputFiles section.

    This is an intentional refusal state, distinct from an enumerated listing
    with zero entries.
    """

    accession: AccessionNumber
    source_url: str
    vehicle: Literal["summary", "package"]
    page_sha256: str
    diagnostics: ParserDiagnostics


@dataclass(frozen=True, slots=True)
class EnumerationFailure:
    """The vehicle payload could not be decoded or read structurally."""

    accession: AccessionNumber
    source_url: str
    vehicle: Literal["summary", "package"]
    page_sha256: str
    diagnostic: ParserDiagnostic


EnumerationOutcome = EnumeratedDocuments | UnrecognizedEnumeration | EnumerationFailure


def inventory_entry_id(
    accession: AccessionNumber,
    table_kind: str,
    row_ordinal: int,
    index_sha256: str,
) -> str:
    """Deterministic entry identity: SHA-256 of canonical JSON for the four fields."""
    payload = [str(accession), table_kind, row_ordinal, index_sha256]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
