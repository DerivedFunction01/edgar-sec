"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations

import math

from edgar_sec.engine.tables.extraction.admission_evidence import apply_admissions
from edgar_sec.engine.tables.extraction.aoci_gate import aoci_gate_detail
from edgar_sec.engine.tables.extraction.balance_sheet_separator_evidence import (
    fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.cash_flow_separator_evidence import (
    apply_cash_flow_assignment,
    fired_separator_outcome as fired_cash_flow_separator_outcome,
)
from edgar_sec.engine.tables.extraction.credit_separator_evidence import (
    fired_separator_outcome as fired_credit_separator_outcome,
)
from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome,
)
from edgar_sec.engine.tables.extraction.core_form_specs import CORE_FORM_SPECS
from edgar_sec.engine.tables.extraction.derivatives_evidence import (
    DerivativesText,
    _term_pattern as _term_pattern,
    derivatives_subject_for_geometry,
    evaluate_derivatives_evidence,
)
from edgar_sec.engine.tables.extraction.genre_seat import (
    apply_section_refusals,
    geometry_refusal,
)
from edgar_sec.engine.tables.extraction.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
    _explained_foreign,
    score_geometry,
)
from edgar_sec.engine.tables.extraction.geometry_text import (
    GeometryText,
    geometry_text_from_table as geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.section_gate import ScopeRow
from edgar_sec.engine.tables.extraction.form_test_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    TAX_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.input_class_evidence import (
    apply_input_class_seat,
)
from edgar_sec.engine.tables.extraction.pension_evidence import (
    PENSION_ANCHOR_SPECS,
    PensionText,
    evaluate_pension_anchor,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    failing_pension_routed_outcome,
)
from edgar_sec.engine.tables.extraction.combined_operations_separator_evidence import (
    apply_combined_operations_assignment,
    failing_combined_operations_separator_outcome,
)
from edgar_sec.engine.tables.extraction.labor_evidence import (
    apply_labor_seat,
)
from edgar_sec.engine.tables.extraction.seat_floor_evidence import (
    apply_seat_floor,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.primary_gate import apply_primary_gate
from edgar_sec.engine.tables.extraction.comprehensive_income_separator_evidence import (
    apply_comprehensive_income_assignment,
)
from edgar_sec.engine.tables.extraction.equity_separator_evidence import (
    apply_equity_assignment,
)
from edgar_sec.engine.tables.extraction.income_statement_setlevel_evidence import (
    apply_income_statement_assignment,
)
from edgar_sec.engine.tables.extraction.stock_comp_separator_evidence import (
    apply_stock_comp_assignment,
    fired_separator_outcome as fired_stock_comp_separator_outcome,
)
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_BALANCE_SHEET_SEPARATOR,
    TEST_CASH_FLOW_SEPARATOR,
    TEST_CREDIT_SEPARATOR,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR,
    TEST_CORE_FORM,
    TEST_EPS_DETECTOR,
    TEST_EQUITY_SEPARATOR,
    TEST_PENSION_ROUTED,
    TEST_STOCK_COMP_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.term_vetoes import term_veto_hits
from edgar_sec.engine.tables.extraction.signature_profiles import (
    CONTAINMENT_EDGES,
    INHERITANCE_FACTORS,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
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


def _ladder_direction(
    geometry: GeometryText,
    ladder_terms: tuple[LadderTerm, ...],
) -> float:
    """Signed debt/lease evidence: positive leans lease, from the edge."""
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    direction = 0.0
    for spec in ladder_terms:
        if spec.term in text:
            direction += math.log(
                (spec.support_lease + 1.0) / (spec.support_debt + 1.0)
            )
    return direction


def _seat_at_floor(
    scores: dict[str, FamilyScore], family: str, detail: str
) -> dict[str, FamilyScore]:
    """Seat one family at CLAIM_FLOOR via the gate channel."""
    existing = scores.get(family)
    if existing is not None and existing.total >= CLAIM_FLOOR:
        return scores
    base = existing.total if existing is not None else 0.0
    lift = CLAIM_FLOOR - base
    channels = dict(existing.by_channel) if existing is not None else {}
    channels["gate"] = channels.get("gate", 0.0) + lift
    evidence = existing.evidence if existing is not None else ()
    note = ClaimEvidence("gate", detail, lift)
    seated = FamilyScore(family, CLAIM_FLOOR, channels, evidence + (note,))
    return {**scores, family: seated}


def _append_note(
    scores: dict[str, FamilyScore], family: str, channel: str, detail: str
) -> dict[str, FamilyScore]:
    """Append a zero-point note to one family's trail."""
    score = scores[family]
    return {
        **scores,
        family: FamilyScore(
            family,
            score.total,
            dict(score.by_channel),
            score.evidence + (ClaimEvidence(channel, detail, 0.0),),
        ),
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
    if hard_vetoed:
        for family, term in hard_vetoed.items():
            if family in scores:
                scores = _append_note(scores, family, "veto", f"hard:{term}")
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
    # Cure 2 (ladder attribution): the map's priced edge terms
    # decide debt vs lease before the pair stays contested.
    attributed: list[str] = []
    if "debt_maturity" in claims and "lease_maturity" in claims:
        direction = _ladder_direction(geometry, ladder_terms)
        loser = None
        if direction >= LADDER_MARGIN:
            loser = "debt_maturity"
        elif direction <= -LADDER_MARGIN:
            loser = "lease_maturity"
        if loser is not None:
            claims.remove(loser)
            attributed.append(loser)
            if loser in contested:
                contested.remove(loser)
            if len(contested) < 2:
                contested = []
    # Cure 2, single-claim arm: a decisive edge direction against
    # a lone ladder claim contests or flips it (priced arms).
    if LADDER_SINGLE_MODE != "off":
        ladder_claims = [f for f in claims if f in ("debt_maturity", "lease_maturity")]
        if len(ladder_claims) == 1:
            holder = ladder_claims[0]
            other = "lease_maturity" if holder == "debt_maturity" else "debt_maturity"
            direction = _ladder_direction(geometry, ladder_terms)
            opposed = (
                direction >= LADDER_MARGIN
                if holder == "debt_maturity"
                else direction <= -LADDER_MARGIN
            )
            if opposed and other in scores:
                if LADDER_SINGLE_MODE == "flip":
                    claims.remove(holder)
                    claims.append(other)
                    attributed.append(holder)
                elif not contested:
                    claims.append(other)
                    contested = [holder, other]
    # Cure 6 (derivatives gate): a derivatives claim requires U/A
    # evidence in the geometry itself; the gate is registry data
    # (form_test_specs.DERIVATIVES_EVIDENCE_SPECS), priced on the
    # The measured evidence-class split: no-evidence claims are the
    # false mass.
    deriv_spec = DERIVATIVES_EVIDENCE_SPECS.get("derivatives_hedging")
    deriv_evidence = (
        evaluate_derivatives_evidence(
            DerivativesText.from_geometry(geometry), deriv_spec
        )
        if deriv_spec is not None
        else None
    )
    if (
        deriv_evidence is not None
        and not deriv_evidence.admitted
        and "derivatives_hedging" in claims
    ):
        claims.remove("derivatives_hedging")
        if "derivatives_hedging" in contested:
            contested.remove("derivatives_hedging")
        scores = _append_note(
            scores,
            "derivatives_hedging",
            "gate",
            f"derivatives: {deriv_evidence.detail}",
        )
    # Cure 7 (derivatives subject gate): a derivatives claim also
    # requires the rank-1 subject verdict — derivative evidence in
    # the geometry's own framing, not only its body content.
    deriv_subject = (
        derivatives_subject_for_geometry(geometry) if deriv_spec is not None else None
    )
    if (
        deriv_subject is not None
        and not deriv_subject.subject
        and "derivatives_hedging" in claims
    ):
        claims.remove("derivatives_hedging")
        if "derivatives_hedging" in contested:
            contested.remove("derivatives_hedging")
        gated = scores["derivatives_hedging"]
        scores = dict(scores)
        scores["derivatives_hedging"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence
            + (
                ClaimEvidence(
                    "gate", f"derivatives subject: {deriv_subject.detail}", 0.0
                ),
            ),
        )
    # Step 8 core-form gate (priced): a claim in a core-form
    # family requires its stamped core-form outcome to pass; an
    # outcome absent or unevaluable never fails the gate.
    for family in CORE_FORM_SPECS:
        if family not in claims:
            continue
        failed = failing_core_form_outcome(geometry.form_tests, family, TEST_CORE_FORM)
        if failed is None:
            continue
        claims.remove(family)
        if family in contested:
            contested.remove(family)
        scores = _append_note(scores, family, "gate", failed.detail)
    # Balance-sheet separator gate (priced): a balance_sheet
    # claim is refused when the stamped separator outcome fired;
    # an outcome absent or unevaluable never fails the gate.
    if "balance_sheet" in claims:
        fired = fired_separator_outcome(
            geometry.form_tests, "balance_sheet", TEST_BALANCE_SHEET_SEPARATOR
        )
        if fired is not None:
            claims.remove("balance_sheet")
            if "balance_sheet" in contested:
                contested.remove("balance_sheet")
            scores = _append_note(scores, "balance_sheet", "gate", fired.detail)
    # Cash-flow cascade gate (priced): a cash_flow claim is
    # refused when the stamped cascade outcome fired on a
    # claim-local leg; an outcome absent or unevaluable never
    # fails the gate. The set-level legs run at filing level.
    if "cash_flow" in claims:
        fired = fired_cash_flow_separator_outcome(
            geometry.form_tests, "cash_flow", TEST_CASH_FLOW_SEPARATOR
        )
        if fired is not None:
            claims.remove("cash_flow")
            if "cash_flow" in contested:
                contested.remove("cash_flow")
            scores = _append_note(scores, "cash_flow", "gate", fired.detail)
    # Credit separator gate (priced): a credit_losses claim is
    # refused when the stamped separator outcome fired; an
    # outcome absent or unevaluable never fails the gate.
    if "credit_losses_rollforward" in claims:
        fired = fired_credit_separator_outcome(
            geometry.form_tests,
            "credit_losses_rollforward",
            TEST_CREDIT_SEPARATOR,
        )
        if fired is not None:
            claims.remove("credit_losses_rollforward")
            if "credit_losses_rollforward" in contested:
                contested.remove("credit_losses_rollforward")
            scores = _append_note(
                scores, "credit_losses_rollforward", "gate", fired.detail
            )
    # EPS determination gate (priced): an eps_reconciliation
    # claim is refused when the seat's detector fires on the
    # geometry, whatever channel produced the claim; an outcome
    # absent or unevaluable never fails the gate.
    if "eps_reconciliation" in claims:
        fired = failing_core_form_outcome(
            geometry.form_tests, "eps_reconciliation", TEST_EPS_DETECTOR
        )
        if fired is not None:
            claims.remove("eps_reconciliation")
            if "eps_reconciliation" in contested:
                contested.remove("eps_reconciliation")
            scores = _append_note(scores, "eps_reconciliation", "gate", fired.detail)
    # Comprehensive-income separator gate (priced): a claim is
    # refused when the stamped separator outcome fired; an
    # outcome absent or unevaluable never fails the gate.
    if "comprehensive_income" in claims:
        fired = fired_separator_outcome(
            geometry.form_tests,
            "comprehensive_income",
            TEST_COMPREHENSIVE_INCOME_SEPARATOR,
        )
        if fired is not None:
            claims.remove("comprehensive_income")
            if "comprehensive_income" in contested:
                contested.remove("comprehensive_income")
            scores = _append_note(scores, "comprehensive_income", "gate", fired.detail)
    # Equity separator gate (priced): an equity_statement claim
    # is refused when the stamped separator outcome fired; an
    # outcome absent or unevaluable never fails the gate.
    if "equity_statement" in claims:
        fired = fired_separator_outcome(
            geometry.form_tests, "equity_statement", TEST_EQUITY_SEPARATOR
        )
        if fired is not None:
            claims.remove("equity_statement")
            if "equity_statement" in contested:
                contested.remove("equity_statement")
            scores = _append_note(scores, "equity_statement", "gate", fired.detail)
    # Stock-comp separator gate (priced): a stock_comp claim is
    # refused when the stamped separator outcome fired; an
    # outcome absent or unevaluable never fails the gate.
    if "stock_comp_rollforward" in claims:
        fired = fired_stock_comp_separator_outcome(
            geometry.form_tests, "stock_comp_rollforward", TEST_STOCK_COMP_SEPARATOR
        )
        if fired is not None:
            claims.remove("stock_comp_rollforward")
            if "stock_comp_rollforward" in contested:
                contested.remove("stock_comp_rollforward")
            scores = _append_note(
                scores, "stock_comp_rollforward", "gate", fired.detail
            )
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
            scores = _seat_at_floor(
                scores, "derivatives_hedging", deriv_evidence.detail
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
    # Pension core-anchor gate: a pension claim requires a
    # disjunctive ASC 715 core anchor on the geometry's own
    # surfaces, its following prose completing each leg's surface.
    pension_spec = PENSION_ANCHOR_SPECS.get("pension")
    if pension_spec is not None and "pension" in claims:
        pension_evidence = evaluate_pension_anchor(
            PensionText.from_geometry(geometry), pension_spec
        )
        if not pension_evidence.admitted:
            claims.remove("pension")
            if "pension" in contested:
                contested.remove("pension")
            gated = scores["pension"]
            scores = dict(scores)
            scores["pension"] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (ClaimEvidence("gate", f"pension: {pension_evidence.detail}", 0.0),),
            )
    # Pension routed separator gate (priced): a surviving pension
    # claim requires the stamped routed-separator outcome to
    # pass; an outcome absent or unevaluable never fails it.
    if "pension" in claims:
        routed_failed = failing_pension_routed_outcome(
            geometry.form_tests, "pension", TEST_PENSION_ROUTED
        )
        if routed_failed is not None:
            claims.remove("pension")
            if "pension" in contested:
                contested.remove("pension")
            scores = _append_note(scores, "pension", "gate", routed_failed.detail)
    # Ruling 18 seat (tax_reconciliation): the priced statutory-
    # anchor conjunction replaces the family's claim path — a
    # scored claim is displaced, the seat alone decides claimage.
    tax_spec = TAX_EVIDENCE_SPECS.get("tax_reconciliation")
    if tax_spec is not None:
        if "tax_reconciliation" in claims:
            claims.remove("tax_reconciliation")
            if "tax_reconciliation" in contested:
                contested.remove("tax_reconciliation")
            scores = _append_note(
                scores,
                "tax_reconciliation",
                "gate",
                "tax seat displaces scored claim",
            )
        # Seat precedence: the seat outranks the recorded hard
        # term in its precedence set; any other term bars it.
        if hard_vetoed.get("tax_reconciliation") in (
            None,
            *tax_spec.seat_veto_precedence_terms,
        ):
            tax_outcome = next(
                (o for o in geometry.form_tests if o.test_id == tax_spec.test_id),
                None,
            )
            if tax_outcome is not None and tax_outcome.passed:
                scores = _seat_at_floor(
                    scores, "tax_reconciliation", tax_outcome.detail
                )
                claims.append("tax_reconciliation")
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
            scores = _append_note(
                scores, "combined_operations_ci", "gate", fired.detail
            )
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


# Inheritance lends a fragment the discounted evidence of the
# nearest preceding claim in its note or section; a note title
# shared with 2+ same-family claims lends that family tie evidence.
def compete_filing(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
    scopes: tuple[ScopeRow, ...] = (),
) -> list[CompetitionResult]:
    """Compete one filing's geometries with context fed back.

    Context lends evidence to unclaimed geometries only; it never
    overrides a geometry's own scored claim.
    """
    results = [
        compete(g, terms, edges, ladder_terms=ladder_terms, scopes=scopes)
        for g in geometries
    ]
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
    # Comprehensive-income ranking pass (set-level, priced):
    # core-completeness ranking over the filing's formed
    # candidate set; it only removes claims.
    results = apply_comprehensive_income_assignment(geometries, results)
    # Cash-flow assignment pass (set-level, priced): winner
    # takes all over the filing's formed cash_flow candidate set;
    # it only removes claims, so the primary gate stays final.
    results = apply_cash_flow_assignment(geometries, results)
    # Equity assignment pass (set-level, priced): joint
    # assignment over the filing's formed equity candidate set;
    # it only removes claims, so the primary gate stays final.
    results = apply_equity_assignment(geometries, results)
    # Combined operations set-level pass (priced): J1 joint
    # assignment and A1 corekeep adjudication over the filing's
    # complete candidate sets, after inheritance settles claims.
    results = apply_combined_operations_assignment(geometries, results)
    # Income-statement set-level pass (priced): routing,
    # uniqueness, dominant-cluster and ties refusals over the
    # filing's formed candidate set; it only removes claims.
    results = apply_income_statement_assignment(geometries, results)
    # Stock-comp assignment pass (set-level, priced): a claim
    # is refused when a determined other-family seat has seated
    # the same geometry; it only removes claims, so the
    # primary gate stays final.
    results = apply_stock_comp_assignment(geometries, results)
    # Final pass: the primary hard gates refuse claims whose
    # necessary sections are missing over the statement cluster;
    # running last, inheritance cannot resurrect a gated claim.
    return apply_primary_gate(geometries, results)
