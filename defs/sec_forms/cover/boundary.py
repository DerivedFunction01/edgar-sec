"""Shared cover-boundary evidence and conservative detector."""

from __future__ import annotations

from defs.sec_forms.cover.body_search import (
    _confirm_backward_body,
    _find_body_root_backward,
    _next_nonblank_line,
)
from defs.sec_forms.cover.cover_start import (
    find_cover_start,
)
from defs.sec_forms.cover.models import (
    BodyRoot,
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
    DocumentTopology,
    ItemDefinition,
)
from defs.sec_forms.cover.rules import CompiledCoverRules, compile_cover_rules
from defs.sec_forms.cover.structure import (
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from defs.sec_forms.cover.toc import RE_TOC_HEADING, find_toc_span
from defs.sec_forms.page_markers import find_page_markers


def _prev_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, -1, -1):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _is_proxy_reference_disclosure(line: str) -> bool:
    stripped = line.strip().lower()
    return bool(
        stripped.startswith(
            (
                "portions of",
                "the information required",
                "information required",
                "see part",
                "refer to",
            )
        )
    )


def _enabled(policy: CoverBoundaryPolicy, signal: BoundarySignal) -> bool:
    return signal in policy.signals


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _line_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _next_cover_transition(
    lines: list[str], start_line: int, search_limit: int
) -> tuple[int, str] | None:
    """Find the next heading that can terminate an incorporated-reference block."""
    for index, line in enumerate(lines[start_line:search_limit], start=start_line):
        match = match_structural_line(line, index)
        if match is None:
            continue
        if match.role == "toc_heading":
            return index, "TOC heading"
        if not match.is_exact_heading:
            continue
        if match.reference_count != 1:
            continue
        if index > 0:
            prev = _prev_nonblank_line(lines, index - 1)
            if prev is not None and is_preceding_continuation(prev[1]):
                continue
        following = _next_nonblank_line(lines, index + 1)
        if following is not None:
            if is_continuation_prose(following[1]):
                continue
            if _is_proxy_reference_disclosure(following[1]):
                continue
        if match.role == "part":
            return index, "PART heading"
        if match.role == "item":
            return index, "ITEM 1 heading"
    return None


def _unknown(method: BoundaryMethod = BoundaryMethod.UNKNOWN) -> CoverBoundary:
    return CoverBoundary(
        end_line=None,
        end_offset=None,
        method=method,
        confidence=0.0,
        evidence=(),
        approximate=True,
    )


def _finalize_boundary(
    end_line: int,
    method: BoundaryMethod,
    confidence: float,
    evidence: list[BoundaryEvidence],
    cover_start: CoverStart,
    lines: list[str],
    continued_cover: bool = False,
    confirm_backward: bool = True,
    rules: CompiledCoverRules | None = None,
) -> CoverBoundary:
    """Run backward body confirmation and build the final boundary."""
    if confirm_backward:
        rules = rules or compile_cover_rules()
        adjusted_end, adjusted_evidence = _confirm_backward_body(
            lines, end_line, cover_start.start_line, evidence, rules
        )
    else:
        adjusted_end, adjusted_evidence = end_line, evidence
    return CoverBoundary(
        end_line=adjusted_end,
        end_offset=_line_offset(lines, adjusted_end),
        method=method,
        confidence=confidence,
        evidence=tuple(adjusted_evidence),
        start_line=cover_start.start_line,
        start_offset=cover_start.start_offset,
        start_evidence=cover_start.evidence,
        approximate=True,
        continued_cover=continued_cover,
    )


