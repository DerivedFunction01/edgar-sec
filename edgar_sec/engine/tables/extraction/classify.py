"""The classification cascade over one structured table."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.classification import (
    Classification,
    Evidence,
    TableKind,
)
from edgar_sec.engine.tables.extraction.deferred_tax_seat import (
    apply_deferred_tax_seat,
)
from edgar_sec.engine.tables.extraction.family_scoring import evidence_scores
from edgar_sec.engine.tables.extraction.filing_passes import (
    apply_detail_agreement,
    apply_placement,
)
from edgar_sec.engine.tables.extraction.finishing import (
    context_base,
    finish,
    refinish,
)
from edgar_sec.engine.tables.extraction.genre_seat import (
    FULL_REFUSAL_PREFIXES,
    table_refusal,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.policy import (
    ClassificationPolicy,
    default_policy,
)
from edgar_sec.engine.tables.extraction.regions import Region, effective_regions
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    CONTEXT_ANCHOR_MIN_SCORE,
    CORE_FAMILIES,
    FAMILY_PRIORITY,
    RESIDUAL_FAMILY,
    SATELLITE_FAMILIES,
)
from edgar_sec.engine.tables.extraction.rule_matching import rule_matches
from edgar_sec.engine.tables.extraction.section_gate import (
    STATEMENT_FAMILIES,
    GenreRefusal,
    genre_refusal,
)
from edgar_sec.engine.tables.extraction.stub_routing import apply_stub_routing
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.engine.tables.extraction.validation import IdentityOutcome

__all__ = [
    "Classification",
    "Evidence",
    "TableKind",
    "candidate_scores",
    "classify_filing",
    "classify_table",
]


def candidate_scores(
    table: TypedTable,
    policy: ClassificationPolicy | None = None,
    math_outcomes: tuple[IdentityOutcome, ...] | None = None,
) -> dict[str, tuple[float, tuple[Evidence, ...]]]:
    """Every scored family's points and evidence, before arbitration."""
    policy = policy if policy is not None else default_policy()
    labels = [normalize_text(row.label) for row in table.rows]
    scored = evidence_scores(table, labels, policy, math_outcomes)
    return {
        family: (score, tuple(evidence)) for family, (score, evidence) in scored.items()
    }


def _section_refusal(
    table: TypedTable, family: str, policy: ClassificationPolicy
) -> GenreRefusal | None:
    section = table.context.section
    if section is None or not policy.section_scopes:
        return None
    title = " | ".join(
        part
        for part in (
            section.title,
            *table.context.caption_stack,
            *table.caption.titles,
        )
        if part
    )
    return genre_refusal(
        policy.section_scopes,
        family,
        section.form,
        section.part,
        section.item,
        title or None,
    )


def classify_table(
    table: TypedTable,
    policy: ClassificationPolicy | None = None,
    math_outcomes: tuple[IdentityOutcome, ...] | None = None,
) -> Classification:
    """Classify one table: the genre seat, then the cascade.

    A furniture table is genre-refused at the seat before any
    family scoring; a section-refused claim is refused after.
    """
    policy = policy if policy is not None else default_policy()
    seat = table_refusal(table)
    if seat is not None:
        labels = [normalize_text(row.label) for row in table.rows]
        evidence = context_base(table) + [Evidence("genre_refusal", seat.detail, 0.0)]
        return finish(RESIDUAL_FAMILY, "genre_refusal", 0.0, evidence, labels, table)
    result = _cascade(table, policy, math_outcomes)
    refusal = _section_refusal(table, result.family, policy)
    if refusal is None:
        return result
    labels = [normalize_text(row.label) for row in table.rows]
    evidence = context_base(table) + [Evidence("genre_refusal", refusal.detail, 0.0)]
    return finish(RESIDUAL_FAMILY, "genre_refusal", 0.0, evidence, labels, table)


