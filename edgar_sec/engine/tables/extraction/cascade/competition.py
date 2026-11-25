"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.evidence.form.admission_evidence import (
    apply_admissions,
)
from edgar_sec.engine.tables.extraction.seats.aoci_gate import aoci_gate_detail
from edgar_sec.engine.tables.extraction.separators.combined_operations_separator_evidence import (
    failing_combined_operations_separator_outcome,
)
from edgar_sec.engine.tables.extraction.cascade.competition_gates import (
    apply_core_form_gates,
    apply_derivatives_gates,
    apply_pension_gates,
    apply_tax_seat,
)
from edgar_sec.engine.tables.extraction.seats.genre_seat import (
    apply_section_refusals,
    geometry_refusal,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
    _explained_foreign,
    score_geometry,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.evidence.form.input_class_evidence import (
    apply_input_class_seat,
)
from edgar_sec.engine.tables.extraction.evidence.form.labor_evidence import (
    apply_labor_seat,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.ladder_attribution import (
    apply_ladder_attribution,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.score_trail import (
    append_note,
    seat_at_floor,
)
from edgar_sec.engine.tables.extraction.seats.seat_floor_evidence import (
    apply_seat_floor,
)
from edgar_sec.engine.tables.extraction.seats.section_gate import ScopeRow
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    CONTAINMENT_EDGES,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.cascade.stamped_gates import apply_stamped_gates
from edgar_sec.engine.tables.extraction.seats.primary_gate import section_presence
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    term_veto_hits,
    term_veto_hits_by_channel,
)

# Calibration constants, derivation-priced by the calibration
# harness over the adjudicated corpora; the pin iteration
# re-prices them against the 1B map profile.
CLAIM_FLOOR = 5.0
DOMINANCE_RATIO = 1.25
FOREIGN_ALLOWANCE = 0.25
CORROBORATION_POINTS = 0.75
INHERITANCE_FACTOR = 0.5
INHERITANCE_MAX_DISTANCE = 3
TIE_POINTS = 1.0

# False-claim constants, derivation-priced.
LADDER_MARGIN = 1.0
LADDER_SINGLE_MODE = "contest"
REACH_DOMINANCE = 1.25
REACH_FLOORS = {"pension": 4.0, "deferred_tax": 4.0}
REACH_MIN_STUB_SHARE: dict[str, float] = {
    "pension": 0.5,
    "deferred_tax": 0.5,
}


def compete(
    geometry: GeometryText,
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    scores: dict[str, FamilyScore] | None = None,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
    scopes: tuple[ScopeRow, ...] = (),
) -> CompetitionResult:
    """Issue claims for one geometry under the dominance rule."""
    if geometry_refusal(geometry) is not None:
        return CompetitionResult(claims=(), contested=(), scores={})
    scores = scores if scores is not None else score_geometry(geometry, terms)
    if geometry.closure_closed and scores:
        leader = max(scores.values(), key=lambda s: s.total)
        trail = leader.evidence + (
            ClaimEvidence("closure", "grid closes", CORROBORATION_POINTS),
        )
        scores = dict(scores)
        scores[leader.family] = FamilyScore(
            leader.family,
            leader.total + CORROBORATION_POINTS,
            dict(leader.by_channel),
            trail,
        )
    # Term vetoes, hard tier (Step 6 v2 re-price; owner imposter
    # ruling): a hit removes the family's claim outright. The
    # score stays as foreign mass and carries the veto in its
    # trail; the family is barred from claims, contested pairs,
    # and reach below, and compete_filing re-applies this on
    # every re-compete, so inheritance cannot resurrect it.
    veto_hits = term_veto_hits(geometry)
    hard_vetoed = {
        family: tiers["hard"] for family, tiers in veto_hits.items() if "hard" in tiers
    }
    # Priced scoping (balance_sheet): a lead-channel-only hard
    # hit reads borrowed prose context, not the table; it does
    # not bar a geometry whose own stubs carry every necessary
    # balance_sheet section (the primary gate's completeness,
    # read at geometry level). A body-channel hit still bars.
    if "balance_sheet" in hard_vetoed:
        by_channel = term_veto_hits_by_channel(geometry).get("balance_sheet", {})
        hard_channels = by_channel.get("hard", {})
        if hard_channels and set(hard_channels) == {"lead"}:
            presence = section_presence(geometry.stubs, "balance_sheet")
            if all(presence[s] for s in ("assets", "liabilities", "equity")):
                del hard_vetoed["balance_sheet"]
    if hard_vetoed:
        for family, term in hard_vetoed.items():
            if family in scores:
                scores = append_note(scores, family, "veto", f"hard:{term}")
    ranked = sorted(scores.values(), key=lambda s: -s.total)
    claims: list[str] = []
    contested: list[str] = []
    explained_all: dict[str, float] = {}
    explained_by: dict[str, dict[str, float]] = {}
    for candidate in ranked:
        if candidate.family in hard_vetoed:
            continue
        if candidate.total < CLAIM_FLOOR:
            continue
        foreign, explained = _explained_foreign(candidate.family, scores, edges)
        explained_all.update(explained)
        explained_by[candidate.family] = explained
        if foreign <= FOREIGN_ALLOWANCE:
            claims.append(candidate.family)
        elif candidate.total >= DOMINANCE_RATIO * foreign:
            claims.append(candidate.family)
    if not claims:
        floored = [
            c.family
            for c in ranked
            if c.total >= CLAIM_FLOOR and c.family not in hard_vetoed
        ]
        if len(floored) >= 2:
            top, second = scores[floored[0]].total, scores[floored[1]].total
            if top < DOMINANCE_RATIO * second:
                claims = floored[:2]
                contested = floored[:2]
        if not claims and floored:
            claims = floored[:1]
            contested = floored[:1]
    if len(claims) >= 2:
        top = scores[claims[0]].total
        second = scores[claims[1]].total
        if top < DOMINANCE_RATIO * second:
            contested = claims[:2]
    # Cure 1 + Step 9 AOCI gates: the verdict is aoci_gate's.
    aoci_detail = aoci_gate_detail(claims, scores, geometry)
    if aoci_detail is not None:
        claims.remove("aoci_rollforward")
        if "aoci_rollforward" in contested:
            contested.remove("aoci_rollforward")
        gated = scores["aoci_rollforward"]
        scores = dict(scores)
        scores["aoci_rollforward"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence + (ClaimEvidence("gate", aoci_detail, 0.0),),
        )
    contested, attributed = apply_ladder_attribution(
        claims,
        contested,
        scores,
        geometry,
        ladder_terms,
        margin=LADDER_MARGIN,
        single_mode=LADDER_SINGLE_MODE,
    )
    scores, deriv_evidence, deriv_subject = apply_derivatives_gates(
        claims, contested, scores, geometry
    )
    scores = apply_core_form_gates(claims, contested, scores, geometry)
    # Stamped-outcome gates (priced): the separator and detector
    # gates refuse a claim whose stamped outcome fired.
    scores = apply_stamped_gates(claims, contested, scores, geometry)
    # Cures 4+5 (claim-reach): subject-evidence presence claims
    # an otherwise unclaimed geometry at declared provenance.
    reach: list[str] = []
    if not claims:
        best_other = max(
            (s.total for f, s in scores.items() if f not in REACH_FLOORS),
            default=0.0,
        )
        for family, floor in REACH_FLOORS.items():
            if family in hard_vetoed:
                continue
            score = scores.get(family)
            if score is None:
                continue
            stub_share = (
                score.by_channel.get("stub", 0.0) / score.total
                if score.total > 0
                else 0.0
            )
            if stub_share < REACH_MIN_STUB_SHARE.get(family, 0.0):
                continue
            if score.total >= floor and score.total >= (REACH_DOMINANCE * best_other):
                claims.append(family)
                reach.append(family)
        # Derivatives reach: strong U/A evidence (a subject-named
        # instrument, a period listing, an A-frontier form) claims
        # an otherwise unclaimed geometry whose signature score
        # alone stays under the floor — the plain-listing misses.
        if (
            not claims
            and "derivatives_hedging" not in hard_vetoed
            and deriv_evidence is not None
            and deriv_evidence.admitted
            and deriv_evidence.strong
            and deriv_subject is not None
            and deriv_subject.subject
        ):
            scores = seat_at_floor(
                scores, "derivatives_hedging", deriv_evidence.detail, CLAIM_FLOOR
            )
            claims.append("derivatives_hedging")
            reach.append("derivatives_hedging")
    # Ruling 18 seat (valuation_model_assumptions): the priced
    # input-class reader seats the family on its grid text; at
    # least 3 canonical classes claim, no refusal condition.
    claims, scores = apply_input_class_seat(
        geometry,
        claims,
        scores,
        hard_vetoed,
        floor=CLAIM_FLOOR,
        score_type=FamilyScore,
        evidence_type=ClaimEvidence,
    )
    # Step 7 admission (priced): the core-signal reads seat
    # claims the signature competition cannot reach.
    admission, scores = apply_admissions(
        geometry.form_tests,
        claims,
        scores,
        hard_vetoed,
        floor=CLAIM_FLOOR,
        score_type=FamilyScore,
        evidence_type=ClaimEvidence,
    )
    scores = apply_pension_gates(claims, contested, scores, geometry)
    scores = apply_tax_seat(
        claims, contested, scores, geometry, hard_vetoed, CLAIM_FLOOR
    )
    # S6-B labor seat: the priced bargaining-unit signature
    # (labor_form evidence, stamped at the form-test stage) seats
    # labor_contracts at the claim floor — registry data in
    # labor_specs.LABOR_EVIDENCE_SPECS.
    scores = apply_labor_seat(geometry, scores, claims, reach, hard_vetoed, CLAIM_FLOOR)
    # R1 seat-at-floor (claim-path pricing): the registered
    # families' priced seat tests seat them at the claim floor
    # — registry data in seat_floor_specs.SEAT_FLOOR_SPECS.
    scores = apply_seat_floor(geometry, scores, claims, hard_vetoed, floor=CLAIM_FLOOR)
    # Combined operations separator gate (priced): a
    # combined_operations_ci claim is refused when the stamped
    # separator outcome fired. It binds after the seat-at-floor
    # channel — this family's seat can admit a claim its typed
    # core refuses — where the sibling separators bind earlier.
    if "combined_operations_ci" in claims:
        fired = failing_combined_operations_separator_outcome(geometry.form_tests)
        if fired is not None:
            claims.remove("combined_operations_ci")
            if "combined_operations_ci" in contested:
                contested.remove("combined_operations_ci")
            scores = append_note(scores, "combined_operations_ci", "gate", fired.detail)
    if scopes:
        kept, kept_contested = apply_section_refusals(
            claims, contested, geometry, scopes
        )
        claims, contested = kept, kept_contested
    # S1 separator gate: a fired statement-summary rule denies
    # every claim — the priced mass is a composition (a summary
    # of a statement), claimed by no family (S1 pricing covers).
    separator = geometry.summary_separator
    if separator is not None and separator.fired and claims:
        removed, claims, contested = tuple(claims), [], []
        reach = [family for family in reach if family not in removed]
        scores = dict(scores)
        for family in removed:
            gated = scores[family]
            scores[family] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (
                    ClaimEvidence(
                        "gate", f"summary separator: {separator.detail}", 0.0
                    ),
                ),
            )
    role = (
        "continuation"
        if geometry.is_fragment
        else "head"
        if geometry.caption.strip()
        else "standalone"
    )
    grouped: list[ClaimGroup] = []
    for family in claims:
        score = scores[family]
        state = (
            "contested"
            if family in contested
            else "admission"
            if family in admission
            else "reach"
            if family in reach
            else "claimed"
        )
        grouped.append(
            ClaimGroup(
                family,
                score.total,
                state,
                role,
                dict(score.by_channel),
                tuple(e.detail for e in score.evidence if e.channel == "veto"),
                sum(explained_by.get(family, {}).values()),
            )
        )
    for family in attributed:
        score = scores[family]
        grouped.append(
            ClaimGroup(
                family,
                score.total,
                "attributed",
                role,
                dict(score.by_channel),
                tuple(e.detail for e in score.evidence if e.channel == "veto"),
                sum(explained_by.get(family, {}).values()),
            )
        )
    return CompetitionResult(
        claims=tuple(claims),
        contested=tuple(contested),
        scores=scores,
        foreign_explained=explained_all,
        groups=tuple(grouped),
    )
