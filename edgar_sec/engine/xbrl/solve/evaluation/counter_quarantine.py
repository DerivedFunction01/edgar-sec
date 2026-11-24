"""Quarantine reason vocabulary and pair-level reason assignment."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    XbrlFact,
)
from edgar_sec.engine.xbrl.taxonomy.archive import current_table
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for, item_type_local


# Quarantine reasons are pair-level: exact-qname calc membership plus the
# unconsumed remainder's shape; partially consumed covers fact-level passes.
REASON_DIMENSIONED_ONLY_NO_CALC_ROLE = "DIMENSIONED_ONLY_NO_CALC_ROLE"
REASON_DIMENSIONED_ONLY_IN_CALC_ARCS = "DIMENSIONED_ONLY_IN_CALC_ARCS"
REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED = (
    "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED"
)
REASON_UNDIMENSIONED_NO_CALC_ROLE = "UNDIMENSIONED_NO_CALC_ROLE"
REASON_UNDIMENSIONED_CALC_ISOLATED = "UNDIMENSIONED_CALC_ISOLATED"
REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED = (
    "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED"
)
REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED = (
    "UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED"
)
QUARANTINE_REASONS = (
    REASON_DIMENSIONED_ONLY_NO_CALC_ROLE,
    REASON_DIMENSIONED_ONLY_IN_CALC_ARCS,
    REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED,
    REASON_UNDIMENSIONED_NO_CALC_ROLE,
    REASON_UNDIMENSIONED_CALC_ISOLATED,
    REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED,
    REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED,
)


@dataclass(frozen=True, slots=True)
class QuarantinedFact:
    """An unconsumed filing fact captured in Epistemic Quarantine."""

    fact: XbrlFact
    reason: str


class PairReasonsMixin:
    """Assigns each quarantined concept its pair-level reason."""

    @staticmethod
    def _pair_reasons(
        solved: Sequence[XbrlFact],
        unconsumed: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        audited: frozenset[str],
        declarations: Mapping[str, ConceptDeclaration] | None = None,
    ) -> dict[str, str]:
        """Pair reason per quarantined concept from arcs and fact shape.

        A declared per-share concept with no calc role is calc-isolated
        by construction: its verdict names the class, not a mapping gap.
        """
        in_arcs: set[str] = set()
        parents: dict[str, set[str]] = {}
        for arc in calculation_arcs:
            in_arcs.add(arc.parent_qname)
            in_arcs.add(arc.child_qname)
            parents.setdefault(arc.child_qname, set()).add(arc.parent_qname)
        supplied = declarations or {}
        table: dict[str, str] | None = None

        def is_per_share(concept: str) -> bool:
            nonlocal table
            if table is None:
                table = current_table()
            declaration = declaration_for(concept, table, supplied)
            return (
                declaration is not None
                and item_type_local(declaration.item_type) == "perShareItemType"
            )

        consumed = Counter(
            fact.concept_qname
            for fact in solved
            if isinstance(fact.value, (int, float))
        )
        grouped: dict[str, list[XbrlFact]] = {}
        for fact in unconsumed:
            grouped.setdefault(fact.concept_qname, []).append(fact)
        reasons: dict[str, str] = {}
        for concept, members in grouped.items():
            if all(fact.dimensions for fact in members):
                if concept not in in_arcs:
                    reasons[concept] = REASON_DIMENSIONED_ONLY_NO_CALC_ROLE
                elif consumed[concept]:
                    reasons[concept] = (
                        REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED
                    )
                else:
                    reasons[concept] = REASON_DIMENSIONED_ONLY_IN_CALC_ARCS
                continue
            if concept not in in_arcs:
                reasons[concept] = (
                    REASON_UNDIMENSIONED_CALC_ISOLATED
                    if is_per_share(concept)
                    else REASON_UNDIMENSIONED_NO_CALC_ROLE
                )
            elif (
                parents.get(concept)
                and not parents[concept] & audited
                and concept not in audited
            ):
                reasons[concept] = REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED
            else:
                reasons[concept] = REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED
        return reasons
