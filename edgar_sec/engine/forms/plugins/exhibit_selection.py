"""Bounded probe for exhibit designations near a document's opening."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    EvidenceSpan,
    ExhibitIdentity,
)
from edgar_sec.domain.forms.exhibits.profiles import get_exhibit_authority_profile
from edgar_sec.domain.forms.exhibits.registry import resolve_pack_for_identity
from edgar_sec.engine.forms.cover.toc.models import TocSpan

if TYPE_CHECKING:
    from edgar_sec.domain.forms.common.exhibits import ExhibitPack


# =============================================================================
# Precompiled Patterns (Module Load Time)
# =============================================================================

# Line-anchored exhibit designation pattern
DESIGNATION_RE = re.compile(
    r"(?m)^EXHIBIT\s+(\d+(?:\.\d+)*)|^EX-(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


PROBE_LINE_BOUND = 25
"""Maximum opening lines to scan for exhibit designator probes."""

PROBE_CHAR_BOUND = 10000


@dataclass(frozen=True, slots=True)
class ExhibitProbeMatch:
    """Match result from an exhibit header probe."""

    exhibit_identity: ExhibitIdentity
    evidence_tier: str
    confidence_band: str
    evidence_span: EvidenceSpan | None = None
    line_number: int | None = None
    raw_match: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledExhibitPack:
    """Precompiled regex patterns for exhibit pack evaluation."""

    pack_id: str
    pack_version: str
    title_pattern: re.Pattern
    primary_pattern: re.Pattern
    secondary_pattern: re.Pattern
    veto_pattern: re.Pattern
    title_window_lines: int


_PACK_COMPILE_CACHE: dict[tuple[str, str], CompiledExhibitPack] = {}


def _compile_pack(pack: ExhibitPack) -> CompiledExhibitPack:
    """Compile a pack's string anchors/tokens into regex patterns."""
    from edgar_sec.foundation.regex.builder import build_alternation

    def compile_terms(items: tuple[str, ...]) -> re.Pattern:
        pattern = build_alternation(
            items,
            auto_escape=True,
            compact=True,
            flexible_whitespace=True,
            never_match_empty=True,
        )
        return re.compile(pattern, re.IGNORECASE)

    title_pattern = compile_terms(pack.title_anchors)
    primary_pattern = compile_terms(pack.primary_anchors)
    secondary_pattern = compile_terms(pack.secondary_tokens)
    veto_pattern = compile_terms(pack.veto_signals)

    return CompiledExhibitPack(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        title_pattern=title_pattern,
        primary_pattern=primary_pattern,
        secondary_pattern=secondary_pattern,
        veto_pattern=veto_pattern,
        title_window_lines=pack.title_window_lines,
    )


def _get_compiled_pack(pack_id: str, pack: ExhibitPack) -> CompiledExhibitPack:
    """Get cached compiled pack or compile on first access."""
    cache_key = (pack_id, pack.version)
    if cache_key not in _PACK_COMPILE_CACHE:
        _PACK_COMPILE_CACHE[cache_key] = _compile_pack(pack)
    return _PACK_COMPILE_CACHE[cache_key]


def _normalize_exhibit_code(raw: str | None) -> str:
    """Normalize exhibit code to canonical numeric form."""
    if raw is None:
        return ""
    normalized = raw.upper().replace("-", ".").replace(" ", "")
    return normalized.replace("EXHIBIT", "").replace("EX", "").lstrip(".")


def is_shielded_by_toc(span: EvidenceSpan, toc_span: TocSpan | None) -> bool:
    """Check if a span falls inside TOC or Exhibit Index bounds."""
    if toc_span is None:
        return False
    return toc_span.start_offset <= span.start_char < toc_span.end_offset


def probe_exhibit_header(
    text: str,
    lines: tuple[str, ...],
    toc_span: TocSpan | None = None,
    filing_form: str | None = None,
) -> ExhibitProbeMatch | None:
    """Search opening window for exhibit designator.

    Returns a match only when a line-anchored exhibit code appears
    before PROBE_LINE_BOUND and is not shielded by TOC.
    """
    if lines:
        candidate = "\n".join(lines[:PROBE_LINE_BOUND])
    else:
        candidate = text[:10000]

    for m in DESIGNATION_RE.finditer(candidate):
        # Try both capture groups (group 1 for EXHIBIT, group 2 for EX-)
        raw_code = m.group(1) or m.group(2)
        code = _normalize_exhibit_code(raw_code)
        if code in ("", "0"):
            continue

        # Determine which group matched to get correct span
        group_num = 1 if m.group(1) else 2

        span = EvidenceSpan(
            signal_id=f"exhibit_code_{code}",
            start_char=m.start(group_num),
            end_char=m.end(group_num),
        )

        if is_shielded_by_toc(span, toc_span):
            continue

        authority_id = "reg_s_k_item_601"
        identity = ExhibitIdentity(authority_id=authority_id, code=code)

        line_num: int | None = None
        if lines:
            offset = m.start(group_num)
            line_num = 0
            pos = 0
            for i, line in enumerate(lines):
                pos += len(line) + 1
                if offset < pos:
                    line_num = i
                    break

        return ExhibitProbeMatch(
            exhibit_identity=identity,
            evidence_tier="direct_designator",
            confidence_band="high",
            evidence_span=span,
            line_number=line_num,
            raw_match=m.group(0),
        )

    return None


