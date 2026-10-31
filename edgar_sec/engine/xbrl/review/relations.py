"""Seeded longitudinal relations across concept switches, with evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import FinancialQuery, QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FactScope


@dataclass(frozen=True, slots=True)
class RelationSpec:
    """One same-firm longitudinal relation across a concept switch."""

    firm: str
    boundary: str
    pre_concept: str
    pre_value: float
    pre_instant: str
    pre_accession: str
    post_concept: str
    post_value: float
    post_instant: str
    post_accession: str
    provenance: str


@dataclass(frozen=True, slots=True)
class RelationReport:
    """Gate outcome for the seeded longitudinal relations."""

    total: int
    passed: int
    failures: tuple[str, ...]

    @property
    def passed_all(self) -> bool:
        """True when every seeded relation holds at both endpoints."""
        return not self.failures


RELATION_SET: tuple[RelationSpec, ...] = (
    RelationSpec(
        firm="BAC",
        boundary="ASU 2016-18",
        pre_concept="us-gaap:CashAndCashEquivalentsAtCarryingValue",
        pre_value=120_102_000_000.0,
        pre_instant="2011-12-31",
        pre_accession="0000070858-12-000155",
        post_concept=(
            "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
        ),
        post_value=290_114_000_000.0,
        post_instant="2024-12-31",
        post_accession="0000070858-25-000139",
        provenance=(
            "WS1 step-1 audit sections 3-4: FY2011 consolidated cash "
            "REPORTED 120,102M under the predecessor concept (rendered "
            "text L7045); register F sections 3-4: FY2024 cash REPORTED "
            "290,114M under the ASU 2016-18 rollup (rendered text "
            "L4564). The "
            "relation is the concept switch itself, not one concept "
            "smoothed across the boundary."
        ),
    ),
)


def evaluate_relations(
    engine: Any,
    endpoints: dict[str, tuple[Sequence[XbrlFact], Sequence[Any]]],
    relations: tuple[RelationSpec, ...] = RELATION_SET,
) -> RelationReport:
    """Evaluate seeded relations at both endpoints through the query engine.

    Each endpoint must answer REPORTED at its recorded value under its
    own era's concept and UNAVAILABLE under the other era's concept.
    """
    failures: list[str] = []
    passed = 0
    for spec in relations:
        label = f"{spec.firm} relation across {spec.boundary}"
        checks = (
            (spec.pre_accession, spec.pre_concept, spec.pre_instant, True),
            (spec.pre_accession, spec.post_concept, spec.pre_instant, False),
            (spec.post_accession, spec.post_concept, spec.post_instant, True),
            (spec.post_accession, spec.pre_concept, spec.post_instant, False),
        )
        expected_value = {
            (spec.pre_accession, spec.pre_concept): spec.pre_value,
            (spec.post_accession, spec.post_concept): spec.post_value,
        }
        ok = True
        for accession, qname, instant, present in checks:
            endpoint = endpoints.get(accession)
            if endpoint is None:
                failures.append(f"{label}: no endpoint facts for {accession}")
                ok = False
                continue
            facts, arcs = endpoint
            result = engine.execute(
                FinancialQuery(
                    qname,
                    FactScope(accession=accession, instant_date=instant, unit="USD"),
                ),
                facts,
                arcs,
            )
            want_status = QueryStatus.REPORTED if present else QueryStatus.UNAVAILABLE
            want_value = expected_value.get((accession, qname))
            if result.status != want_status or (
                want_value is not None and result.value != want_value
            ):
                failures.append(
                    f"{label}: {qname} @ {accession} expected "
                    f"{want_status} {want_value}, got {result.status} {result.value}"
                )
                ok = False
        if ok:
            passed += 1
    return RelationReport(total=len(relations), passed=passed, failures=tuple(failures))
