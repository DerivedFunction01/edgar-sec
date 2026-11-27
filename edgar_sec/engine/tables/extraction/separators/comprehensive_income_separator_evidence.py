"""Comprehensive-income separator evidence
(TEST_COMPREHENSIVE_INCOME_SEPARATOR). The routed cascade
over one comprehensive_income candidate: the nine priced
claim-local legs in firing order, plus the ranking pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
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
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE

_HEADER_LINES = 3
_YEAR_RE = YEAR_TOKEN_SEARCH_RE
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


@lru_cache(maxsize=None)
def _spec_index(spec) -> TermIndex:
    """One index over the cascade's term census: the spec's
    stub-key lists by role, the bookend and tax-header phrases,
    and the two single tokens — every entry phrase-kind."""
    entries = []
    for kind, terms in (
        ("walk_begin", spec.walk_begin_terms),
        ("walk_end", spec.walk_end_terms),
        ("oci", spec.oci_terms),
        ("components_total", spec.components_total_terms),
        ("descent", spec.descent_terms),
        ("tax_header", spec.tax_header_phrases),
    ):
        entries += [TermEntry(term, kind) for term in terms]
    entries += [
        TermEntry(term, "equity_host", value=term) for term in spec.equity_host_terms
    ]
    entries += [TermEntry(p, "bookend_begin") for p in _BOOKEND_BEGIN_PHRASES]
    entries += [TermEntry(p, "bookend_end") for p in _BOOKEND_END_PHRASES]
    entries.append(TermEntry(_GUARANTOR_TOKEN, "guarantor"))
    entries.append(TermEntry(_TAX_TOKEN, "tax_token"))
    return TermIndex(entries)


def _kinds_over(spec, texts) -> set:
    """The union of kinds the index finds over the texts."""
    index = _spec_index(spec)
    kinds = set()
    for text in texts:
        kinds |= set(index.scan(text))
    return kinds


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
    """The determined core: walk head, walk tail, OCI element.
    The components schedule is the second determined shape:
    OCI element, walk tail, and a components-total stub."""
    kinds = _kinds_over(spec, stub_keys)
    begin = "walk_begin" in kinds
    end = "walk_end" in kinds
    oci = "oci" in kinds
    if begin and end and oci:
        return True
    total = "components_total" in kinds
    return bool(oci and end and total)


def comprehensive_income_candidate_features(
    text: ComprehensiveIncomeSeparatorText,
    spec: ComprehensiveIncomeSeparatorSpec,
) -> ComprehensiveIncomeCandidateFeatures:
    """Cascade features over the packet text surface."""
    blob = text.stub_blob
    index = _spec_index(spec)
    blob_kinds = set(index.scan(blob))
    bookend_pair = "bookend_begin" in blob_kinds and "bookend_end" in blob_kinds
    header_text = norm(" ".join([*text.caption_stack, *text.headers]))
    header_kinds = set(index.scan(header_text))
    return ComprehensiveIncomeCandidateFeatures(
        row_count=len(text.stubs),
        span_years=len(text.span_years),
        core_complete=_core_complete(text.stub_keys, spec),
        hdr_accumulated=_ACCUMULATED_KEY in text.header_keys,
        bookend_pair=bookend_pair,
        descent="descent" in _kinds_over(spec, text.stub_keys),
        host_equity=(
            len(
                set().union(
                    *(
                        index.scan(stub).get("equity_host", frozenset())
                        for stub in text.norm_stubs
                    )
                )
            )
            >= spec.equity_host_min
        ),
        detail_taxcol=(
            "tax_header" in header_kinds and "tax_token" in header_kinds
        ),
        guarantor=(
            "guarantor" in blob_kinds
            or any(
                "guarantor" in index.scan(norm(cell)) for cell in text.headers
            )
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


def comprehensive_income_components_form(geometry, spec) -> bool:
    """The components-schedule form over a geometry's stubs:
    OCI content totalled to a components total, with no
    walk-begin stub (the statement sibling carries the walk)."""
    stub_keys = frozenset(
        key for key in (stub_key(stub) for stub in geometry.stubs) if len(key) >= 3
    )
    kinds = _kinds_over(spec, stub_keys)
    return bool(
        "oci" in kinds and "components_total" in kinds and "walk_begin" not in kinds
    )


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
