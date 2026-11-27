"""Spanning veto pass: set-level refusals over gate-final
claims for the Round-3 P1 spanning-class packets. Legs read
the final competition results, as priced.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_SIGNATURE_ABSENCE,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    stub_key,
)
from edgar_sec.engine.tables.extraction.seats.primary_gate import (
    statement_clusters,
)
from edgar_sec.engine.tables.extraction.vetoes.spanning_veto_specs import (
    BS_FAMILY,
    BS_FILING_RELATIVE_FLOOR,
    CF_DOMINANCE_RATIO,
    CF_FAMILY,
    LEG_BS_FILING_RELATIVE,
    LEG_CF_DOMINANCE,
    LEG_CF_SIGNATURE,
)


def _cf_dominance_fires(result) -> bool:
    """The claim's score under 1.25x its best live rival's score."""
    own = result.scores.get(CF_FAMILY)
    if own is None:
        return False
    best_rival = max(
        (
            s.total
            for f, s in result.scores.items()
            if f != CF_FAMILY and f in result.claims
        ),
        default=0.0,
    )
    return own.total < CF_DOMINANCE_RATIO * best_rival


def _cf_signature_fires(geometry) -> bool:
    """The stamped signature-absence outcome did not pass."""
    for outcome in geometry.form_tests:
        if outcome.family == CF_FAMILY and outcome.kind == TEST_SIGNATURE_ABSENCE:
            return not outcome.passed
    return False


def _cf_signature_passes(geometry) -> bool:
    """A passing stamped signature-absence outcome."""
    for outcome in geometry.form_tests:
        if outcome.family == CF_FAMILY and outcome.kind == TEST_SIGNATURE_ABSENCE:
            return bool(outcome.passed)
    return False


def _bs_carries_closing_total(geometry) -> bool:
    """The geometry carries the statement's combined closing
    total stub (total liabilities and <equity form>): it is the
    statement's own tail, not a single-caption fragment."""
    return any(
        stub_key(stub).startswith("total liabilities and") for stub in geometry.stubs
    )


def _bs_filing_relative_fires(result, filing_top) -> bool:
    """The claim's score under 0.4x the filing's top score."""
    own = result.scores.get(BS_FAMILY)
    if own is None or filing_top <= 0.0:
        return False
    return own.total < BS_FILING_RELATIVE_FLOOR * filing_top


def _filing_top(results) -> float:
    """The filing's strongest claimed balance_sheet score."""
    return max(
        (
            result.scores[BS_FAMILY].total
            for result in results
            if BS_FAMILY in result.claims and result.scores.get(BS_FAMILY)
        ),
        default=0.0,
    )


def _fired_legs(geometries, results, index, filing_top, clusters):
    """Every priced leg firing on one claimed geometry."""
    result = results[index]
    legs = []
    if CF_FAMILY in result.claims:
        if _cf_dominance_fires(result):
            legs.append((CF_FAMILY, LEG_CF_DOMINANCE))
        # The signature read at statement-cluster scope: the
        # leg fires only when no cluster member carries a
        # passing signature-absence outcome, so a fragment of
        # a signature-carrying statement is not refused for
        # its own stubs alone.
        if _cf_signature_fires(geometries[index]) and not any(
            _cf_signature_passes(geometries[member]) for member in clusters[index]
        ):
            legs.append((CF_FAMILY, LEG_CF_SIGNATURE))
    if (
        BS_FAMILY in result.claims
        and not _bs_carries_closing_total(geometries[index])
        and _bs_filing_relative_fires(result, filing_top)
    ):
        legs.append((BS_FAMILY, LEG_BS_FILING_RELATIVE))
    return tuple(legs)


def apply_spanning_vetoes(geometries, results):
    """Final pass: remove packet-family claims firing any leg.

    Firings read the input results only, so removals never
    change another firing.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    filing_top = _filing_top(results)
    clusters = statement_clusters(geometries)
    fired = {}
    for index, result in enumerate(results):
        legs = _fired_legs(geometries, results, index, filing_top, clusters)
        for family, leg in legs:
            fired.setdefault(index, {}).setdefault(family, []).append(leg)
    if not fired:
        return list(results)
    out = []
    for index, result in enumerate(results):
        hit = fired.get(index)
        if not hit:
            out.append(result)
            continue
        scores = dict(result.scores)
        for family, legs in hit.items():
            score = scores.get(family)
            if score is not None:
                detail = "spanning veto: " + ", ".join(legs)
                scores[family] = FamilyScore(
                    score.family,
                    score.total,
                    dict(score.by_channel),
                    score.evidence + (ClaimEvidence("gate", detail, 0.0),),
                )
        out.append(
            CompetitionResult(
                claims=tuple(f for f in result.claims if f not in hit),
                contested=tuple(f for f in result.contested if f not in hit),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family not in hit),
            )
        )
    return out
