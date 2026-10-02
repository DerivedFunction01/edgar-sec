"""Main cover boundary detection logic.

The detector walks a ladder of evidence sources, strongest first, and returns
the first one that both fires and is corroborated by cover identity or a page
marker:

1. an incorporated-by-reference block (annual and foreign annual covers only),
2. a detected TOC span,
3. a bare TOC heading,
4. an exact ``PART`` heading, then an exact ``ITEM`` heading,
5. an amendment structural transition (EXPLANATORY NOTE, REPORT OF INDEPENDENT
   AUDITORS, SIGNATURES) — only when ``AMENDMENT_TRANSITION`` is enabled,
6. decisive body prose with no structural anchor at all.

No signal is authoritative on its own: a phrase match with no corroborating
cover evidence is ignored, which is why a current report (8-K) — whose profile
disables cover parsing entirely — never gets a cover boundary.
"""

from __future__ import annotations

import re as _re

from edgar_sec.engine.document.page_markers.detector import (
    PageMarkerKind,
    find_page_markers,
)
from edgar_sec.engine.forms.cover.models import (
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
)
from edgar_sec.engine.forms.cover.rules import compile_cover_rules
from edgar_sec.engine.forms.cover.structure import (
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from edgar_sec.engine.forms.cover.toc.finder import find_toc_span
from edgar_sec.engine.forms.cover.toc.patterns import RE_TOC_HEADING

# Amendment-specific structural transitions that end a 10-K/A cover page when
# no PART I / ITEM 1 / TOC sequence is present.  Matched case-insensitively
# against trimmed lines.  Order matters: more-specific patterns first.
_RE_AMENDMENT_TRANSITION = _re.compile(
    r"^\s*(?:"
    r"explanatory\s+(?:note|statement)"
    r"|report\s+of\s+independent\s+(?:registered\s+public\s+accounting\s+firm|auditors?)"
    r"|signatures?"
    r")\s*$",
    _re.IGNORECASE,
)

from .corridor import (
    _finalize_boundary,
    _find_body_prose_line,
    _unknown,
    enabled,
    find_cover_start,
    is_proxy_reference_disclosure,
    line_at_offset,
    next_nonblank_line,
    prev_nonblank_line,
)
from .transition import _first_body_semantic_line, _next_cover_transition


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
    page_analysis = getattr(boundary_input, "page_analysis", None)
    page_markers = (
        page_analysis.markers if page_analysis is not None else find_page_markers(text)
    )
    page_markers = tuple(
        marker
        for marker in page_markers
        if marker.kind
        not in {
            PageMarkerKind.REPEATING_HEADER,
            PageMarkerKind.REPEATING_FOOTER,
        }
    )
    page_lines = {
        getattr(marker, "start_line", None)
        if getattr(marker, "start_line", None) is not None
        else text.count("\n", 0, marker.start)
        for marker in page_markers
    }
    for index, line in enumerate(lines[:search_limit]):
        if (
            enabled(policy, BoundarySignal.PAGE_MARKERS)
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
        if enabled(
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

    if enabled(policy, BoundarySignal.INCORPORATED_REFERENCE):
        for match in rules.incorporated.finditer(text):
            index = line_at_offset(text, match.start())
            if index < scan_start or index >= search_limit:
                continue
            if identity_count < 2 and first_page is None:
                continue
            if is_proxy_reference_disclosure(lines[index]):
                continue
            phrase_end_line = line_at_offset(text, match.end()) + 1
            transition = _next_cover_transition(lines, phrase_end_line, search_limit)
            end_line = transition[0] if transition else phrase_end_line
            depth_line = _first_body_semantic_line(
                lines, phrase_end_line, end_line, rules
            )
            if depth_line is not None:
                evidence.append(
                    BoundaryEvidence(
                        name="body_prose_depth_adjust",
                        strength=0.7,
                        line=depth_line,
                        details=(
                            "body-semantic prose precedes the structural "
                            "transition; cover ends before it"
                        ),
                    )
                )
                end_line = depth_line
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

    if enabled(policy, BoundarySignal.TOC_TRANSITION):
        toc = find_toc_span(
            text,
            start_line=scan_start,
            max_lines=search_limit,
            page_analysis=page_analysis,
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

    if enabled(policy, BoundarySignal.TOC_TRANSITION):
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

    if enabled(policy, BoundarySignal.PART_FALLBACK):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            match = match_structural_line(line, index)
            if match is None or match.role != "part" or not match.is_exact_heading:
                continue
            if identity_count < 2 and first_page is None:
                continue
            if index > 0:
                prev = prev_nonblank_line(lines, index - 1)
                if prev is not None and is_preceding_continuation(prev[1]):
                    continue
            following = next_nonblank_line(lines, index + 1)
            if following is not None:
                if is_continuation_prose(following[1]):
                    continue
                if is_proxy_reference_disclosure(following[1]):
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

    if enabled(policy, BoundarySignal.AMENDMENT_TRANSITION):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            if not _RE_AMENDMENT_TRANSITION.match(line):
                continue
            if identity_count < 2 and first_page is None:
                continue
            if index > 0:
                prev = prev_nonblank_line(lines, index - 1)
                if prev is not None and is_preceding_continuation(prev[1]):
                    continue
            evidence.append(
                BoundaryEvidence(
                    name="amendment_transition",
                    strength=0.72,
                    line=index,
                    details=f"amendment structural transition at line {index}: {line.strip()!r}",
                )
            )
            return _finalize_boundary(
                end_line=index,
                method=BoundaryMethod.FALLBACK,
                confidence=0.72,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
            )

    if enabled(policy, BoundarySignal.ITEM_FALLBACK):
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            match = match_structural_line(line, index)
            if match is None or match.role != "item" or not match.is_exact_heading:
                continue
            if identity_count < 2 and first_page is None:
                continue
            if index > 0:
                prev = prev_nonblank_line(lines, index - 1)
                if prev is not None and is_preceding_continuation(prev[1]):
                    continue
            following = next_nonblank_line(lines, index + 1)
            if following is not None:
                if is_continuation_prose(following[1]):
                    continue
                if is_proxy_reference_disclosure(following[1]):
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

    if enabled(policy, BoundarySignal.BODY_PROSE_FALLBACK):
        prose_line = _find_body_prose_line(lines, scan_start, search_limit, rules)
        if (
            prose_line is not None
            and cover_start.start_line is not None
            and identity_count >= 1
        ):
            evidence.append(
                BoundaryEvidence(
                    name="body_prose_fallback",
                    strength=0.65,
                    line=prose_line,
                    details=(
                        "decisive body-lexical prose ends a cover without "
                        "structural anchors"
                    ),
                )
            )
            return _finalize_boundary(
                end_line=prose_line,
                method=BoundaryMethod.FALLBACK,
                confidence=0.65,
                evidence=evidence,
                cover_start=cover_start,
                lines=lines,
                rules=rules,
            )

    if (
        cover_start.start_line is not None
        and identity_count >= 1
        and len(lines) <= search_limit
    ):
        evidence.append(
            BoundaryEvidence(
                name="cover_only_fragment",
                strength=0.6,
                line=len(lines),
                details=(
                    f"{identity_count} cover identity signal(s), detected cover "
                    "start, and no body anchor in fully searched document"
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


__all__ = ["find_cover_boundary", "find_cover_boundary_for_profile"]
