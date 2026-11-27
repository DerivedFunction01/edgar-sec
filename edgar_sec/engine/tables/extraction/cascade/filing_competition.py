"""Filing-level competition: compete_filing and its context
feedback over one filing's geometries.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.assignment_stage import (
    apply_assignment_stage,
)
from edgar_sec.engine.tables.extraction.cascade.competition import (
    CLAIM_FLOOR,
    INHERITANCE_FACTOR,
    INHERITANCE_MAX_DISTANCE,
    TIE_POINTS,
    compete,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
    _explained_foreign,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_evidence import (
    apply_ppe_vetoes,
    capture_claim_stages,
    discipline_form_fires,
    passed_form_test_details,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_specs import (
    ADMISSION_FORM_TEST_DETAILS,
    OVSEAT_SIG_FLOOR,
    OVSEAT_TERM,
)
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_evidence import (
    apply_precision_vetoes,
)
from edgar_sec.engine.tables.extraction.vetoes.spanning_veto_evidence import (
    apply_spanning_vetoes,
)
from edgar_sec.engine.tables.extraction.seats.cover_seat import apply_cover_seat
from edgar_sec.engine.tables.extraction.seats.eps_seat import apply_eps_seat
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    term_veto_hits,
)
from edgar_sec.engine.tables.extraction.seats.primary_gate import (
    apply_primary_gate,
    statement_clusters,
)
from edgar_sec.engine.tables.extraction.seats.lease_span_seat import (
    apply_lease_span_seat,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    apply_lease_stub_refusal,
)
from edgar_sec.engine.tables.extraction.seats.related_party_seat import (
    apply_related_party_seat,
)
from edgar_sec.engine.tables.extraction.cascade.pension_generation_seat import (
    apply_pension_generation_seat,
)
from edgar_sec.engine.tables.extraction.seats.segment_seat import apply_segment_seat
from edgar_sec.engine.tables.extraction.seats.warrant_seat import apply_warrant_seat
from edgar_sec.engine.tables.extraction.vetoes.debt_maturity_claim_vetoes import (
    apply_debt_maturity_claim_vetoes,
)
from edgar_sec.engine.tables.extraction.seats.section_gate import ScopeRow
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    CHANNELS as SIGNATURE_CHANNELS,
    CONTAINMENT_EDGES,
    INHERITANCE_FACTORS,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    FOOTNOTE_TAIL_RE,
)


# Inheritance lends a fragment the discounted evidence of the
# nearest preceding claim in its note or section; a note title
# shared with 2+ same-family claims lends that family tie evidence.


def _ppe_signature_sum(result: CompetitionResult) -> float:
    """A result's PPE signature-channel mass (context excluded)."""
    score = result.scores.get("ppe")
    if score is None:
        return 0.0
    return sum(score.by_channel.get(name, 0.0) for name in SIGNATURE_CHANNELS)


def _sole_depreciation_expense_row(geometry: GeometryText) -> bool:
    """The geometry's sole labeled row is a depreciation-expense
    line: a one-row depreciation summary, spared suppression."""
    labels = [normalize_text(stub) for stub in geometry.stubs if stub.strip()]
    if len(labels) != 1:
        return False
    return FOOTNOTE_TAIL_RE.sub("", labels[0]).strip() == "depreciation expense"