def _cascade(
    table: TypedTable,
    policy: ClassificationPolicy | None = None,
    math_outcomes: tuple[IdentityOutcome, ...] | None = None,
) -> Classification:
    """Classify one structured table through the ordered cascade.

    Precomputed math outcomes may be supplied by callers that evaluate
    identities once per document; None evaluates them for this table.
    """
    policy = policy if policy is not None else default_policy()
    labels = [normalize_text(row.label) for row in table.rows]
    section = table.context.section
    base = [
        Evidence(
            "context",
            f"section={section.item if section else None} "
            f"note={table.context.note is not None}",
            0.0,
        )
    ]
    if table.context.region == Region.SIGNATURE.value:
        evidence = base + [
            Evidence("context", "signature region: not a statement candidate", 0.0)
        ]
        return finish(RESIDUAL_FAMILY, "region", 0.0, evidence, labels, table)
    for rule in policy.specific:
        matched = rule_matches(rule, table)
        if matched is not None:
            evidence = base + [Evidence(matched, rule.family, 0.0)]
            return finish(rule.family, "specific", 0.0, evidence, labels, table)
    scored = evidence_scores(table, labels, policy, math_outcomes)
    winner = min(
        scored,
        key=lambda family: (-scored[family][0], FAMILY_PRIORITY.index(family)),
    )
    score, evidence = scored[winner]
    if score >= ASSIGNMENT_FLOOR:
        return finish(winner, "evidence", score, base + evidence, labels, table)
    residual = base + [
        Evidence(
            "residual",
            f"best {winner} at {score:.2f} below floor {ASSIGNMENT_FLOOR}",
            0.0,
        )
    ]
    return finish(RESIDUAL_FAMILY, "residual", score, residual, labels, table)


def classify_filing(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    policy: ClassificationPolicy | None = None,
    math_outcomes: list[tuple[IdentityOutcome, ...]] | None = None,
) -> tuple[list[Classification], list[dict[str, float]]]:
    """Classify one filing's tables with the constellation pass.

    Placement-kind form tests are applied over the first-pass reads;
    satellite wins before the first core anchor are re-arbitrated.
    """
    policy = policy if policy is not None else default_policy()
    results: list[Classification] = []
    scored: list[dict[str, tuple[float, tuple[Evidence, ...]]]] = []
    for position, table in enumerate(tables):
        outcomes = None if math_outcomes is None else math_outcomes[position]
        result = classify_table(table, policy, math_outcomes=outcomes)
        results.append(result)
        entry = candidate_scores(table, policy, math_outcomes=outcomes)
        if result.tier == "genre_refusal":
            if any(
                ev.detail.startswith(FULL_REFUSAL_PREFIXES)
                for ev in result.evidence
                if ev.group == "genre_refusal"
            ):
                entry = {}
            else:
                entry = {
                    family: scored_entry
                    for family, scored_entry in entry.items()
                    if family not in STATEMENT_FAMILIES
                }
        scored.append(entry)
    regions = effective_regions([table.context for table in tables])
    for position, region in enumerate(regions):
        if region != Region.SIGNATURE.value:
            continue
        table = tables[position]
        labels = [normalize_text(row.label) for row in table.rows]
        marker = Evidence("context", "signature region: not a statement candidate", 0.0)
        results[position] = finish(
            RESIDUAL_FAMILY,
            "region",
            0.0,
            context_base(table) + [marker],
            labels,
            table,
        )
        scored[position] = {}
    scores: list[dict[str, float]] = [
        {family: score for family, (score, _) in entry.items()} for entry in scored
    ]
    apply_placement(tables, results, scored, scores)
    apply_detail_agreement(tables, results, scored, scores)
    anchors = [
        position
        for position, result in enumerate(results)
        if result.family in CORE_FAMILIES
        and (result.tier == "specific" or result.score >= CONTEXT_ANCHOR_MIN_SCORE)
    ]
    if anchors:
        first_anchor = min(anchors)
        for position, result in enumerate(results):
            if position >= first_anchor or result.tier == "specific":
                continue
            if result.family not in SATELLITE_FAMILIES:
                continue
            adjusted = dict(scores[position])
            adjusted[result.family] = 0.0
            evidence = {
                family: trail for family, (_, trail) in scored[position].items()
            }
            marker = Evidence(
                "context",
                f"{result.family} candidacy precedes the first statement anchor",
                0.0,
            )
            results[position] = refinish(tables[position], adjusted, evidence, marker)
            scores[position] = adjusted
    apply_stub_routing(tables, results, finish, Evidence)
    apply_deferred_tax_seat(tables, results, scores, finish)
    return results, scores
