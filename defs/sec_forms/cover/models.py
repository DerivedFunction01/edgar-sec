"""Shared immutable data models and enums for cover and body boundary detection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BoundarySignal(StrEnum):
    """Evidence capabilities that a cover profile may enable."""

    COVER_IDENTITY_AND_LAYOUT = "cover_identity_and_layout"
    PAGE_MARKERS = "page_markers"
    INCORPORATED_REFERENCE = "incorporated_reference"
    TOC_TRANSITION = "toc_transition"
    PART_FALLBACK = "part_fallback"
    ITEM_FALLBACK = "item_fallback"


class BodyAnchorType(StrEnum):
    """How a body-start anchor was selected."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    SUBSTANTIVE = "substantive"
    UNKNOWN = "unknown"


class BoundaryMethod(StrEnum):
    """How a cover boundary was selected."""

    DISABLED = "disabled"
    MARKER = "marker"
    STRUCTURAL = "structural"
    PHRASE = "phrase"
    FALLBACK = "fallback"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CoverBoundaryPolicy:
    """Declared boundary capabilities enabled by a form profile."""

    signals: tuple[BoundarySignal, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryEvidence:
    """One named piece of evidence contributing to the boundary decision."""

    name: str
    strength: float
    line: int
    details: str = ""


@dataclass(frozen=True, slots=True)
class CoverBoundary:
    """Conservative, exclusive end of the cover page."""

    end_line: int | None
    end_offset: int | None
    method: BoundaryMethod
    confidence: float
    evidence: tuple[BoundaryEvidence, ...] = ()
    start_line: int | None = None
    start_offset: int | None = None
    start_evidence: tuple[BoundaryEvidence, ...] = ()
    approximate: bool = True
    continued_cover: bool = False


@dataclass(frozen=True, slots=True)
class BoundaryInput:
    """Representation-neutral input for cover boundary detection."""

    text: str
    representation: str = "ascii"


@dataclass(frozen=True, slots=True)
class CoverStart:
    """The detected opening cluster of the cover page."""

    start_line: int | None
    start_offset: int | None
    evidence: tuple[BoundaryEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class BodyRoot:
    """A detected body anchor found by backward search."""

    line: int
    root_type: str
    confidence: float
    label: str


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    """Canonical definition of a form structural item."""

    item: str
    part: int
    names: tuple[str, ...]
    optional: bool = False
    early: bool = False


@dataclass(frozen=True, slots=True)
class DocumentTopology:
    """The complete 4-zone structural partition of an SEC filing."""

    cover_start: int | None
    cover_end: int | None
    toc_start: int | None
    toc_end: int | None
    body_start: int | None
    confidence: float
    method: str
    evidence: tuple[BoundaryEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class BodyStartEvidence:
    """One named piece of evidence for a body-start decision."""

    name: str
    strength: float
    line: int
    details: str = ""


@dataclass(frozen=True, slots=True)
class BodyStart:
    """The first sufficiently validated body region after cover/TOC material.

    ``anchor_type`` is one of ``BodyAnchorType``. ``line`` is the source line
    of the body-start boundary; ``heading_line`` is the structural heading
    line when present. ``delayed`` is set when an earlier candidate was
    rejected in favor of a later one. ``rejection_reasons`` records why
    earlier candidates were rejected.
    """

    line: int | None
    heading_line: int | None
    first_unit_line: int | None
    anchor_type: str
    confidence: float
    evidence: tuple[BodyStartEvidence, ...] = ()
    delayed: bool = False
    rejection_reasons: tuple[str, ...] = ()
    reason: str = ""


__all__ = [
    "BodyAnchorType",
    "BodyRoot",
    "BodyStart",
    "BodyStartEvidence",
    "BoundaryEvidence",
    "BoundaryInput",
    "BoundaryMethod",
    "BoundarySignal",
    "CoverBoundary",
    "CoverBoundaryPolicy",
    "CoverStart",
    "DocumentTopology",
    "ItemDefinition",
]
