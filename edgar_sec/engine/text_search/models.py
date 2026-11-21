"""Result and scope types for text search over acquired holdings."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Coverage",
    "SearchHit",
    "SearchResult",
    "SearchScope",
    "TargetVerdict",
]


@dataclass(frozen=True, slots=True)
class SearchScope:
    """Caller filters; attachment scope is explicit, never silently primary."""

    accessions: tuple[str, ...] = ()
    ciks: tuple[int, ...] = ()
    forms: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    attachment_scope: str = "all_documents"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One chunk-level hit with its document identity and excerpt."""

    accession: str
    filename: str
    logical_document_id: str | None
    document_role: str | None
    section_name: str | None
    note_label: str | None
    start_line: int
    end_line: int
    excerpt: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class TargetVerdict:
    """Whether one caller-named target is in the indexed corpus at all."""

    target: str
    covered: bool


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the search actually ran over, stated on every result."""

    index_present: bool
    source_snapshot_id: str | None
    built_at: str | None
    accessions_searched: int
    documents_searched: int
    chunks_searched: int
    targets: tuple[TargetVerdict, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Hits plus coverage; an absent target is never a plain no-match."""

    query: str
    mode: str
    hits: tuple[SearchHit, ...]
    coverage: Coverage
    not_in_corpus: tuple[str, ...] = field(default_factory=tuple)