def _line_prefix(text: str, line_limit: int, char_limit: int) -> str:
    prefix = text[:char_limit]
    offset = 0
    for _ in range(line_limit):
        newline = prefix.find("\n", offset)
        if newline < 0:
            return prefix
        offset = newline + 1
    return prefix[:offset]


def evaluate_exhibit_body(
    text: str,
    *,
    filing_form: str,
    expected_type: str,
    expected_identity: ExhibitIdentity,
    toc_span: TocSpan | None = None,
) -> DocumentRoleAssessment | None:
    pack = resolve_pack_for_identity(expected_identity)
    profile = get_exhibit_authority_profile(expected_identity.authority_id)
    if pack is None or profile is None or filing_form not in profile.applicable_forms:
        return None

    probe_text = _line_prefix(text, PROBE_LINE_BOUND, PROBE_CHAR_BOUND)
    title_text = _line_prefix(probe_text, pack.title_window_lines, len(probe_text))
    compiled = _get_compiled_pack(pack.pack_id, pack)
    header = probe_exhibit_header(
        probe_text, (), toc_span=toc_span, filing_form=filing_form
    )
    title_match = compiled.title_pattern.search(title_text)
    veto_match = compiled.veto_pattern.search(title_text)

    supporting: list[EvidenceSpan] = []
    contradicting: list[EvidenceSpan] = []
    if header is not None and header.evidence_span is not None:
        target = (
            supporting
            if header.exhibit_identity == expected_identity
            else contradicting
        )
        target.append(header.evidence_span)
    if title_match is not None:
        supporting.append(
            EvidenceSpan(
                signal_id=f"{pack.pack_id}_title",
                start_char=title_match.start(),
                end_char=title_match.end(),
            )
        )
    if veto_match is not None:
        contradicting.append(
            EvidenceSpan(
                signal_id=f"{pack.pack_id}_veto",
                start_char=veto_match.start(),
                end_char=veto_match.end(),
            )
        )

    mismatch = (
        header is not None and header.exhibit_identity != expected_identity
    ) or veto_match is not None
    consistent = (
        header is not None
        and header.exhibit_identity == expected_identity
        and title_match is not None
        and veto_match is None
    )
    disposition = (
        "possible_role_mismatch"
        if mismatch
        else "consistent"
        if consistent
        else "insufficient_evidence"
    )
    diagnostic_code = "suspected_misfiled_exhibit" if mismatch else None
    diagnostic_detail = (
        "Opening evidence conflicts with the expected exhibit pack."
        if mismatch
        else None
    )
    return DocumentRoleAssessment(
        expected_role="exhibit",
        expected_type=expected_type,
        filing_form=filing_form,
        expected_identity=expected_identity,
        observed_kind="exhibit" if header is not None else "unknown",
        observed_identity=header.exhibit_identity if header is not None else None,
        disposition=disposition,
        evaluator_quality=pack.evaluator_quality,
        profile_id=profile.authority_id,
        profile_version=profile.version,
        diagnostic_code=diagnostic_code,
        diagnostic_detail=diagnostic_detail,
        supporting_evidence=tuple(supporting),
        contradicting_evidence=tuple(contradicting),
        matched_evidence_tier=(pack.matched_evidence_tier if consistent else None),
        confidence_band=(
            pack.min_confidence_band
            if consistent
            else "low"
            if mismatch
            else "insufficient"
        ),
        pack_id=pack.pack_id,
        pack_version=pack.version,
    )


__all__ = [
    "PROBE_LINE_BOUND",
    "ExhibitProbeMatch",
    "CompiledExhibitPack",
    "DESIGNATION_RE",
    "is_shielded_by_toc",
    "probe_exhibit_header",
    "evaluate_exhibit_body",
    "_compile_pack",
    "_get_compiled_pack",
]
