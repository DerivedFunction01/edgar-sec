"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations
import re
from edgar_sec.engine.tables.extraction.separators.summary_separator import (
    SummarySeparatorResult,
)

from edgar_sec.engine.tables.extraction.evidence.form.admission_evidence import (
    apply_admissions,
)
from edgar_sec.engine.tables.extraction.seats.aoci_gate import (
    aoci_gate_detail,
    component_grid,
)
from edgar_sec.engine.tables.extraction.separators.combined_operations_separator_evidence import (
    failing_combined_operations_separator_outcome,
    location_refusal_detail,
)
from edgar_sec.engine.tables.extraction.form_specs.form_signal_specs import (
    SEPARATOR_EXEMPTIONS,
    SUMMARY_SEPARATOR_SPECS_BY_ID,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence import (
    failing_goodwill_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_evidence import (
    failing_goodwill_foreign_separator_outcome,
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
    VETO_POINTS,
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
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_COMPOSITION_TWIN,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    CONTAINMENT_EDGES,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.cascade.stamped_gates import apply_stamped_gates
from edgar_sec.engine.tables.extraction.form_specs.core_form_specs import (
    SUMMARY_SEPARATOR_FORM_EXEMPTIONS,
)
from edgar_sec.engine.tables.extraction.seats.primary_gate import (
    GATE_SETS,
    cash_flow_grantor_veto_scoped,
    cash_flow_lead_veto_scoped,
    section_presence,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    hard_veto_form_exemption,
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


_SEP5_STAMP = "mda_financing_operating_rows11"
_SEP5_TITLE_RE = re.compile(r"statements? of cash flows", re.IGNORECASE)


def _sep5_criterion_holds(geometry) -> bool:
    """Sep-5 criterion form (cash_flow, priced): title leg and presence leg.
    The stamp rule's verdict is suppressed when both legs hold.
    """
    titles = " ".join(
        t for t in (geometry.lead_title or "", geometry.note_title or "") if t
    )
    if not _SEP5_TITLE_RE.search(titles):
        return False
    presence = section_presence(geometry.stubs, "cash_flow")
    return all(presence[s] for s in GATE_SETS["cash_flow"])
def _composition_outcomes(
    geometry: GeometryText,
) -> tuple[frozenset[str], frozenset[str]]:
    """Families whose composition twin passed / failed here."""
    passed: set[str] = set()
    failed: set[str] = set()
    for outcome in geometry.form_tests:
        if outcome.kind != TEST_COMPOSITION_TWIN:
            continue
        if outcome.passed:
            passed.add(outcome.family)
        else:
            failed.add(outcome.family)
    return frozenset(passed), frozenset(failed - passed)


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
    # Priced scoping (balance_sheet): a hard hit in either
    # channel reads term context the table's own complete
    # sections outweigh; it does not bar a geometry whose own
    # stubs carry every necessary balance_sheet section (the
    # primary gate's completeness, read at geometry level).
    if "balance_sheet" in hard_vetoed:
        presence = section_presence(geometry.stubs, "balance_sheet")
        if all(presence[s] for s in ("assets", "liabilities", "equity")):
            del hard_vetoed["balance_sheet"]
    # Priced scoping (cash_flow): the balance_sheet scoping
    # generalized — a lead-channel-only hard hit does not bar
    # cash_flow when the geometry's own stubs prove the
    # statement in one of the primary gate's shapes (full
    # section presence, exactly financing missing, or the
    # supplemental schedule identity). A body hit still bars.
    if "cash_flow" in hard_vetoed:
        by_channel = term_veto_hits_by_channel(geometry).get("cash_flow", {})
        hard_channels = by_channel.get("hard", {})
        if hard_channels and set(hard_channels) == {"lead"}:
            if cash_flow_lead_veto_scoped(geometry):
                del hard_vetoed["cash_flow"]
    # Priced scoping (cash_flow, grantor): a remaining hard
    # tier in either channel is scoped when own-stub presence
    # is exactly the spine pair and the bullion marker fires
    # (a bullion-only grantor trust has no middle sections).
    if "cash_flow" in hard_vetoed and cash_flow_grantor_veto_scoped(geometry):
        del hard_vetoed["cash_flow"]
    if hard_vetoed:
        for family, term in hard_vetoed.items():
            if family in scores:
                scores = append_note(scores, family, "veto", f"hard:{term}")
    # Form-conditioned hard-veto exemption (greenfield
    # intangibles packet): an exempted hit whose named form
    # test passed unbars the family, at the scored price.
    for family, term in list(hard_vetoed.items()):
        form_tests = hard_veto_form_exemption(family, term)
        if form_tests is None:
            continue
        passed = {o.test_id for o in geometry.form_tests if o.passed}
        if not any(t in passed for t in form_tests):
            continue
        del hard_vetoed[family]
        score = scores.get(family)
        if score is None:
            continue
        if any(
            e.channel == "veto" and e.detail.startswith("term:") for e in score.evidence
        ):
            scores = append_note(scores, family, "veto", f"exempt:{term}")
        else:
            channels = dict(score.by_channel)
            channels["veto"] = channels.get("veto", 0.0) - VETO_POINTS
            scores = dict(scores)
            scores[family] = FamilyScore(
                family,
                max(score.total - VETO_POINTS, 0.0),
                channels,
                score.evidence + (ClaimEvidence("veto", f"term:{term}", -VETO_POINTS),),
            )
    ranked = sorted(scores.values(), key=lambda s: -s.total)
    claims: list[str] = []
    contested: list[str] = []
    explained_all: dict[str, float] = {}
    explained_by: dict[str, dict[str, float]] = {}
    # Composition bar (priced, inventory Addendum 8): a claimant
    # whose composition twin passed is not barred by foreign mass
    # from a family whose composition twin failed on this geometry.
    comp_passed, comp_failed = _composition_outcomes(geometry)
    foreign_scores = scores
    if comp_passed and comp_failed:
        foreign_scores = {
            family: (
                FamilyScore(family, 0.0, {}, sc.evidence)
                if family in comp_failed
                else sc
            )
            for family, sc in scores.items()
        }
    for candidate in ranked:
        if candidate.family in hard_vetoed:
            continue
        if candidate.total < CLAIM_FLOOR:
            continue
        if candidate.family in comp_passed and comp_failed:
            foreign, explained = _explained_foreign(
                candidate.family, foreign_scores, edges
            )
            scores = append_note(
                scores,
                candidate.family,
                "gate",
                "composition-failed foreign excluded",
            )
        else:
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
    # AOCI component-grid seat (priced): a geometry carrying the
    # family's component-grid form seats aoci_rollforward even
    # when signature dominance or a protective hard veto bars
    # the scored claim — the form test is aoci_gate's, and its
    # movement/column arms keep other families' walks and full
    # equity statements out.
    if "aoci_rollforward" not in claims and component_grid(geometry):
        scores = seat_at_floor(
            scores, "aoci_rollforward", "aoci component-grid seat", CLAIM_FLOOR
        )
        claims.append("aoci_rollforward")
        reach.append("aoci_rollforward")
    # Combined operations separator gate (priced): a
    # combined_operations_ci claim is refused when the stamped
    # separator outcome fired. It binds after the seat-at-floor
    # channel — this family's seat can admit a claim its typed
    # core refuses — where the sibling separators bind earlier.
    if "combined_operations_ci" in claims:
        fired = failing_combined_operations_separator_outcome(geometry.form_tests)
        if fired is None:
            refusal = location_refusal_detail(geometry)
            if refusal is not None:
                claims.remove("combined_operations_ci")
                if "combined_operations_ci" in contested:
                    contested.remove("combined_operations_ci")
                scores = append_note(scores, "combined_operations_ci", "gate", refusal)
        if fired is not None:
            claims.remove("combined_operations_ci")
            if "combined_operations_ci" in contested:
                contested.remove("combined_operations_ci")
            scores = append_note(scores, "combined_operations_ci", "gate", fired.detail)
    # Goodwill separator gate (priced): a goodwill_rollforward
    # claim is refused when the stamped separator outcome fired.
    # It binds after the seat-at-floor channel — this family's
    # measure-set seat can admit a claim its separator refuses —
    # where the sibling separators bind earlier.
    if "goodwill_rollforward" in claims:
        fired = failing_goodwill_separator_outcome(geometry.form_tests)
        if fired is not None:
            claims.remove("goodwill_rollforward")
            if "goodwill_rollforward" in contested:
                contested.remove("goodwill_rollforward")
            scores = append_note(scores, "goodwill_rollforward", "gate", fired.detail)
    # Goodwill foreign-subject separator gate (priced): a
    # goodwill_rollforward claim is refused when the stamped
    # foreign-subject separator outcome fired — the geometry's
    # stub/header zone binds a foreign walked subject and
    # goodwill is not a bound subject of that zone. It binds
    # after the seat-at-floor channel, beside the allocation
    # separator gate above.
    if "goodwill_rollforward" in claims:
        fired = failing_goodwill_foreign_separator_outcome(geometry.form_tests)
        if fired is not None:
            claims.remove("goodwill_rollforward")
            if "goodwill_rollforward" in contested:
                contested.remove("goodwill_rollforward")
            scores = append_note(scores, "goodwill_rollforward", "gate", fired.detail)
    if scopes:
        kept, kept_contested = apply_section_refusals(
            claims, contested, geometry, scopes
        )
        claims, contested = kept, kept_contested
    # S1 separator gate: a fired statement-summary rule denies
    # every claim (S1 pricing covers), except a spared family:
    # one whose fired rules are a subset of its
    # SEPARATOR_EXEMPTIONS entry, or one named in
    # SUMMARY_SEPARATOR_FORM_EXEMPTIONS with a companion pass.
    _sep = geometry.summary_separator
    if (
        _sep is not None
        and _SEP5_STAMP in _sep.rules
        and "cash_flow" in claims
        and _sep5_criterion_holds(geometry)
    ):
        _remaining = tuple(r for r in _sep.rules if r != _SEP5_STAMP)
        _sub = tuple(
            dict.fromkeys(
                SUMMARY_SEPARATOR_SPECS_BY_ID[r].sub_mass
                for r in _remaining
                if r in SUMMARY_SEPARATOR_SPECS_BY_ID
            )
        )
        if _remaining and not _sub:
            _sub = _sep.sub_masses
        object.__setattr__(
            geometry,
            "summary_separator",
            SummarySeparatorResult(rules=_remaining, sub_masses=_sub),
        )
    separator = geometry.summary_separator
    if separator is not None and separator.fired and claims:
        fired_rules = frozenset(separator.rules)
        passed = {o.test_id for o in geometry.form_tests if o.passed}
        spared = tuple(
            family
            for family in claims
            if (
                family in SEPARATOR_EXEMPTIONS
                and fired_rules <= frozenset(SEPARATOR_EXEMPTIONS[family])
            )
            or any(
                t in passed for t in SUMMARY_SEPARATOR_FORM_EXEMPTIONS.get(family, ())
            )
        )
        # Tax precedence (priced): a tax claim at the gate is a
        # seat admission; it survives a non-NONGAAP fire.
        keep_tax = (
            "tax_reconciliation" in claims
            and "NONGAAP-SUMMARY" not in separator.sub_masses
        )
        # Charges exemption (priced): a restructuring claim whose
        # gate pass came through the charges form is a seat
        # admission; it survives the summary fire — the charges
        # specimen's only filed form is often the summary instance.
        keep_charges = "restructuring" in claims and any(
            ev.channel == "gate" and ev.detail.startswith("restructuring charges:")
            for ev in scores["restructuring"].evidence
        )
        kept = list(spared)
        if keep_tax and "tax_reconciliation" not in kept:
            kept.append("tax_reconciliation")
        if keep_charges and "restructuring" not in kept:
            kept.append("restructuring")
        removed = tuple(f for f in claims if f not in kept)
        claims = [f for f in claims if f in kept]
        contested = [f for f in contested if f in kept]
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
        for family in spared:
            kept_score = scores[family]
            scores[family] = FamilyScore(
                kept_score.family,
                kept_score.total,
                dict(kept_score.by_channel),
                kept_score.evidence
                + (
                    ClaimEvidence(
                        "gate",
                        f"summary separator exempted: {separator.detail}",
                        0.0,
                    ),
                ),
            )
        if keep_tax:
            gated = scores["tax_reconciliation"]
            scores["tax_reconciliation"] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (
                    ClaimEvidence(
                        "gate",
                        f"summary separator: {separator.detail}; tax seat precedence",
                        0.0,
                    ),
                ),
            )
        if keep_charges:
            gated = scores["restructuring"]
            scores["restructuring"] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (
                    ClaimEvidence(
                        "gate",
                        f"summary separator: {separator.detail}; charges seat exemption",
                        0.0,
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
