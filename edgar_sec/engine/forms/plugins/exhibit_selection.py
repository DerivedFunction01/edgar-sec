"""Bounded probe for exhibit designations near a document's opening."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.exhibits import EvidenceSpan, ExhibitIdentity
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
    title_pattern: re.Pattern
    primary_pattern: re.Pattern
    secondary_pattern: re.Pattern
    veto_pattern: re.Pattern
    title_window_lines: int


_PACK_COMPILE_CACHE: dict[str, CompiledExhibitPack] = {}
"""Cache compiled packs by pack_id for reuse."""


def _compile_pack(pack: ExhibitPack) -> CompiledExhibitPack:
    """Compile a pack's string anchors/tokens into regex patterns."""
    from edgar_sec.foundation.regex.builder import build_alternation

    title_pattern = build_alternation(
        pack.title_anchors,
        auto_escape=True,
        compact=True,
        flexible_whitespace=True,
    )
    primary_pattern = build_alternation(
        pack.primary_anchors,
        auto_escape=True,
        compact=True,
        flexible_whitespace=True,
    )
    secondary_pattern = build_alternation(
        pack.secondary_tokens,
        auto_escape=True,
        compact=True,
        flexible_whitespace=True,
    )
    veto_pattern = build_alternation(
        pack.veto_signals,
        auto_escape=True,
        compact=True,
        flexible_whitespace=True,
    )

    return CompiledExhibitPack(
        pack_id=pack.pack_id,
        title_pattern=title_pattern,
        primary_pattern=primary_pattern,
        secondary_pattern=secondary_pattern,
        veto_pattern=veto_pattern,
        title_window_lines=pack.title_window_lines,
    )


def _get_compiled_pack(pack_id: str, pack: ExhibitPack) -> CompiledExhibitPack:
    """Get cached compiled pack or compile on first access."""
    if pack_id not in _PACK_COMPILE_CACHE:
        _PACK_COMPILE_CACHE[pack_id] = _compile_pack(pack)
    return _PACK_COMPILE_CACHE[pack_id]


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


__all__ = [
    "PROBE_LINE_BOUND",
    "ExhibitProbeMatch",
    "CompiledExhibitPack",
    "DESIGNATION_RE",
    "is_shielded_by_toc",
    "probe_exhibit_header",
    "_compile_pack",
    "_get_compiled_pack",
]
