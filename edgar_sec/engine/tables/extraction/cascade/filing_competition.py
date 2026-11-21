"""Filing-level competition: compete_filing and its context
feedback over one filing's geometries.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.evidence.aro_evidence import (
    apply_aro_assignment,
)
from edgar_sec.engine.tables.extraction.separators.combined_operations_separator_evidence import (
    apply_combined_operations_assignment,
)
from edgar_sec.engine.tables.extraction.cascade.competition import (
    INHERITANCE_FACTOR,
    INHERITANCE_MAX_DISTANCE,
    TIE_POINTS,
    compete,
)
from edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_evidence import (
    apply_comprehensive_income_assignment,
)
from edgar_sec.engine.tables.extraction.separators.equity_separator_evidence import (
    apply_equity_assignment,
)
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import (
    ClaimEvidence,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.evidence.income_statement_setlevel_evidence import (
    apply_income_statement_assignment,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    apply_lease_assignment,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_evidence import (
    apply_ppe_vetoes,
    capture_claim_stages,
)
from edgar_sec.engine.tables.extraction.seats.primary_gate import apply_primary_gate
from edgar_sec.engine.tables.extraction.seats.section_gate import ScopeRow
from edgar_sec.engine.tables.extraction.core.signature_profiles import (
    CONTAINMENT_EDGES,
    INHERITANCE_FACTORS,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_evidence import (
    apply_stock_comp_assignment,
)


# Inheritance lends a fragment the discounted evidence of the
# nearest preceding claim in its note or section; a note title
# shared with 2+ same-family claims lends that family tie evidence.
_ASSIGNMENT_PASSES = (
    apply_comprehensive_income_assignment,
    apply_equity_assignment,
    apply_combined_operations_assignment,
    apply_income_statement_assignment,
    apply_stock_comp_assignment,
    apply_aro_assignment,
    apply_lease_assignment,
)


def compete_filing(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
    scopes: tuple[ScopeRow, ...] = (),
) -> list[CompetitionResult]:
    """Compete one filing's geometries with context fed back;
    context lends to unclaimed geometries only and never
    overrides a geometry's own scored claim."""
    results = [
        compete(g, terms, edges, ladder_terms=ladder_terms, scopes=scopes)
        for g in geometries
    ]
    own_results = list(results)
    claimed_by_title: dict[str, dict[str, int]] = {}
    for geometry, result in zip(geometries, results, strict=True):
        if geometry.note_title and result.claims:
            bucket = claimed_by_title.setdefault(geometry.note_title, {})
            for family in result.claims:
                bucket[family] = bucket.get(family, 0) + 1
    for index, (geometry, result) in enumerate(zip(geometries, results, strict=True)):
        if result.claims:
            continue
        bonus: dict[str, float] = {}
        if geometry.is_fragment:
            for back in range(1, INHERITANCE_MAX_DISTANCE + 1):
                prior_index = index - back
                if prior_index < 0:
                    break
                prior = geometries[prior_index]
                prior_result = results[prior_index]
                if not prior_result.claims:
                    continue
                same_home = (
                    (
                        prior.note_title is not None
                        and prior.note_title == geometry.note_title
                    )
                    or (
                        prior.section_item is not None
                        and prior.section_item == geometry.section_item
                    )
                    or back == 1
                )
                if not same_home:
                    continue
                for family in prior_result.claims:
                    factor = INHERITANCE_FACTORS.get(family, INHERITANCE_FACTOR)
                    inherited = factor * prior_result.scores[family].total
                    bonus[family] = max(bonus.get(family, 0.0), inherited)
                break
        if geometry.note_title:
            for family, count in claimed_by_title.get(geometry.note_title, {}).items():
                if count >= 2:
                    bonus[family] = bonus.get(family, 0.0) + TIE_POINTS
        if not bonus:
            continue
        adjusted: dict[str, FamilyScore] = {}
        for family, score in result.scores.items():
            add = bonus.pop(family, 0.0)
            if add:
                trail = score.evidence + (
                    ClaimEvidence("context", "inherited/tie evidence", add),
                )
                channels = dict(score.by_channel)
                channels["context"] = channels.get("context", 0.0) + add
                adjusted[family] = FamilyScore(
                    family, score.total + add, channels, trail
                )
            else:
                adjusted[family] = score
        for family, add in bonus.items():
            adjusted[family] = FamilyScore(
                family,
                add,
                {"context": add},
                (ClaimEvidence("context", "inherited/tie evidence", add),),
            )
        results[index] = compete(
            geometries[index],
            terms,
            edges,
            scores=adjusted,
            ladder_terms=ladder_terms,
            scopes=scopes,
        )
    stages = capture_claim_stages(own_results, results)
    # Set-level assignment passes (priced): each pass runs over
    # the filing's formed candidate set and only removes claims.
    for apply_assignment in _ASSIGNMENT_PASSES:
        results = apply_assignment(geometries, results)
    # The primary hard gates refuse claims whose necessary
    # sections are missing over the statement cluster; the PPE
    # veto then reads gate-final claims on the captured stage.
    gated = apply_primary_gate(geometries, results)
    return apply_ppe_vetoes(geometries, gated, stages)
