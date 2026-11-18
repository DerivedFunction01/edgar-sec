"""Filing-level constellation passes over first-pass reads."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.classification import (
    Classification,
    Evidence,
)
from edgar_sec.engine.tables.extraction.detail_agreement import (
    DETAIL_AGREEMENT_FLOOR,
    DETAIL_AGREEMENT_POINTS,
    find_detail_agreement,
)
from edgar_sec.engine.tables.extraction.finishing import refinish
from edgar_sec.engine.tables.extraction.form_test_specs import FORM_TEST_SPECS
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.placement import placement_facts
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_PLACEMENT_CONSISTENCY,
)
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    FAMILY_PRIORITY,
    PRIMARY_STATEMENT_FAMILIES,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


def apply_placement(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    results: list[Classification],
    scored: list[dict[str, tuple[float, tuple[Evidence, ...]]]],
    scores: list[dict[str, float]],
) -> None:
    """Apply placement-kind form tests over first-pass reads.
    A fired conjunction disqualifies its family for the table
    (the satellite precedent); a pass changes nothing."""
    specs = tuple(
        spec for spec in FORM_TEST_SPECS if spec.kind == TEST_PLACEMENT_CONSISTENCY
    )
    if not specs:
        return
    sequence = tuple(result.family for result in results)
    for position, table in enumerate(tables):
        if not scored[position]:
            continue
        if results[position].tier in ("specific", "genre_refusal"):
            continue
        facts = placement_facts(sequence, position)
        adjusted = dict(scores[position])
        evidence = {family: trail for family, (_, trail) in scored[position].items()}
        touched = False
        for outcome in evaluate_form_tests(table, specs=specs, placement=facts):
            if not outcome.evaluable or outcome.passed:
                continue
            family = outcome.family
            if family not in adjusted or adjusted[family] == 0.0:
                continue
            adjusted[family] = 0.0
            touched = True
            trail = list(evidence.get(family, ()))
            trail.append(Evidence("form_test", f"{outcome.test_id} fired", 0.0))
            evidence[family] = tuple(trail)
        if touched:
            marker = Evidence("context", "placement facts from first-pass reads", 0.0)
            results[position] = refinish(table, adjusted, evidence, marker)
            scores[position] = adjusted


def apply_detail_agreement(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    results: list[Classification],
    scored: list[dict[str, tuple[float, tuple[Evidence, ...]]]],
    scores: list[dict[str, float]],
) -> None:
    """Claim breakdown tables for their host family on agreement.
    A candidate's components close to one primary statement line;
    its points join the scored evidence and re-arbitration."""

    def seated(result: Classification) -> bool:
        return (
            result.family in PRIMARY_STATEMENT_FAMILIES
            and result.score >= ASSIGNMENT_FLOOR
            and result.tier not in ("genre_refusal", "region")
        )

    hosts = [
        (result.family, tables[position])
        for position, result in enumerate(results)
        if seated(result)
    ]
    if not hosts:
        return
    for position, table in enumerate(tables):
        result = results[position]
        if result.tier in ("genre_refusal", "region"):
            continue
        if seated(result):
            continue
        agreement = find_detail_agreement(table, hosts)
        if agreement is None:
            continue
        adjusted = dict(scores[position])
        adjusted[agreement.host_family] = (
            adjusted.get(agreement.host_family, 0.0) + DETAIL_AGREEMENT_POINTS
        )
        evidence = {family: trail for family, (_, trail) in scored[position].items()}
        trail = list(evidence.get(agreement.host_family, ()))
        trail.append(
            Evidence(
                "form_test",
                f"detail value agreement: {agreement.host_label}",
                DETAIL_AGREEMENT_POINTS,
            )
        )
        evidence[agreement.host_family] = tuple(trail)
        marker = Evidence("context", "detail agreement from filing constellation", 0.0)
        winner = min(
            adjusted,
            key=lambda family: (-adjusted[family], FAMILY_PRIORITY.index(family)),
        )
        floor = ASSIGNMENT_FLOOR
        if (
            winner == agreement.host_family
            and adjusted[winner] >= DETAIL_AGREEMENT_FLOOR
        ):
            floor = DETAIL_AGREEMENT_FLOOR
        results[position] = refinish(table, adjusted, evidence, marker, floor=floor)
        scores[position] = adjusted
