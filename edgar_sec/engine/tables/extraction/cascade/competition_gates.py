"""Per-family gate stage of the signature competition: the
derivatives, core-form, pension, and tax-seat gates that
refuse or seat claims after the dominance claiming.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome,
)
from edgar_sec.engine.tables.extraction.form_specs.core_form_specs import (
    CORE_FORM_GATE_FORM_EXEMPTIONS,
    CORE_FORM_SPECS,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.derivatives_evidence import (
    DerivativesText,
    derivatives_subject_for_geometry,
    evaluate_derivatives_evidence,
)
from edgar_sec.engine.tables.extraction.specs.families.derivatives_evidence_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.pension.pension_evidence import (
    PENSION_ANCHOR_SPECS,
    PensionText,
    evaluate_pension_anchor,
    pension_anchor_set,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    failing_pension_routed_outcome,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_CORE_FORM,
    TEST_PENSION_COMBINATION,
    TEST_PENSION_ROUTED,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.score_trail import (
    append_note,
    seat_at_floor,
)
from edgar_sec.engine.tables.extraction.specs.families.tax_evidence_specs import (
    TAX_EVIDENCE_SPECS,
)


def apply_derivatives_gates(claims, contested, scores, geometry):
    """Refuse a derivatives claim its own evidence does not admit.

    Returns the scores plus the evidence and subject reads,
    which the claim-reach stage consumes.
    """
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
        scores = append_note(
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
    return scores, deriv_evidence, deriv_subject


def apply_core_form_gates(claims, contested, scores, geometry):
    """Refuse core-form claims whose stamped outcome failed."""
    # Step 8 core-form gate (priced): a claim in a core-form
    # family requires its stamped core-form outcome to pass; an
    # outcome absent or unevaluable never fails the gate.
    for family in CORE_FORM_SPECS:
        if family not in claims:
            continue
        failed = failing_core_form_outcome(geometry.form_tests, family, TEST_CORE_FORM)
        if failed is None:
            continue
        # Form-conditioned exemption (greenfield intangibles
        # packet): the gate does not refuse a family whose
        # named companion form test passed on this geometry.
        companion = CORE_FORM_GATE_FORM_EXEMPTIONS.get(family)
        if companion is not None and any(
            o.test_id == companion and o.passed for o in geometry.form_tests
        ):
            continue
        claims.remove(family)
        if family in contested:
            contested.remove(family)
        scores = append_note(scores, family, "gate", failed.detail)
    return scores


def apply_pension_gates(claims, contested, scores, geometry):
    """Refuse a pension claim its core anchor or separators fail."""
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
    # Pension separator gates (priced): a surviving pension claim
    # requires each stamped separator outcome to pass; an outcome
    # absent or unevaluable never fails it.
    if "pension" in claims:
        for kind, reader in (
            (TEST_PENSION_ROUTED, failing_pension_routed_outcome),
            (TEST_PENSION_COMBINATION, failing_core_form_outcome),
        ):
            failed = reader(geometry.form_tests, "pension", kind)
            if failed is not None:
                # Pension cost-cell yield (priced): the routed
                # cost cell firing on the movedens leg does not
                # refuse a claim the geometry's own pension
                # anchor legs carry.
                if (
                    kind == TEST_PENSION_ROUTED
                    and failed.detail == "kind:cost cell fired (A:movedens_le_0.25)"
                    and pension_anchor_legs(geometry)
                ):
                    scores = append_note(
                        scores,
                        "pension",
                        "gate",
                        f"{failed.detail}; pension anchor yield",
                    )
                    continue
                claims.remove("pension")
                if "pension" in contested:
                    contested.remove("pension")
                scores = append_note(scores, "pension", "gate", failed.detail)
                break
    # PENR variant leg 1: a pension claim carrying no
    # form-test points on a geometry with no data rows.
    if "pension" in claims:
        penr_chans = scores["pension"].by_channel
        if penr_chans.get("form_test", 0.0) == 0.0 and geometry.data_rows == 0:
            claims.remove("pension")
            if "pension" in contested:
                contested.remove("pension")
            scores = append_note(
                scores, "pension", "gate", "pension: penr no-form norows"
            )
    return scores


# Priced R2 rescue data: the benefits-note placement terms
# of the hard-veto scoping combination.
PENSION_VETO_RESCUE_PLACEMENT_TERMS = (
    "pension",
    "postretirement",
    "defined benefit",
    "benefit plan",
    "retirement",
    "employee benefit",
)


def pension_veto_rescued(geometry, scores):
    """Whether the priced R2 combination lifts the veto:
    a dominant pension score at strength, placed in a
    benefits note or carrying the NPBC signature."""
    score = scores.get("pension")
    if score is None or score.total < 20.0:
        return False
    if any(
        score.total < other.total
        for family, other in scores.items()
        if family != "pension"
    ):
        return False
    title = (geometry.note_title or "").lower()
    if any(term in title for term in PENSION_VETO_RESCUE_PLACEMENT_TERMS):
        return True
    spec = PENSION_ANCHOR_SPECS.get("pension")
    if spec is None:
        return False
    stubtext = geometry.stub_text
    groups = sum(
        1 for group in spec.npbc_groups if any(term in stubtext for term in group)
    )
    return groups >= spec.npbc_min_groups


def pension_anchor_legs(geometry):
    """The geometry's pension anchor legs under the base spec."""
    spec = PENSION_ANCHOR_SPECS.get("pension")
    if spec is None:
        return frozenset()
    return pension_anchor_set(PensionText.from_geometry(geometry), spec)


