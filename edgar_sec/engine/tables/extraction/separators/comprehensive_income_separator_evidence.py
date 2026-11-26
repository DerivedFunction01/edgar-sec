"""Comprehensive-income separator evidence
(TEST_COMPREHENSIVE_INCOME_SEPARATOR). The routed cascade
over one comprehensive_income candidate: the nine priced
claim-local legs in firing order, plus the ranking pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_specs import (
    COMPREHENSIVE_INCOME_SEPARATOR_SPECS,
    ComprehensiveIncomeSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys,
    norm,
    stub_key,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    HEADER_STOP_TOKENS,
)
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_PATTERN

_HEADER_LINES = 3
_YEAR_RE = re.compile(rf"\b(?:{YEAR_TOKEN_PATTERN})\b")
_ACCUMULATED_KEY = "accumulated"
_TAX_TOKEN = "tax"
_GUARANTOR_TOKEN = "guarantor"
_BOOKEND_BEGIN_PHRASES = ("beginning", "opening balance")
_BOOKEND_END_PHRASES = (
    "ending",
    "closing balance",
    "balance at end",
    "balance at the end",
)


class ComprehensiveIncomeSeparatorText:
    """The packet text surface the cascade reads."""

    def __init__(self, table_text, caption_stack=()):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [tuple(c.strip() for c in ln.split("|")) for ln in lines]
        self.stubs = tuple(row[0] for row in self.rows if row[0])
        self.headers = tuple(
            cell for row in self.rows[:_HEADER_LINES] for cell in row if cell
        )
        self.caption_stack = list(caption_stack or [])
        self.stub_keys = frozenset(
            key for key in (stub_key(stub) for stub in self.stubs) if len(key) >= 3
        )
        self.header_keys = header_keys(self.headers)
        self.norm_stubs = tuple(norm(stub) for stub in self.stubs)
        self.stub_blob = " ".join(self.norm_stubs)
        years = set()
        for zone in (*self.caption_stack, *self.headers):
            years.update(_YEAR_RE.findall(zone))
        self.span_years = frozenset(years)

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class ComprehensiveIncomeCandidateFeatures:
    """One candidate's cascade features and determined-core read."""

    row_count: int
    span_years: int
    core_complete: bool
    hdr_accumulated: bool
    bookend_pair: bool
    descent: bool
    host_equity: bool
    detail_taxcol: bool
    guarantor: bool


def _core_complete(stub_keys: frozenset, spec) -> bool:
    """The determined core: walk head, walk tail, OCI element."""
    begin = any(term in key for key in stub_keys for term in spec.walk_begin_terms)
    end = any(term in key for key in stub_keys for term in spec.walk_end_terms)
    oci = any(term in key for key in stub_keys for term in spec.oci_terms)
    return begin and end and oci


def comprehensive_income_candidate_features(
    text: ComprehensiveIncomeSeparatorText,
    spec: ComprehensiveIncomeSeparatorSpec,
) -> ComprehensiveIncomeCandidateFeatures:
    """Cascade features over the packet text surface."""
    blob = text.stub_blob
    bookend_pair = any(phrase in blob for phrase in _BOOKEND_BEGIN_PHRASES) and any(
        phrase in blob for phrase in _BOOKEND_END_PHRASES
    )
    header_text = norm(" ".join([*text.caption_stack, *text.headers]))
    return ComprehensiveIncomeCandidateFeatures(
        row_count=len(text.rows),
        span_years=len(text.span_years),
        core_complete=_core_complete(text.stub_keys, spec),
        hdr_accumulated=_ACCUMULATED_KEY in text.header_keys,
        bookend_pair=bookend_pair,
        descent=any(
            term in key for key in text.stub_keys for term in spec.descent_terms
        ),
        host_equity=(
            sum(
                1
                for term in spec.equity_host_terms
                if any(term in stub for stub in text.norm_stubs)
            )
            >= spec.equity_host_min
        ),
        detail_taxcol=(
            any(phrase in header_text for phrase in spec.tax_header_phrases)
            and _TAX_TOKEN in header_text
        ),
        guarantor=(
            _GUARANTOR_TOKEN in blob
            or any(_GUARANTOR_TOKEN in norm(cell) for cell in text.headers)
        ),
    )


