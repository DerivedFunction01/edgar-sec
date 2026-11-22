"""Assignment stage: the set-level assignment passes and the
preservation of the claims they remove.

A claim removed by a pass is re-seated from its score before
the primary gate runs; later stages run unchanged.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.aro_evidence import (
    apply_aro_assignment,
)
from edgar_sec.engine.tables.extraction.evidence.income_statement.income_statement_setlevel_evidence import (
    apply_income_statement_assignment,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    apply_lease_assignment,
)
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_evidence import (
    apply_stock_comp_assignment,
)
from edgar_sec.engine.tables.extraction.separators.combined_operations_separator_evidence import (
    apply_combined_operations_assignment,
)
from edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_evidence import (
    apply_comprehensive_income_assignment,
)
from edgar_sec.engine.tables.extraction.separators.equity_separator_evidence import (
    apply_equity_assignment,
)

ASSIGNMENT_PASSES = (
    apply_comprehensive_income_assignment,
    apply_equity_assignment,
    apply_combined_operations_assignment,
    apply_income_statement_assignment,
    apply_stock_comp_assignment,
    apply_aro_assignment,
    apply_lease_assignment,
)


def _claim_role(geometry: GeometryText) -> str:
    """A claim's grouped-return role, as compete() stamps it."""
    return (
        "continuation"
        if geometry.is_fragment
        else "head"
        if geometry.caption.strip()
        else "standalone"
    )


def _refused_reseat(family: str, score: FamilyScore | None) -> bool:
    """Whether preservation refuses to re-seat a removed claim.

    An income_statement claim whose score carries
    context-channel points stays removed.
    """
    return (
        family == "income_statement"
        and score is not None
        and score.by_channel.get("context", 0.0) > 0
    )


def preserve_assignment_claims(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    entering: list[CompetitionResult],
    assigned: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Re-seat the claims the assignment passes removed, rebuilt
    from each family's score — a claim the refusal names (an
    income_statement score with context points) stays removed.
    """
    out: list[CompetitionResult] = []
    for geometry, before, result in zip(geometries, entering, assigned, strict=True):
        missing = [
            family
            for family in before.claims
            if family not in result.claims
            and not _refused_reseat(family, result.scores.get(family))
        ]
        if not missing:
            out.append(result)
            continue
        groups = list(result.groups)
        have = {group.family for group in groups}
        for family in sorted(missing):
            if family in have:
                continue
            score = result.scores.get(family)
            if score is None:
                continue
            groups.append(
                ClaimGroup(
                    family=family,
                    score=score.total,
                    state="claimed",
                    role=_claim_role(geometry),
                    channels=dict(score.by_channel),
                    veto_flags=tuple(
                        e.detail for e in score.evidence if e.channel == "veto"
                    ),
                    explained_foreign=0.0,
                )
            )
        out.append(
            CompetitionResult(
                claims=tuple([*result.claims, *sorted(missing)]),
                contested=result.contested,
                scores=result.scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(groups),
            )
        )
    return out


def apply_assignment_stage(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Run the assignment passes, then preserve their removals."""
    assigned = list(results)
    for apply_assignment in ASSIGNMENT_PASSES:
        assigned = apply_assignment(geometries, assigned)
    return preserve_assignment_claims(geometries, results, assigned)
