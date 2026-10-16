"""Data models for structural section and note sequence analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CandidateKind(StrEnum):
    """Classification of a raw structural candidate heading."""

    STANDARD = "standard"
    GROUPED = "grouped"
    NUMERIC = "numeric"
    TITLE_ONLY = "title_only"


@dataclass(frozen=True, slots=True)
class SectionCandidate:
    """Raw structural section candidate extracted from document lines."""

    line_number: int
    raw_text: str
    kind: CandidateKind
    identifiers: tuple[str, ...]
    title: str = ""
    part: int | None = None
    is_omitted: bool = False
    preceded_by_continuation: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedSection:
    """Validated structural section bounded by document line coordinates."""

    item_identifier: str
    start_line: int
    end_line: int | None
    title: str
    raw_heading: str
    kind: CandidateKind
    confidence: float
    is_omitted: bool = False
    grouped_with: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SectionSequence:
    """Document-level sequence of resolved statutory Part/Item sections."""

    family: str
    sections: tuple[ResolvedSection, ...]
    missing_items: tuple[str, ...] = ()
    anachronistic_rejections: int = 0
    non_contiguous_rejections: int = 0
    payload_sha256: str | None = None
    representation_id: str | None = None
    renderer_version: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedNote:
    """Validated financial statement footnote bounded by document coordinates."""

    note_number: int
    note_label: str
    start_line: int
    end_line: int | None
    title: str
    raw_heading: str
    confidence: float
    grouped_with: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class NotesSequence:
    """Document-level sequence of financial statement footnotes."""

    notes: tuple[ResolvedNote, ...]
    anachronistic_rejections: int = 0
    non_contiguous_rejections: int = 0
    payload_sha256: str | None = None
    representation_id: str | None = None
    renderer_version: str | None = None
