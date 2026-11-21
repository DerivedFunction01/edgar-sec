"""PPE veto pass: set-level refusals over gate-final claims.
The dominance leg prices rival presence on the pre-gate
claim stage; the other legs read the gate-final results.
"""

from __future__ import annotations

from typing import NamedTuple

from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_specs import (
    HOST_MIN_SHARED_KEYS,
    LEAD_BALANCE_MIN,
    LEG_CONTEXT_CARRIED,
    LEG_DOMINANCE,
    LEG_HOST_CLAIM,
    LEG_LEAD_BALANCE,
    PPE_FAMILY,
    PROSE_CHANNELS,
    SIGNATURE_CHANNELS,
    STRONG_STUB_KEYS,
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


def _host_claim_fires(geometry, result) -> bool:
    """A claiming rival hosts the strong-key threshold."""
    stubs = {normalize_text(stub) for stub in geometry.stubs}
    for family in result.claims:
        if family == PPE_FAMILY:
            continue
        strong = STRONG_STUB_KEYS.get(family)
        if strong and len(stubs & strong) >= HOST_MIN_SHARED_KEYS:
            return True
    return False


def _dominance_fires(result, stage) -> bool:
    """A stage-claiming rival's own-stage total reaches the
    PPE final total (weak dominance, as arbitrated)."""
    own = result.scores.get(PPE_FAMILY)
    if own is None:
        return False
    for family in stage.claims:
        if family == PPE_FAMILY:
            continue
        rival = stage.scores.get(family)
        if rival is not None and rival.total >= own.total:
            return True
    return False


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


def _fired_legs(geometries, results, stages, index):
    """Every priced leg firing on one PPE-claimed geometry."""
    geometry = geometries[index]
    result = results[index]
    legs = []
    if _host_claim_fires(geometry, result):
        legs.append(LEG_HOST_CLAIM)
    if _dominance_fires(result, stages[index]):
        legs.append(LEG_DOMINANCE)
    if _lead_balance_fires(result):
        legs.append(LEG_LEAD_BALANCE)
    if _context_carried_fires(geometries, results, index, result):
        legs.append(LEG_CONTEXT_CARRIED)
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
