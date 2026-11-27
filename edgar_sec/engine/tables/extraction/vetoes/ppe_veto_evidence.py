"""PPE veto pass: set-level refusals over gate-final claims.
The composition build retires the dominance and host-claim
legs; the remaining legs read gate-final results and
geometry.
"""

from __future__ import annotations

from typing import NamedTuple

from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.specs.families.ppe_specs import (
    PPE_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_specs import (
    ADMISSION_FORM_TEST_DETAILS,
    CLASS_TERMS,
    CORE_FLOOR_TERMS,
    DISCIPLINE_CLASS_MIN,
    DISCIPLINE_NUMERIC_MIN,
    DISCIPLINE_S3_NUMERIC_MIN,
    LEAD_BALANCE_MIN,
    LEG_COEX_LEAD,
    LEG_CONTEXT_CARRIED,
    LEG_CORE_FLOOR,
    LEG_LEAD_BALANCE,
    LEG_STATEMENT_FORM,
    LEG_WEAK_SIGNATURE,
    PPE_FAMILY,
    PROSE_CHANNELS,
    SIGNATURE_CHANNELS,
    STATEMENT_MIN_DATA_ROWS,
    STATEMENT_MIN_NUMERIC_CELLS,
    WEAK_CLASS_DIVERSITY_MAX,
    WEAK_SIG_MAX,
)


class ClaimStage(NamedTuple):
    """One geometry's pre-gate claim stage: the families
    claiming at the own or context stage, with the scores
    as computed at the own stage."""

    claims: tuple
    scores: dict


def capture_claim_stages(own_results, mid_results):
    """Snapshot the pre-gate claim stage per geometry.

    Presence unions the own claims with the context-stage
    claims; totals stay at the own stage, as priced.
    """
    return tuple(
        ClaimStage(
            claims=tuple(dict.fromkeys((*own.claims, *mid.claims))),
            scores=own.scores,
        )
        for own, mid in zip(own_results, mid_results, strict=True)
    )


def _signature_sum(score) -> float:
    """A score's signature-channel mass (context excluded)."""
    if score is None:
        return 0.0
    return sum(score.by_channel.get(name, 0.0) for name in SIGNATURE_CHANNELS)


def passed_form_test_details(score) -> set:
    """A score's passed form-test evidence details."""
    return {
        entry.detail
        for entry in score.evidence
        if entry.channel == "form_test" and entry.detail.endswith(" passed")
    }


def _form_test_admission_seat(result) -> bool:
    """The claim is a form-test admission seat: group state
    admission, with both form tests passed in its evidence."""
    group = next((g for g in result.groups if g.family == PPE_FAMILY), None)
    if group is None or group.state != "admission":
        return False
    score = result.scores.get(PPE_FAMILY)
    if score is None:
        return False
    return set(ADMISSION_FORM_TEST_DETAILS) <= passed_form_test_details(score)


def _discipline_admission_seat(geometry, result) -> bool:
    """The claim is a discipline-form admission seat: group
    state admission, the discipline form firing."""
    group = next((g for g in result.groups if g.family == PPE_FAMILY), None)
    if group is None or group.state != "admission":
        return False
    return discipline_form_fires(geometry, result.scores.get(PPE_FAMILY))


def _lead_balance_fires(result) -> bool:
    """Zero form/stub mass, prose present, leads balanced."""
    score = result.scores.get(PPE_FAMILY)
    if score is None:
        return False
    channels = score.by_channel
    if channels.get("form_test", 0.0) != 0.0:
        return False
    if channels.get("stub", 0.0) != 0.0:
        return False
    prose = sum(channels.get(name, 0.0) for name in PROSE_CHANNELS)
    leadin = channels.get("leadin", 0.0)
    lead_title = channels.get("lead_title", 0.0)
    if prose <= 0.0 or leadin <= 0.0 or lead_title <= 0.0:
        return False
    return min(leadin, lead_title) / (leadin + lead_title) >= LEAD_BALANCE_MIN


def _context_carried_fires(geometries, results, index, result) -> bool:
    """Own signature empty and context-carried, with a
    signature-earned mate seated in a different section."""
    score = result.scores.get(PPE_FAMILY)
    if score is None:
        return False
    if _signature_sum(score) != 0.0:
        return False
    if score.by_channel.get("context", 0.0) <= 0.0:
        return False
    home = geometries[index].section_item
    for mate_index, mate in enumerate(results):
        if mate_index == index:
            continue
        if _signature_sum(mate.scores.get(PPE_FAMILY)) <= 0.0:
            continue
        if geometries[mate_index].section_item != home:
            return True
    return False


def _class_diversity(geometry) -> int:
    """Distinct PPE asset-class terms across the stubs."""
    text = " || ".join({normalize_text(stub) for stub in geometry.stubs})
    return sum(1 for term in CLASS_TERMS if term in text)


def discipline_form_fires(geometry, score) -> bool:
    """The geometry carries the PPE discipline form and
    no balance-sheet head (enlarged-set pricing)."""
    if score is None or score.total <= 0.0:
        return False
    head = [normalize_text(s) for s in geometry.stubs if s.strip()][:8]
    if any("balance sheet" in s for s in head):
        return False
    if any("current assets" in s for s in head) and any("cash" in s for s in head):
        return False
    spec = PPE_EVIDENCE_SPECS[PPE_FAMILY]
    stub_join = " || ".join({normalize_text(s) for s in geometry.stubs})
    head_join = " || ".join({normalize_text(s) for s in geometry.headers})
    grid = normalize_text(geometry.grid_text)
    contra = spec.contra_term in stub_join or spec.contra_term in grid
    classes = sum(1 for term in CLASS_TERMS if term in stub_join or term in head_join)
    numeric = (
        geometry.data_rows >= DISCIPLINE_NUMERIC_MIN
        and geometry.numeric_cells >= DISCIPLINE_NUMERIC_MIN
    )
    net = any(lit in stub_join or lit in grid for lit in spec.net_close_literals)
    col1 = (
        spec.col1_header_terms[0] in head_join or spec.col1_header_terms[0] in stub_join
    ) and contra
    s3 = (
        spec.s3_marker_term in grid or any(term in grid for term in spec.s3_cost_terms)
    ) and "real estate" in grid
    if classes >= DISCIPLINE_CLASS_MIN and (contra or net) and numeric:
        return True
    if col1 and numeric:
        return True
    return (
        s3
        and geometry.data_rows >= DISCIPLINE_S3_NUMERIC_MIN
        and geometry.numeric_cells >= DISCIPLINE_S3_NUMERIC_MIN
    )


def _weak_signature_fires(geometry, result) -> bool:
    """Weak-band signature mass over near-single-class stubs."""
    score = result.scores.get(PPE_FAMILY)
    if score is None:
        return False
    if _signature_sum(score) > WEAK_SIG_MAX:
        return False
    return _class_diversity(geometry) <= WEAK_CLASS_DIVERSITY_MAX


def _coex_lead_fires(result) -> bool:
    """A rival claims the geometry at gate and the PPE
    signature is lead-only (stub, caption, notehead empty)."""
    score = result.scores.get(PPE_FAMILY)
    if score is None:
        return False
    if not any(family != PPE_FAMILY for family in result.claims):
        return False
    channels = score.by_channel
    if channels.get("stub", 0.0) != 0.0:
        return False
    if channels.get("caption", 0.0) != 0.0:
        return False
    if channels.get("notehead", 0.0) != 0.0:
        return False
    return _signature_sum(score) > 0.0


def _statement_form_fires(geometry) -> bool:
    """Statement-length geometry: row and numeric mass."""
    return (
        geometry.data_rows >= STATEMENT_MIN_DATA_ROWS
        and geometry.numeric_cells >= STATEMENT_MIN_NUMERIC_CELLS
    )


def _core_floor_fires(geometry) -> bool:
    """No deep-core term in the table's own text: the claim
    carries no core evidence of its own. A geometry with no
    table text is not evaluable; the floor abstains."""
    text = normalize_text(
        " ".join([*geometry.stubs, *geometry.headers, geometry.grid_text])
    )
    if not text:
        return False
    return not any(term in text for term in CORE_FLOOR_TERMS)


def _fired_legs(geometries, results, stages, index):
    """Every priced leg firing on one PPE-claimed geometry."""
    geometry = geometries[index]
    result = results[index]
    legs = []
    if _lead_balance_fires(result):
        legs.append(LEG_LEAD_BALANCE)
    if _context_carried_fires(geometries, results, index, result):
        legs.append(LEG_CONTEXT_CARRIED)
    # The precision packet's legs skip an admission seat
    # whose form earned the claim: form-test pair or the
    # discipline form, not the veto, earned it.
    if not _form_test_admission_seat(result) and not _discipline_admission_seat(
        geometry, result
    ):
        if _weak_signature_fires(geometry, result):
            legs.append(LEG_WEAK_SIGNATURE)
        if _coex_lead_fires(result):
            legs.append(LEG_COEX_LEAD)
        if _statement_form_fires(geometry):
            legs.append(LEG_STATEMENT_FORM)
    # The core floor is a claim condition, not a packet
    # leg: it applies to admission seats too, whose form
    # legs carry core terms by construction.
    if _core_floor_fires(geometry):
        legs.append(LEG_CORE_FLOOR)
    return tuple(legs)


def apply_ppe_vetoes(geometries, results, stages):
    """Final pass: remove PPE claims firing any priced leg.

    Firings read the input results and the captured claim
    stages only, so removals never change another firing.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    fired = {
        index: legs
        for index, result in enumerate(results)
        if PPE_FAMILY in result.claims
        and (legs := _fired_legs(geometries, results, stages, index))
    }
    if not fired:
        return list(results)
    out = []
    for index, result in enumerate(results):
        legs = fired.get(index)
        if legs is None:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(PPE_FAMILY)
        if score is not None:
            detail = "ppe veto: " + ", ".join(legs)
            scores[PPE_FAMILY] = FamilyScore(
                score.family,
                score.total,
                dict(score.by_channel),
                score.evidence + (ClaimEvidence("gate", detail, 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(f for f in result.claims if f != PPE_FAMILY),
                contested=tuple(f for f in result.contested if f != PPE_FAMILY),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family != PPE_FAMILY),
            )
        )
    return out