# Priced VETO-RC yield data: the pension stub vocabulary
# whose majority share marks a geometry as the family's
# own table under a reclassification caption.
PENSION_VETO_YIELD_STUB_TERMS = (
    "pension",
    "postretirement",
    "benefit cost",
    "service cost",
    "actuarial",
    "prior service",
    "net periodic",
    "benefit obligation",
)


def pension_veto_yielded(geometry, term):
    """Whether the priced reclassification yield lifts
    the veto: pension stubs in the majority and an
    anchor leg carrying the geometry."""
    if term != "reclassification" or not geometry.stubs:
        return False
    share = sum(
        1
        for stub in geometry.stubs
        if any(t in stub.lower() for t in PENSION_VETO_YIELD_STUB_TERMS)
    ) / len(geometry.stubs)
    return share >= 0.5 and bool(pension_anchor_legs(geometry))


def apply_tax_seat(claims, contested, scores, geometry, hard_vetoed, floor):
    """Run the tax_reconciliation seat: it alone decides claimage."""
    # Ruling 18 seat (tax_reconciliation): the priced statutory-
    # anchor conjunction replaces the family's claim path — a
    # scored claim is displaced, the seat alone decides claimage.
    tax_spec = TAX_EVIDENCE_SPECS.get("tax_reconciliation")
    if tax_spec is not None:
        if "tax_reconciliation" in claims:
            claims.remove("tax_reconciliation")
            if "tax_reconciliation" in contested:
                contested.remove("tax_reconciliation")
            scores = append_note(
                scores,
                "tax_reconciliation",
                "gate",
                "tax seat displaces scored claim",
            )
        # Seat precedence: the seat outranks the recorded hard
        # term in its precedence set; any other term bars it.
        # A floor term counts only when the family's scored
        # total clears the claim floor.
        hard = hard_vetoed.get("tax_reconciliation")
        tax_score = scores.get("tax_reconciliation")
        precedence = hard is None or (
            hard in tax_spec.seat_veto_precedence_terms
            and (
                hard not in tax_spec.seat_veto_precedence_floor_terms
                or (tax_score is not None and tax_score.total >= floor)
            )
        )
        if precedence:
            tax_outcome = next(
                (o for o in geometry.form_tests if o.test_id == tax_spec.test_id),
                None,
            )
            if tax_outcome is not None and tax_outcome.passed:
                scores = seat_at_floor(
                    scores, "tax_reconciliation", tax_outcome.detail, floor
                )
                claims.append("tax_reconciliation")
    return scores
