"""S3 parser contract for the document_inventory pipeline.

Typed input/output for parsing an EDGAR ``-index.html`` response
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from edgar_sec.domain.identity import AccessionNumber

from .cohort import InventoryEntry

__all__ = [
    "IndexPageInput",
    "ParserDiagnostic",
    "ParserDiagnostics",
    "ParsedIndexPage",
    "UnrecognizedIndexPage",
    "IndexParseFailure",
    "IndexParseOutcome",
    "parse_html_index",
]


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

    ``entries`` contains one row per body row of every recognized source table; a
    recognized but empty table yields zero entries rather than ``UnrecognizedIndexPage``.
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


def parse_html_index(page: IndexPageInput) -> IndexParseOutcome:
    """Parse a raw ``-index.html`` response.

    Not implemented.
    """
    raise NotImplementedError("parse_html_index is not implemented")
