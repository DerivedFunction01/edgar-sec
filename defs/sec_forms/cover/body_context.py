"""Body-unit context and lexical-pack glue for body-start detection.

Sits between the boundary world (logical units, TOC spans) and the generic
lexical evidence engine (`defs.text.bow`). Owns unit indexing, TOC/protected
eligibility, and the resolution of a body evidence object into a compiled
lexical pack. The body-start resolver consumes these helpers; extraction
callers can reuse them for the same unit model.
"""

from __future__ import annotations

from defs.sec_forms.cover.toc import TocSpan
from defs.sec_forms.forms.common import derive_lexical_pack
from defs.text.bow import (
    CompiledEvidencePack,
    EvidenceContext,
    LexicalEvidencePack,
    compile_evidence_pack,
)
from defs.text.healing import strip_alphanumeric_words
from defs.text.logical_units import LogicalUnit

_PROTECTED_UNIT_KINDS = frozenset({"table", "list", "signature", "toc"})


def compile_body_lexical(evidence: object) -> CompiledEvidencePack:
    """Compile the lexical pack for a body evidence object.

    Accepts a compiled pack, a ``LexicalEvidencePack``, or an object
    carrying a ``lexical`` pack or legacy body vocabulary fields.
    """
    if isinstance(evidence, CompiledEvidencePack):
        return evidence
    if isinstance(evidence, LexicalEvidencePack):
        return compile_evidence_pack(evidence)
    lexical = getattr(evidence, "lexical", None)
    if isinstance(lexical, LexicalEvidencePack):
        return compile_evidence_pack(lexical)
    return compile_evidence_pack(
        derive_lexical_pack(
            body_ngrams=tuple(getattr(evidence, "body_ngrams", ())),
            body_verbs=tuple(getattr(evidence, "body_verbs", ())),
            body_terms=tuple(getattr(evidence, "body_terms", ())),
            cover_terms=tuple(getattr(evidence, "cover_terms", ())),
        )
    )


def collect_cover_vocab(lines: list[str], end_line: int) -> frozenset[str]:
    """Collect word tokens from the cover/reference prefix.

    The result is diagnostic context only; it never affects a lexical score.
    """
    return frozenset(strip_alphanumeric_words("\n".join(lines[:end_line])))


def index_units_by_line(units: list[LogicalUnit]) -> dict[int, LogicalUnit]:
    """Map every covered source line to its owning logical unit."""
    units_by_line: dict[int, LogicalUnit] = {}
    for unit in units:
        for line_index in range(unit.start_line, unit.end_line + 1):
            units_by_line[line_index] = unit
    return units_by_line


def unit_at(units_by_line: dict[int, LogicalUnit], line: int) -> LogicalUnit | None:
    return units_by_line.get(line)


def unit_in_toc(unit: LogicalUnit, toc_span: TocSpan | None) -> bool:
    """Return whether a unit belongs to TOC context.

    A unit overlaps the caller-supplied TOC span (``end_line`` is the first
    post-TOC line, so the span is exclusive at the end), or the unit itself
    was classified as TOC content by an upstream semantic classifier.
    """
    if unit.kind == "toc":
        return True
    if toc_span is None:
        return False
    return unit.start_line < toc_span.end_line and unit.end_line >= toc_span.start_line


def unit_is_protected(unit: LogicalUnit) -> bool:
    """Return whether a unit kind is protected for body-start analysis."""
    return unit.kind in _PROTECTED_UNIT_KINDS


def unit_context(
    unit: LogicalUnit,
    toc_span: TocSpan | None,
    prefix_vocab: frozenset[str],
) -> EvidenceContext:
    """Build the lexical scoring context for one logical unit."""
    in_toc = unit_in_toc(unit, toc_span)
    protected = unit_is_protected(unit)
    if in_toc:
        reason = "unit overlaps the detected TOC span"
    elif protected:
        reason = f"unit kind {unit.kind!r} is not eligible prose"
    else:
        reason = ""
    return EvidenceContext(
        eligible=not in_toc and not protected,
        unit_kind=unit.kind,
        zone="toc" if in_toc else None,
        exclusion_reason=reason,
        prefix_vocab=prefix_vocab,
    )


def is_form_placeholder(line: str) -> bool:
    """Return whether a line is a form placeholder like ``Omitted.``."""
    stripped = line.strip().rstrip(".")
    return stripped.lower() in ("omitted", "not applicable", "reserved")


__all__ = [
    "collect_cover_vocab",
    "compile_body_lexical",
    "index_units_by_line",
    "is_form_placeholder",
    "unit_at",
    "unit_context",
    "unit_in_toc",
    "unit_is_protected",
]