def apply_ppe_formation_suppression(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Suppress the formed set's signature-less PPE claims: a
    context-only claim does not seat beside a signature-earned
    PPE claim, unless its geometry is a depreciation summary."""
    if not any(
        "ppe" in result.claims and _ppe_signature_sum(result) > 0.0
        for result in results
    ):
        return list(results)
    out: list[CompetitionResult] = []
    for geometry, result in zip(geometries, results, strict=True):
        if "ppe" not in result.claims or _ppe_signature_sum(result) > 0.0:
            out.append(result)
            continue
        if _sole_depreciation_expense_row(geometry):
            out.append(result)
            continue
        out.append(
            CompetitionResult(
                claims=tuple(f for f in result.claims if f != "ppe"),
                contested=tuple(f for f in result.contested if f != "ppe"),
                scores=result.scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family != "ppe"),
            )
        )
    return out


def apply_ppe_veto_override_seat(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Veto-override seat at the suppression seam's output:
    competition ran veto-intact, so no claim is displaced;
    a claim-free geometry seats PPE on any leg's terms."""
    out: list[CompetitionResult] = []
    for geometry, result in zip(geometries, results, strict=True):
        score = result.scores.get("ppe")
        if score is None or "ppe" in result.claims:
            out.append(result)
            continue
        hard = (term_veto_hits(geometry).get("ppe") or {}).get("hard")
        # Leg F: both form tests pass, hard hit absent or
        # the override term. Leg S: the override term hit,
        # signature and total each clearing their floor.
        leg_f = set(ADMISSION_FORM_TEST_DETAILS) <= passed_form_test_details(
            score
        ) and (hard is None or hard == OVSEAT_TERM)
        leg_s = (
            hard == OVSEAT_TERM
            and _ppe_signature_sum(result) >= OVSEAT_SIG_FLOOR
            and score.total >= CLAIM_FLOOR
        )
        # Leg D: the discipline form seats with the same
        # hard-hit tolerance as Leg F.
        leg_d = (hard is None or hard == OVSEAT_TERM) and discipline_form_fires(
            geometry, score
        )
        if not (leg_f or leg_s or leg_d):
            out.append(result)
            continue
        _, explained = _explained_foreign("ppe", result.scores, CONTAINMENT_EDGES)
        role = (
            "continuation"
            if geometry.is_fragment
            else "head"
            if geometry.caption.strip()
            else "standalone"
        )
        group = ClaimGroup(
            "ppe",
            score.total,
            "admission",
            role,
            dict(score.by_channel),
            tuple(e.detail for e in score.evidence if e.channel == "veto"),
            sum(explained.values()),
        )
        out.append(
            CompetitionResult(
                claims=tuple(result.claims) + ("ppe",),
                contested=result.contested,
                scores=result.scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(result.groups) + (group,),
            )
        )
    return out


def _compete_through_gate(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...],
    edges: tuple[ContainmentEdge, ...],
    ladder_terms: tuple[LadderTerm, ...],
    scopes: tuple[ScopeRow, ...],
):
    """Compete through the primary gate: the claim set the
    gate admits, with the claim stages captured pre-gate."""
    clusters = statement_clusters(geometries)

    def cluster_stubs(index: int) -> tuple[str, ...]:
        return tuple(
            stub for member in clusters[index] for stub in geometries[member].stubs
        )

    results = [
        compete(
            g,
            terms,
            edges,
            ladder_terms=ladder_terms,
            scopes=scopes,
            cluster_stubs=cluster_stubs(index),
        )
        for index, g in enumerate(geometries)
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
            cluster_stubs=cluster_stubs(index),
        )
    stages = capture_claim_stages(own_results, results)
    # Set-level assignment stage (priced): the passes run over
    # the filing's formed candidate set and only remove claims;
    # the stage preserves the claims they remove.
    results = apply_assignment_stage(geometries, results)
    # Formation suppression (priced): a signature-less PPE
    # claim never enters the gate/veto population where the
    # filing seats a signature-earned PPE claim.
    results = apply_ppe_formation_suppression(geometries, results)
    # Veto-override seat (priced): at the suppression seam's
    # output, a claim-free geometry seats PPE on its form
    # tests, its signature, or its discipline form despite
    # the one hard term.
    results = apply_ppe_veto_override_seat(geometries, results)
    # The primary hard gates refuse claims whose necessary
    # sections are missing over the statement cluster; the PPE,
    # precision, and spanning vetoes read gate-final claims.
    gated = apply_primary_gate(geometries, results)
    return gated, stages


def compete_filing_gated(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
    scopes: tuple[ScopeRow, ...] = (),
) -> list[CompetitionResult]:
    """The filing's claims as the primary gate admits them:
    compete's early discipline, before the late veto stages."""
    gated, _ = _compete_through_gate(
        geometries, terms, edges, ladder_terms, scopes
    )
    return gated


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
    gated, stages = _compete_through_gate(
        geometries, terms, edges, ladder_terms, scopes
    )
    vetoed = apply_ppe_vetoes(geometries, gated, stages)
    precise = apply_precision_vetoes(geometries, vetoed, stages)
    spanned = apply_spanning_vetoes(geometries, precise)
    # Formation seat (priced): cover identity is read from the
    # filing's front matter, upstream of every table decision;
    # the seat claims only geometries the chain left unclaimed.
    covered = apply_cover_seat(geometries, spanned)
    # Formation seat (priced): segment_reporting seats on the
    # gate-final unclaimed set its own floor cannot reach.
    segmented = apply_segment_seat(geometries, covered)
    # Formation seat (priced): lease_maturity seats as the
    # final pass on span and stub purity, debt-seat guarded.
    seated = apply_lease_span_seat(geometries, segmented)
    # Stub refusal (priced): a lease claim with no period stub
    # or transposed period axis, or a combined grid whose lease
    # column is a mass sliver, is refused at the final output.
    refused = apply_lease_stub_refusal(geometries, seated)
    # Formation seat (priced): eps_reconciliation seats on
    # the gate-final unclaimed set under its priced guard.
    epsed = apply_eps_seat(geometries, refused)
    # Formation seat (priced): related_party seats on the
    # gate-final unclaimed set its own floor cannot reach.
    partied = apply_related_party_seat(geometries, epsed)
    # Formation seat (priced): warrant_activity seats on the
    # gate-final set its two form tests cannot claim alone.
    warranted = apply_warrant_seat(geometries, partied)
    # Formation seat (priced): pension seats on the
    # gate-final unclaimed set under the generation
    # admission (note identity or quiet-form stubs).
    generated = apply_pension_generation_seat(geometries, warranted)
    # Claim veto (priced): debt_maturity claims meeting one of
    # the section 7 tree front's rule-form conditions are
    # refused at the final output.
    return apply_debt_maturity_claim_vetoes(geometries, generated)
