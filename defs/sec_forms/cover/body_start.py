"""Forward body-start detection after cover/TOC boundaries.

Consumes the results of cover/TOC detection and resolves the first
sufficiently validated body region. The detector prefers a later validated
``BODY_START`` over an early false start: a late start may leave some
ordinary body prose hard-wrapped, while an early start can corrupt a table,
list, signature, TOC, or cover layout.

This module is form-neutral: it consumes a lexical evidence pack via
``defs.sec_forms.cover.body_context`` for scoring. Cover and TOC detection
stay upstream; their boundary results are consumed, never reimplemented.
"""

from __future__ import annotations

import re

from defs.sec_forms.cover.body_context import (
    collect_cover_vocab,
    compile_body_lexical,
    index_units_by_line,
    is_form_placeholder,
    unit_at,
    unit_context,
    unit_in_toc,
)
from defs.sec_forms.cover.models import (
    BodyAnchorType,
    BodyStart,
    BodyStartEvidence,
)
from defs.sec_forms.cover.structure import (
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from defs.sec_forms.cover.toc import TocSpan
from defs.text.bow import BowScore, CompiledEvidencePack, score_unit
from defs.text.structure.logical_units import LogicalUnit, classify_units

# Bounded forward search window after COVER_END/TOC_END.
_BODY_START_SEARCH_WINDOW = 300
# Maximum lines a structural heading can precede its first prose unit.
_HEADING_PROSE_WINDOW = 25
# Minimum lexical score to accept a substantive body start.
_MIN_BODY_SCORE = 2
_WHITESPACE_RE = re.compile(r"\s+")


def _next_nonblank_line(lines: list[str], start: int) -> tuple[int, str] | None:
    return next(
        ((i, s) for i in range(start, len(lines)) if (s := lines[i].strip())),
        None,
    )


def _prev_nonblank_line(lines: list[str], start: int) -> tuple[int, str] | None:
    return next(
        ((i, s) for i in range(start, -1, -1) if (s := lines[i].strip())),
        None,
    )


def _validate_structural_heading(
    lines: list[str],
    heading_line: int,
    units_by_line: dict[int, LogicalUnit],
    toc_span: TocSpan | None,
) -> tuple[bool, str]:
    """Validate a structural PART/ITEM heading as a body anchor.

    Returns (valid, reason). A heading is invalid when it is in TOC/table
    context, has multiple references, is followed by lowercase continuation
    prose, or is preceded by continuation tokens.
    """
    line = lines[heading_line]
    stripped = line.strip()

    unit = unit_at(units_by_line, heading_line)
    if unit is not None:
        if unit_in_toc(unit, toc_span):
            return False, "heading in TOC context"
        if unit.kind in ("table", "list", "signature"):
            return False, "heading in protected table/list unit"

    match = match_structural_line(stripped, heading_line)
    if match is None or not match.is_exact_heading:
        return False, "not an exact structural heading"
    if match.reference_count > 1:
        return False, "multiple PART/ITEM references"

    if heading_line > 0:
        prev = _prev_nonblank_line(lines, heading_line - 1)
        if prev is not None and is_preceding_continuation(prev[1]):
            return False, "preceded by continuation token"

    following = _next_nonblank_line(lines, heading_line + 1)
    if following is not None and is_continuation_prose(following[1]):
        return False, "followed by lowercase continuation prose"

    return True, "valid structural heading"


def _find_first_substantive_prose(
    units: list[LogicalUnit],
    compiled: CompiledEvidencePack,
    toc_span: TocSpan | None,
    prefix_vocab: frozenset[str],
    start_line: int,
    limit_line: int,
) -> tuple[LogicalUnit | None, BowScore | None, LogicalUnit | None]:
    """Find the first substantive prose unit with a lexical score >= 2.

    Skips form placeholders, short headings, tables, and lists. Consecutive
    short paragraph units (each below the word gate) are merged before scoring
    so fragmented HTML prose — split spans, short lead sentences — can still
    reach the lexical gate. Also returns the first intermediate (score-1) unit
    encountered for the audit trail.
    """
    intermediate: LogicalUnit | None = None
    merged: list[LogicalUnit] = []
    merged_text = ""
    for unit in units:
        if unit.start_line < start_line:
            continue
        if unit.start_line > limit_line:
            break
        if unit.kind != "paragraph":
            continue
        if is_form_placeholder(unit.text):
            continue
        if len(unit.text.split()) < 8:
            merged.append(unit)
            merged_text = f"{merged_text} {unit.text}".strip()
            if len(merged_text.split()) >= 8:
                head = merged[0]
                candidate = LogicalUnit(
                    kind="paragraph",
                    start_line=head.start_line,
                    end_line=unit.end_line,
                    text=merged_text,
                )
                bow_score = score_unit(
                    candidate.text,
                    compiled,
                    unit_context(candidate, toc_span, prefix_vocab),
                )
                if bow_score.score >= _MIN_BODY_SCORE:
                    return candidate, bow_score, intermediate
                if bow_score.score == 1 and intermediate is None:
                    intermediate = candidate
                merged = []
                merged_text = ""
            continue
        bow_score = score_unit(
            unit.text, compiled, unit_context(unit, toc_span, prefix_vocab)
        )
        if bow_score.score >= _MIN_BODY_SCORE:
            return unit, bow_score, intermediate
        if bow_score.score == 1 and intermediate is None:
            intermediate = unit
    return None, None, intermediate


def _score_description(bow_score: BowScore) -> str:
    tiers = ", ".join(bow_score.satisfied_tiers) or "none"
    return f"BoW score {bow_score.score} via tier(s) {tiers}"


def find_body_start(
    text: str,
    cover_end: int | None,
    toc_end: int | None,
    evidence: object,
    *,
    search_window: int = _BODY_START_SEARCH_WINDOW,
    toc_span: TocSpan | None = None,
) -> BodyStart:
    """Find the first validated body region after cover/TOC material.

    Args:
        text: full source text.
        cover_end: exclusive cover boundary line (``COVER_END``).
        toc_end: exclusive TOC boundary line (``TOC_END``), when present.
        evidence: a compiled lexical pack, a ``LexicalEvidencePack``, or an
            object carrying a ``lexical`` pack or legacy body fields.
        search_window: bounded forward search window.
        toc_span: caller-supplied TOC span; units inside it stay ineligible.
    """
    lines = text.splitlines()
    if not lines:
        return _unknown_body_start(reason="empty document")

    lower_bound = max(cover_end or 0, toc_end or 0)
    search_limit = min(len(lines), lower_bound + search_window)

    units = classify_units(text)
    units_by_line = index_units_by_line(units)
    compiled = compile_body_lexical(evidence)
    semantic_headings = tuple(getattr(evidence, "semantic_headings", ()))
    prefix_vocab = collect_cover_vocab(lines, lower_bound)

    evidence_log: list[BodyStartEvidence] = []
    rejection_reasons: list[str] = []
    seen_intermediate = False

    candidates: list[tuple[int, str, object]] = []
    structural_headings = tuple(getattr(evidence, "structural_headings", ()))
    for cand_line, role in _scan_structural_candidates(
        lines,
        units_by_line,
        toc_span,
        lower_bound,
        search_limit,
        structural_headings,
    ):
        candidates.append((cand_line, "structural", role))
    for cand_line, unit in _scan_semantic_candidates(
        units, semantic_headings, toc_span, lower_bound, search_limit
    ):
        candidates.append((cand_line, "semantic", unit))

    candidates.sort(key=lambda c: c[0])

    for candidate_line, kind, payload in candidates:
        if kind == "structural":
            role = str(payload)
            valid, reason = _validate_structural_heading(
                lines, candidate_line, units_by_line, toc_span
            )
            if not valid:
                rejection_reasons.append(
                    f"line {candidate_line} {role} rejected: {reason}"
                )
                evidence_log.append(
                    BodyStartEvidence(
                        name="structural_candidate_rejected",
                        strength=0.3,
                        line=candidate_line,
                        details=f"{role}: {reason}",
                    )
                )
                continue

            prose_limit = min(search_limit, candidate_line + _HEADING_PROSE_WINDOW)
            prose_unit, bow_score, intermediate = _find_first_substantive_prose(
                units, compiled, toc_span, prefix_vocab, candidate_line + 1, prose_limit
            )
            seen_intermediate = _record_intermediate(
                evidence_log, intermediate, seen_intermediate
            )
            if prose_unit is not None and bow_score is not None:
                evidence_log.append(
                    BodyStartEvidence(
                        name="structural_body_anchor",
                        strength=0.9,
                        line=candidate_line,
                        details=f"{role} with substantive prose at line {prose_unit.start_line} ({_score_description(bow_score)})",
                    )
                )
                return _build_body_start(
                    line=candidate_line,
                    heading_line=candidate_line,
                    first_unit_line=prose_unit.start_line,
                    anchor_type=BodyAnchorType.STRUCTURAL.value,
                    confidence=0.9,
                    evidence_log=evidence_log,
                    rejection_reasons=rejection_reasons,
                    reason=f"{role} heading with validated prose at line {prose_unit.start_line}",
                )
            rejection_reasons.append(
                f"line {candidate_line} {role}: no substantive prose within window"
            )
        elif kind == "semantic":
            heading_unit: LogicalUnit = payload  # type: ignore[assignment]
            context = unit_context(heading_unit, toc_span, prefix_vocab)
            if len(heading_unit.text.split()) >= 8:
                bow_score = score_unit(heading_unit.text, compiled, context)
                if bow_score.score >= _MIN_BODY_SCORE:
                    evidence_log.append(
                        BodyStartEvidence(
                            name="semantic_body_anchor",
                            strength=0.8,
                            line=heading_unit.start_line,
                            details=f"semantic section with substantive prose ({_score_description(bow_score)})",
                        )
                    )
                    return _build_body_start(
                        line=heading_unit.start_line,
                        heading_line=heading_unit.start_line,
                        first_unit_line=heading_unit.start_line,
                        anchor_type=BodyAnchorType.SEMANTIC.value,
                        confidence=0.8,
                        evidence_log=evidence_log,
                        rejection_reasons=rejection_reasons,
                        reason=f"semantic body section with validated prose at line {heading_unit.start_line}",
                    )

            prose_limit = min(
                search_limit, heading_unit.end_line + _HEADING_PROSE_WINDOW
            )
            prose_unit, bow_score, intermediate = _find_first_substantive_prose(
                units,
                compiled,
                toc_span,
                prefix_vocab,
                heading_unit.end_line + 1,
                prose_limit,
            )
            seen_intermediate = _record_intermediate(
                evidence_log, intermediate, seen_intermediate
            )
            if prose_unit is not None and bow_score is not None:
                evidence_log.append(
                    BodyStartEvidence(
                        name="semantic_body_anchor",
                        strength=0.8,
                        line=heading_unit.start_line,
                        details=f"semantic section with substantive prose at line {prose_unit.start_line} ({_score_description(bow_score)})",
                    )
                )
                return _build_body_start(
                    line=heading_unit.start_line,
                    heading_line=heading_unit.start_line,
                    first_unit_line=prose_unit.start_line,
                    anchor_type=BodyAnchorType.SEMANTIC.value,
                    confidence=0.8,
                    evidence_log=evidence_log,
                    rejection_reasons=rejection_reasons,
                    reason=f"semantic body section with validated prose at line {prose_unit.start_line}",
                )
            rejection_reasons.append(
                f"line {candidate_line} semantic heading: no substantive prose within window"
            )

    prose_unit, bow_score, intermediate = _find_first_substantive_prose(
        units, compiled, toc_span, prefix_vocab, lower_bound, search_limit
    )
    _record_intermediate(evidence_log, intermediate, seen_intermediate)
    if prose_unit is not None and bow_score is not None:
        evidence_log.append(
            BodyStartEvidence(
                name="substantive_body_anchor",
                strength=0.6,
                line=prose_unit.start_line,
                details=f"substantive prose cluster without structural heading ({_score_description(bow_score)})",
            )
        )
        return _build_body_start(
            line=prose_unit.start_line,
            heading_line=None,
            first_unit_line=prose_unit.start_line,
            anchor_type=BodyAnchorType.SUBSTANTIVE.value,
            confidence=0.6,
            evidence_log=evidence_log,
            rejection_reasons=rejection_reasons,
            reason="substantive body prose cluster without structural heading",
        )

    return _build_body_start(
        line=None,
        heading_line=None,
        first_unit_line=None,
        anchor_type=BodyAnchorType.UNKNOWN.value,
        confidence=0.0,
        evidence_log=evidence_log,
        rejection_reasons=rejection_reasons,
        reason="no reliable body candidate within search window",
    )


def _build_body_start(
    line: int | None,
    heading_line: int | None,
    first_unit_line: int | None,
    anchor_type: str,
    confidence: float,
    evidence_log: list[BodyStartEvidence],
    rejection_reasons: list[str],
    reason: str,
) -> BodyStart:
    return BodyStart(
        line=line,
        heading_line=heading_line,
        first_unit_line=first_unit_line,
        anchor_type=anchor_type,
        confidence=confidence,
        evidence=tuple(evidence_log),
        delayed=len(rejection_reasons) > 0,
        rejection_reasons=tuple(rejection_reasons),
        reason=reason,
    )


def _record_intermediate(
    evidence_log: list[BodyStartEvidence],
    intermediate: LogicalUnit | None,
    seen: bool,
) -> bool:
    """Append one intermediate-evidence entry; returns the new seen flag."""
    if intermediate is not None and not seen:
        evidence_log.append(
            BodyStartEvidence(
                name="bow_intermediate",
                strength=0.4,
                line=intermediate.start_line,
                details="intermediate prose evidence; search continued",
            )
        )
        return True
    return seen


def _unknown_body_start(reason: str) -> BodyStart:
    return _build_body_start(
        None, None, None, BodyAnchorType.UNKNOWN.value, 0.0, [], [], reason
    )


def _scan_structural_candidates(
    lines: list[str],
    units_by_line: dict[int, LogicalUnit],
    toc_span: TocSpan | None,
    lower_bound: int,
    search_limit: int,
    structural_headings: tuple[str, ...] = (),
) -> list[tuple[int, str]]:
    """Scan forward for structural PART/ITEM heading candidates."""
    candidates: list[tuple[int, str]] = []
    norm_sh = (
        {h.upper().strip() for h in structural_headings}
        if structural_headings
        else set()
    )
    for index in range(lower_bound, search_limit):
        unit = unit_at(units_by_line, index)
        if unit is not None and (
            unit_in_toc(unit, toc_span) or unit.kind != "paragraph"
        ):
            continue
        line = lines[index].strip()
        if not line:
            continue
        match = match_structural_line(line, index)
        if match is None or not match.is_exact_heading:
            continue
        label = match.label.strip()
        lbl_up = label.upper()
        if not norm_sh or any(lbl_up == s or lbl_up.startswith(s) for s in norm_sh):
            candidates.append((index, label))
    return candidates


def _scan_semantic_candidates(
    units: list[LogicalUnit],
    semantic_headings: tuple[str, ...],
    toc_span: TocSpan | None,
    lower_bound: int,
    search_limit: int,
) -> list[tuple[int, LogicalUnit]]:
    """Scan forward for semantic heading candidates."""
    if not semantic_headings:
        return []
    lowered = [h.lower() for h in semantic_headings]
    normalized = [_WHITESPACE_RE.sub(" ", h.replace("-", " ")) for h in lowered]
    candidates: list[tuple[int, LogicalUnit]] = []
    for unit in units:
        if unit.start_line < lower_bound:
            continue
        if unit.start_line > search_limit:
            break
        if unit.kind != "paragraph" or unit_in_toc(unit, toc_span):
            continue
        t_low = unit.text.lower()
        t_norm = _WHITESPACE_RE.sub(" ", t_low)
        if any(h in t_low or h in t_norm for h in lowered + normalized):
            candidates.append((unit.start_line, unit))
    return candidates


__all__ = ["BodyStart", "BodyStartEvidence", "find_body_start"]
