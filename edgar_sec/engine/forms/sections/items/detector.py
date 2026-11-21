"""Full-document Part and Item section sequence detector."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from edgar_sec.engine.document.page_markers.candidates import line_offsets
from edgar_sec.engine.forms.sections.items.candidates import extract_section_candidates
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    ResolvedSection,
    SectionSequence,
)
from edgar_sec.engine.forms.sections.sequence import MonotonicSequenceTracker
from edgar_sec.foundation.hashing import sha256_text

if TYPE_CHECKING:
    from edgar_sec.domain.forms.common.models import ItemDefinition

_MAX_PSEUDO_TOC_LINE_GAP = 3
_MIN_PSEUDO_TOC_CLUSTER_SIZE = 3


_RE_NON_PROSE = re.compile(r"^(?:page\s+)?\d+$|^[\.\-\s|+=]+$", re.IGNORECASE)

_RE_SUBSTANTIVE_PROSE = re.compile(r"[a-zA-Z]{3,}")


def _has_substantive_prose_between(
    lines: list[str], start_line: int, end_line: int
) -> bool:
    """Return True if intermediate lines contain substantive prose."""
    for line_idx in range(start_line + 1, end_line):
        stripped = lines[line_idx].strip()
        if not stripped or _RE_NON_PROSE.match(stripped):
            continue
        if _RE_SUBSTANTIVE_PROSE.search(stripped):
            return True
    return False


def _filter_pseudo_toc_candidates(
    candidates: list,
    lines: list[str],
) -> tuple[list, set[int]]:
    """Identify and isolate unpaginated navigation clusters lacking prose."""
    if len(candidates) < _MIN_PSEUDO_TOC_CLUSTER_SIZE:
        return candidates, set()

    toc_lines: set[int] = set()
    filtered: list = []
    i = 0
    n = len(candidates)
    while i < n:
        cluster = [candidates[i]]
        j = i + 1
        while (
            j < n
            and (candidates[j].line_number - candidates[j - 1].line_number)
            <= _MAX_PSEUDO_TOC_LINE_GAP
            and not _has_substantive_prose_between(
                lines, candidates[j - 1].line_number, candidates[j].line_number
            )
        ):
            cluster.append(candidates[j])
            j += 1
        if len(cluster) >= _MIN_PSEUDO_TOC_CLUSTER_SIZE:
            # A navigation cluster previews headings that recur later in
            # the body; a dense caption cluster nothing repeats is a form
            # face carrying its content inline, not a table of contents.
            cluster_ids = {item for c in cluster for item in c.identifiers}
            later_ids = {item for c in candidates[j:] for item in c.identifiers}
            if cluster_ids & later_ids:
                for c in cluster:
                    toc_lines.add(c.line_number)
                i = j
                continue
        filtered.append(candidates[i])
        i += 1
    return filtered, toc_lines


def _event_sections(
    cand: SectionCandidate, *, displaced: bool
) -> list[ResolvedSection]:
    """Resolve one admitted candidate event into its sections."""
    if cand.kind == CandidateKind.GROUPED:
        return [
            ResolvedSection(
                item_identifier=f"ITEM {item_id}",
                start_line=cand.line_number,
                end_line=None,
                title=cand.title,
                raw_heading=cand.raw_text,
                kind=CandidateKind.GROUPED,
                confidence=0.9,
                is_omitted=cand.is_omitted,
                grouped_with=tuple(i for i in cand.identifiers if i != item_id),
                displaced=displaced,
            )
            for item_id in cand.identifiers
        ]
    conf = 0.95 if cand.kind == CandidateKind.STANDARD else 0.85
    return [
        ResolvedSection(
            item_identifier=f"ITEM {cand.identifiers[0]}",
            start_line=cand.line_number,
            end_line=None,
            title=cand.title,
            raw_heading=cand.raw_text,
            kind=cand.kind,
            confidence=conf,
            is_omitted=cand.is_omitted,
            displaced=displaced,
        )
    ]


def detect_section_sequence(
    text: str,
    *,
    family: str,
    taxonomy_items: tuple[ItemDefinition, ...],
    toc_span: tuple[int, int] | None = None,
    payload_sha256: str | None = None,
    representation_id: str | None = None,
    renderer_version: str | None = None,
    run_in_titles: bool = False,
) -> SectionSequence:
    """Detect statutory Part/Item sections across a document, in document order."""
    lines = text.splitlines()
    total_lines = len(lines)
    offsets = line_offsets(lines)
    toc_line_set = (
        set(range(toc_span[0], toc_span[1] + 1)) if toc_span is not None else None
    )

    raw_candidates = extract_section_candidates(
        lines,
        taxonomy_items=taxonomy_items,
        toc_lines=toc_line_set,
        run_in_titles=run_in_titles,
    )
    candidates, _ = _filter_pseudo_toc_candidates(raw_candidates, lines)
    refined_candidates: list[SectionCandidate] = []
    for idx, c in enumerate(candidates):
        if c.kind == CandidateKind.STANDARD and not c.title and not c.is_omitted:
            has_titled = any(
                ahead.identifiers == c.identifiers and (ahead.title or ahead.is_omitted)
                for ahead in candidates[idx + 1 : idx + 5]
            )
            if has_titled:
                continue
        refined_candidates.append(c)

    canonical_order = tuple(
        item_def.item.replace("ITEM", "").strip() for item_def in taxonomy_items
    )
    tracker = MonotonicSequenceTracker[str](canonical_order)

    eligible: list[SectionCandidate] = []
    non_contiguous = 0
    for idx, cand in enumerate(refined_candidates):
        if cand.preceded_by_continuation and not (
            cand.kind == CandidateKind.STANDARD and cand.title
        ):
            continue

        if cand.kind == CandidateKind.GROUPED:
            if not tracker.validate_group_contiguity(cand.identifiers):
                non_contiguous += 1
                continue
            if not cand.title and not cand.is_omitted:
                has_titled = any(
                    ahead.identifiers[0] in cand.identifiers
                    and (ahead.title or ahead.is_omitted)
                    for ahead in refined_candidates[idx + 1 : idx + 10]
                )
                if has_titled:
                    continue
        eligible.append(cand)

    # Assembly keeps the canonical spine plus genuine candidates whose
    # exclusion is one local fault; on a stream whose faults do not
    # decompose, the spine alone is kept and the rest rejected.
    assembly = tracker.assemble_sequence([cand.identifiers for cand in eligible])
    resolved: list[ResolvedSection] = []
    anachronisms = 0
    missing_labels: tuple[str, ...]
    displaced_at = set(assembly.displaced)
    chosen = set(assembly.spine) | displaced_at
    resolved_ids: set[str] = set()
    current_idx = -1
    for pos, cand in enumerate(eligible):
        if pos not in chosen:
            anachronisms += 1
            continue
        resolved.extend(_event_sections(cand, displaced=pos in displaced_at))
        for item_id in cand.identifiers:
            resolved_ids.add(item_id)
            ordn = tracker.get_ordinal(item_id)
            if ordn is not None and ordn > current_idx:
                current_idx = ordn
    missing_labels = tuple(
        f"ITEM {item}"
        for idx, item in enumerate(canonical_order)
        if idx <= current_idx and item not in resolved_ids
    )

    # Compute bounding spans between consecutive distinct start lines
    bounded_sections: list[ResolvedSection] = []
    text_len = len(text)
    for idx, sec in enumerate(resolved):
        next_sec = next(
            (s for s in resolved[idx + 1 :] if s.start_line > sec.start_line),
            None,
        )
        end_line = next_sec.start_line - 1 if next_sec else total_lines
        norm_end_line = max(sec.start_line, end_line)
        start_char = (
            offsets[sec.start_line] if sec.start_line < len(offsets) else text_len
        )
        end_char = (
            offsets[norm_end_line + 1] if norm_end_line + 1 < len(offsets) else text_len
        )
        bounded_sections.append(
            ResolvedSection(
                item_identifier=sec.item_identifier,
                start_line=sec.start_line,
                end_line=norm_end_line,
                title=sec.title,
                raw_heading=sec.raw_heading,
                kind=sec.kind,
                confidence=sec.confidence,
                is_omitted=sec.is_omitted,
                grouped_with=sec.grouped_with,
                start_char=start_char,
                end_char=end_char,
                displaced=sec.displaced,
            )
        )

    digest = payload_sha256 or (sha256_text(text) if text else None)
    return SectionSequence(
        family=family,
        sections=tuple(bounded_sections),
        missing_items=missing_labels,
        anachronistic_rejections=anachronisms,
        non_contiguous_rejections=non_contiguous,
        disordered=assembly.disordered,
        payload_sha256=digest,
        representation_id=representation_id,
        renderer_version=renderer_version,
    )
