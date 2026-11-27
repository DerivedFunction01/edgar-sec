"""Debt-maturity claim vetoes: the section 7 tree front's three
rule-form conditions (headers_n = 26; a cash_flow hard hit on
"per share"; a "Total" header with the family's scored hit
"maturity") as claim vetoes at the final filing pass."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    term_veto_hits,
)

__all__ = [
    "apply_debt_maturity_claim_vetoes",
    "debt_maturity_veto_reason",
]

FAMILY = "debt_maturity"
HEADERS_N = 26


def debt_maturity_veto_reason(geometry: GeometryText) -> str | None:
    """The priced rule-form condition this geometry meets."""
    if len(geometry.headers) == HEADERS_N:
        return "debt veto: headers_n=26"
    hits = term_veto_hits(geometry)
    cash_flow_hard = (hits.get("cash_flow") or {}).get("hard")
    if cash_flow_hard == "per share":
        return "debt veto: cash_flow hard per share"
    own_scored = (hits.get(FAMILY) or {}).get("scored")
    if "Total" in geometry.headers and own_scored == "maturity":
        return "debt veto: Total header with maturity scored hit"
    return None


def apply_debt_maturity_claim_vetoes(geometries, results):
    """Final filing-level pass: a debt_maturity claim meeting
    one of the priced rule-form conditions is refused; the
    pass only removes claims."""
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    refused: dict[int, str] = {}
    for i, result in enumerate(results):
        if FAMILY not in result.claims:
            continue
        reason = debt_maturity_veto_reason(geometries[i])
        if reason is not None:
            refused[i] = reason
    if not refused:
        return list(results)
    out = []
    for i, result in enumerate(results):
        if i not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(FAMILY)
        if score is not None:
            scores[FAMILY] = FamilyScore(
                score.family,
                score.total,
                score.by_channel,
                score.evidence + (ClaimEvidence("gate", refused[i], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(
                    name for name in result.claims if name != FAMILY
                ),
                contested=tuple(
                    name for name in result.contested if name != FAMILY
                ),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out