@dataclass(frozen=True, slots=True)
class ComprehensiveIncomeSeparatorVerdict:
    """The cascade's read: admitted unless a priced leg fires."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def evaluate_comprehensive_income_separator(
    text: ComprehensiveIncomeSeparatorText,
    spec: ComprehensiveIncomeSeparatorSpec,
) -> ComprehensiveIncomeSeparatorVerdict:
    """Fire the claim-local legs in their priced order."""
    if not text.rows:
        return ComprehensiveIncomeSeparatorVerdict(False, False, (), "no grid rows")
    features = comprehensive_income_candidate_features(text, spec)
    legs = []
    if features.row_count > spec.max_rows:
        legs.append(f"rows_gt_{spec.max_rows}")
    if features.span_years >= spec.span_years_min:
        legs.append(f"span_ge_{spec.span_years_min}")
    if not features.core_complete:
        legs.append("core_incomplete")
    if features.hdr_accumulated:
        legs.append("hdr_accumulated")
    if features.bookend_pair and features.hdr_accumulated:
        legs.append("bookend_and_accum")
    if features.descent:
        legs.append("descent")
    if features.host_equity:
        legs.append("host_equity")
    if features.detail_taxcol:
        legs.append("detail_taxcol")
    if features.guarantor and not features.core_complete:
        legs.append("guarantor")
    fired = bool(legs)
    detail = (
        "comprehensive income separator fired: " + ", ".join(legs)
        if fired
        else "comprehensive income separator clear"
    )
    return ComprehensiveIncomeSeparatorVerdict(fired, True, tuple(legs), detail)


def evaluate_form_test_comprehensive_income_separator(table, spec):
    """Stage entry: evaluate the cascade over an assembled table."""
    gate_spec = COMPREHENSIVE_INCOME_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return ComprehensiveIncomeSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    context = table.context
    text = ComprehensiveIncomeSeparatorText.from_rows(
        context.rows, list(context.caption_stack) + list(table.caption.titles)
    )
    return evaluate_comprehensive_income_separator(text, gate_spec)


def comprehensive_income_core_complete_from_geometry(geometry, spec) -> bool:
    """The determined-core read over a claimed geometry's stubs."""
    stub_keys = frozenset(
        key for key in (stub_key(stub) for stub in geometry.stubs) if len(key) >= 3
    )
    return _core_complete(stub_keys, spec)


def apply_comprehensive_income_assignment(geometries, results):
    """Ranking pass: a core-incomplete candidate is eliminated
    when a core-complete sibling candidate stands in the same
    filing; runs after every claim is formed, before the gate.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "comprehensive_income"
    spec = COMPREHENSIVE_INCOME_SEPARATOR_SPECS[family]
    claimed = [i for i, result in enumerate(results) if family in result.claims]
    if len(claimed) < 2:
        return list(results)
    complete = {
        i: comprehensive_income_core_complete_from_geometry(geometries[i], spec)
        for i in claimed
    }
    if not any(complete.values()) or all(complete.values()):
        return list(results)
    detail = (
        "comprehensive income ranking: core-incomplete candidate "
        "ranked below a core-complete sibling"
    )
    out = []
    for i, result in enumerate(results):
        if i not in complete or complete[i]:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores[family]
        scores[family] = FamilyScore(
            score.family,
            score.total,
            dict(score.by_channel),
            score.evidence + (ClaimEvidence("gate", detail, 0.0),),
        )
        out.append(
            CompetitionResult(
                claims=tuple(c for c in result.claims if c != family),
                contested=tuple(c for c in result.contested if c != family),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family != family),
            )
        )
    return out