def find_cover_boundary(
    boundary_input: BoundaryInput | str,
    policy: CoverBoundaryPolicy | None,
    *,
    cover_evidence: object | None = None,
    body_evidence: object | None = None,
) -> CoverBoundary:
    """Find a conservative, exclusive end for cover-specific processing.

    The detector uses bounded structural evidence and never treats a literal
    phrase as authoritative by itself. Profiles opt into evidence capabilities;
    an absent policy explicitly disables cover parsing.
    """
    if policy is None:
        return _unknown(BoundaryMethod.DISABLED)

    text = boundary_input if isinstance(boundary_input, str) else boundary_input.text
    lines = text.splitlines()
    if not lines:
        return _unknown()

    rules = compile_cover_rules(cover_evidence, body_evidence)
    cover_start = find_cover_start(
        text,
        policy,
        cover_evidence=cover_evidence,
        body_evidence=body_evidence,
    )
    scan_start = cover_start.start_line if cover_start.start_line is not None else 0
    search_limit = max(200, int(len(lines) * 0.25))
    scan_start = min(scan_start, search_limit)
    evidence: list[BoundaryEvidence] = []

    identity_count = 0
    first_page: int | None = None
    page_markers = find_page_markers(text)
    page_lines = {text.count("\n", 0, marker.start) for marker in page_markers}
    # Page markers can precede the cover cluster (e.g. <PAGE> at line 0), so
    # detect them from the document start rather than from scan_start.
    for index, line in enumerate(lines[:search_limit]):
        if (
            _enabled(policy, BoundarySignal.PAGE_MARKERS)
            and first_page is None
            and index in page_lines
        ):
            first_page = index
            evidence.append(
                BoundaryEvidence(
                    name="first_page_marker",
                    strength=0.45,
                    line=index,
                    details="page marker establishes a lower bound",
                )
            )
            break
    for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
        if _enabled(
            policy, BoundarySignal.COVER_IDENTITY_AND_LAYOUT
        ) and rules.cover_identity.search(line):
            identity_count += 1

    if first_page is not None and identity_count >= 2:
        evidence.append(
            BoundaryEvidence(
                name="cover_identity_layout",
                strength=0.7,
                line=first_page,
                details=f"{identity_count} cover identity signals",
            )
        )

    if _enabled(policy, BoundarySignal.TOC_TRANSITION):
        toc = find_toc_span(
            text,
            start_line=scan_start,
            max_lines=search_limit,
        )
        if toc is not None and identity_count >= 2 and not toc.approximate:
            evidence.extend(
                BoundaryEvidence(
                    name=f"toc_{item.name}",
                    strength=0.9,
                    line=item.line,
                    details=item.details,
                )
                for item in toc.evidence
            )
            evidence.append(
                BoundaryEvidence(
                    name="toc_start_stops_cover_scan",
                    strength=toc.confidence,
                    line=toc.start_line,
                    details=f"{toc.method} TOC starts cover boundary",
                )
            )
            return _finalize_boundary(
                end_line=toc.start_line,
                method=BoundaryMethod.STRUCTURAL,
                confidence=toc.confidence,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                confirm_backward=False,
            )

    if _enabled(policy, BoundarySignal.INCORPORATED_REFERENCE):
        for match in rules.incorporated.finditer(text):
            index = _line_at_offset(text, match.start())
            if index < scan_start or index >= search_limit:
                continue
            if identity_count < 2 and first_page is None:
                continue
            phrase_end_line = _line_at_offset(text, match.end()) + 1
            transition = _next_cover_transition(lines, phrase_end_line, search_limit)
            end_line = transition[0] if transition else phrase_end_line
            evidence.append(
                BoundaryEvidence(
                    name="incorporated_reference",
                    strength=0.92 if identity_count >= 2 else 0.72,
                    line=index,
                    details="annual/foreign cover reference block",
                )
            )
            if transition:
                evidence.append(
                    BoundaryEvidence(
                        name="incorporated_reference_transition",
                        strength=0.96,
                        line=end_line,
                        details=f"cover ends before {transition[1]}",
                    )
                )
            return _finalize_boundary(
                end_line=end_line,
                method=BoundaryMethod.STRUCTURAL
                if transition
                else BoundaryMethod.PHRASE,
                confidence=(
                    0.96
                    if transition
                    else min(0.9, 0.72 + (0.06 * min(identity_count, 3)))
                ),
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
                continued_cover=True,
            )

    if _enabled(policy, BoundarySignal.TOC_TRANSITION):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            if not RE_TOC_HEADING.match(line):
                continue
            if identity_count < 2 and first_page is None:
                continue
            evidence.append(
                BoundaryEvidence(
                    name="toc_transition",
                    strength=0.9,
                    line=index,
                    details="TOC heading follows cover evidence",
                )
            )
            return _finalize_boundary(
                end_line=index,
                method=BoundaryMethod.STRUCTURAL,
                confidence=0.9,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
            )

    if _enabled(policy, BoundarySignal.PART_FALLBACK):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            match = match_structural_line(line, index)
            if match is None or match.role != "part" or not match.is_exact_heading:
                continue
            if identity_count < 2 and first_page is None:
                continue
            if index > 0:
                prev = _prev_nonblank_line(lines, index - 1)
                if prev is not None and is_preceding_continuation(prev[1]):
                    continue
            following = _next_nonblank_line(lines, index + 1)
            if following is not None:
                if is_continuation_prose(following[1]):
                    continue
                if _is_proxy_reference_disclosure(following[1]):
                    continue
            pair_evidence = []
            if following is not None:
                next_match = match_structural_line(following[1], following[0])
                if next_match is not None and next_match.role == "item":
                    pair_evidence.append(
                        BoundaryEvidence(
                            name="part_item_pair",
                            strength=0.85,
                            line=following[0],
                            details="PART I followed by ITEM 1 business-title heading",
                        )
                    )
            evidence.append(
                BoundaryEvidence(
                    name="part_transition",
                    strength=0.68,
                    line=index,
                    details="structural PART/ITEM candidate after cover evidence",
                )
            )
            evidence.extend(pair_evidence)
            return _finalize_boundary(
                end_line=index,
                method=BoundaryMethod.FALLBACK,
                confidence=0.68,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
            )

    if _enabled(policy, BoundarySignal.ITEM_FALLBACK):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            match = match_structural_line(line, index)
            if match is None or match.role != "item" or not match.is_exact_heading:
                continue
            if identity_count < 2 and first_page is None:
                continue
            if index > 0:
                prev = _prev_nonblank_line(lines, index - 1)
                if prev is not None and is_preceding_continuation(prev[1]):
                    continue
            following = _next_nonblank_line(lines, index + 1)
            if following is not None:
                if is_continuation_prose(following[1]):
                    continue
                if _is_proxy_reference_disclosure(following[1]):
                    continue
            evidence.append(
                BoundaryEvidence(
                    name="item_transition",
                    strength=0.62,
                    line=index,
                    details="canonical ITEM heading after cover evidence",
                )
            )
            return _finalize_boundary(
                end_line=index,
                method=BoundaryMethod.FALLBACK,
                confidence=0.62,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
            )

    # Documented conservative fallback: when the entire document was searched,
    # strong cover identity evidence exists, and no body anchor was found, the
    # document is a cover-only fragment and cover processing applies to all of
    # it. Longer documents with an unsearched remainder stay unknown so body
    # content is never healed as cover by default.
    if identity_count >= 2 and len(lines) <= search_limit:
        evidence.append(
            BoundaryEvidence(
                name="cover_only_fragment",
                strength=0.6,
                line=len(lines),
                details=(
                    f"{identity_count} cover identity signals, no body anchor "
                    "in fully searched document"
                ),
            )
        )
        return CoverBoundary(
            end_line=len(lines),
            end_offset=len(text),
            method=BoundaryMethod.FALLBACK,
            confidence=0.6,
            evidence=tuple(evidence),
            start_line=cover_start.start_line,
            start_offset=cover_start.start_offset,
            start_evidence=cover_start.evidence,
            approximate=True,
            continued_cover=True,
        )

    return _unknown()


def find_cover_boundary_for_profile(
    boundary_input: BoundaryInput | str,
    profile: object,
) -> CoverBoundary:
    """Find a boundary using the resolved form profile's evidence packs."""
    return find_cover_boundary(
        boundary_input,
        getattr(profile, "boundary", None),
        cover_evidence=getattr(profile, "cover_evidence", None),
        body_evidence=getattr(profile, "body_evidence", None),
    )


from defs.sec_forms.cover.topology import resolve_document_topology

__all__ = [
    "BodyRoot",
    "BoundaryEvidence",
    "BoundaryInput",
    "BoundaryMethod",
    "BoundarySignal",
    "CoverBoundary",
    "CoverBoundaryPolicy",
    "CoverStart",
    "DocumentTopology",
    "ItemDefinition",
    "_confirm_backward_body",
    "_find_body_root_backward",
    "find_cover_boundary",
    "find_cover_boundary_for_profile",
    "find_cover_start",
    "resolve_document_topology",
]
