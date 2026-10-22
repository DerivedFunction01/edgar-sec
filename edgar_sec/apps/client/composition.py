"""User-composed chains: add/subtract expressions over named operands.

Each operand is a term or example fact resolved per firm through the
query facade. Composition status is the worst operand status under
the facade precedence ladder; a value is returned only when every
operand carries one, units and periods are compatible, and the
antichain veto over the operands' derivation chains passes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from edgar_sec.engine.xbrl.schema.models import CalculationArc
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.query import FinancialQueryResult, QueryStatus

# Facade precedence ladder, best to worst (Phase 2 followup ruling).
STATUS_ORDER: tuple[QueryStatus, ...] = (
    QueryStatus.VERIFIED,
    QueryStatus.REPORTED,
    QueryStatus.CONFLICT,
    QueryStatus.DERIVED,
    QueryStatus.AMBIGUOUS,
    QueryStatus.UNAVAILABLE,
)

OperandResolver = Callable[[str], FinancialQueryResult]
ChainTerms = Sequence[tuple[str, str]]


@dataclass(frozen=True)
class OperandResolution:
    """One operand's resolution inside a composition."""

    sign: str
    term: str
    status: QueryStatus
    value: float | None
    unit: str | None = None
    period_key: str | None = None
    concept_qname: str | None = None
    chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompositionResult:
    """A composed chain's outcome: worst-status propagation, value if sound."""

    status: QueryStatus
    value: float | None
    operands: tuple[OperandResolution, ...] = field(default_factory=tuple)
    message: str = ""


def _worst(statuses: Sequence[QueryStatus]) -> QueryStatus:
    return max(statuses, key=STATUS_ORDER.index)


def _period_key(result: FinancialQueryResult) -> str | None:
    fact = result.reported_fact
    if fact is not None:
        if fact.period_type == "instant":
            return f"instant:{fact.instant_date}"
        return f"duration:{fact.start_date}:{fact.end_date}"
    if result.aggregate is not None:
        return f"aggregate:{result.aggregate.period}"
    return None


def _unit(result: FinancialQueryResult) -> str | None:
    if result.reported_fact is not None:
        return result.reported_fact.unit
    if result.aggregate is not None:
        return result.aggregate.unit
    return None


def _chain(result: FinancialQueryResult) -> tuple[str, ...]:
    concepts = set(result.candidate_qnames)
    if result.reported_fact is not None:
        concepts.add(result.reported_fact.concept_qname)
    if result.aggregate is not None:
        concepts.update(result.aggregate.derivation_path)
        concepts.update(c.identifier for c in result.aggregate.components)
        concepts.add(result.aggregate.measure_id)
    return tuple(sorted(concepts))


def resolve_operand(
    resolver: OperandResolver, sign: str, term: str
) -> OperandResolution:
    """Resolve one operand term through the query facade."""
    result = resolver(term)
    return OperandResolution(
        sign=sign,
        term=term,
        status=result.status,
        value=result.value,
        unit=_unit(result),
        period_key=_period_key(result),
        concept_qname=(
            result.reported_fact.concept_qname
            if result.reported_fact is not None
            else (result.aggregate.measure_id if result.aggregate else None)
        ),
        chain=_chain(result),
    )


def evaluate_chain(
    resolver: OperandResolver,
    terms: ChainTerms,
    arcs: Sequence[CalculationArc],
) -> CompositionResult:
    """Evaluate an add/subtract chain over resolved operands."""
    operands = tuple(resolve_operand(resolver, sign, term) for sign, term in terms)
    if not operands:
        return CompositionResult(QueryStatus.UNAVAILABLE, None, message="empty chain")
    status = _worst([op.status for op in operands])

    selected = [c for op in operands for c in op.chain]
    if selected:
        outcome = AntiChainValidator().verify_non_double_counting(
            selected,
            [(a.parent_qname, a.child_qname, a.weight) for a in arcs],
        )
        if outcome.violations:
            return CompositionResult(
                _worst([status, QueryStatus.CONFLICT]),
                None,
                operands,
                "; ".join(outcome.violations),
            )

    valued = [op for op in operands if op.value is not None]
    for op in valued[1:]:
        head = valued[0]
        if op.unit != head.unit or op.period_key != head.period_key:
            return CompositionResult(
                _worst([status, QueryStatus.CONFLICT]),
                None,
                operands,
                f"operand {op.term!r} is incompatible with {head.term!r}: "
                f"unit {op.unit!r} vs {head.unit!r}, "
                f"period {op.period_key!r} vs {head.period_key!r}",
            )

    if len(valued) != len(operands):
        return CompositionResult(status, None, operands, "an operand carries no value")
    total = sum(
        op.value if op.sign != "-" else -op.value
        for op in operands
        if op.value is not None
    )
    return CompositionResult(status, total, operands)
