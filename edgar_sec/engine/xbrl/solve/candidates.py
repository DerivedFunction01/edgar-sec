"""Classify candidate facts for a target concept."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.schema.models import (
    CORE_PREFIXES,
    CalculationArc,
    Verdict,
    XbrlFact,
    qname_local,
    split_concept_qname,
)


def classify_candidate_facts(
    target_concept: str,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc] = (),
) -> tuple[Verdict, ...]:
    target_local = qname_local(target_concept)
    child_arc_map = {
        arc.child_qname: arc.weight
        for arc in calculation_arcs
        if arc.parent_qname == target_concept
        or qname_local(arc.parent_qname) == target_local
    }
    child_locals = {qname_local(qname) for qname in child_arc_map}

    max_val = max(
        (
            abs(float(fact.value))
            for fact in facts
            if isinstance(fact.value, (int, float))
        ),
        default=1.0,
    )
    max_val = max(1.0, max_val)

    verdicts: list[Verdict] = []
    for fact in facts:
        qname = fact.concept_qname
        q_local = qname_local(qname)
        val = float(fact.value) if isinstance(fact.value, (int, float)) else 0.0
        priority = round(abs(val) / max_val, 4)

        if qname == target_concept or q_local == target_local:
            verdicts.append(
                Verdict(
                    concept_qname=qname,
                    measure_id=target_concept,
                    decision="ACCEPT",
                    role="LEAF" if fact.dimensions else "ROOT",
                    weight=1.0,
                    priority=priority,
                )
            )
            continue

        if qname in child_arc_map or q_local in child_locals:
            verdicts.append(
                Verdict(
                    concept_qname=qname,
                    measure_id=target_concept,
                    decision="ACCEPT",
                    role="LEAF",
                    weight=child_arc_map.get(qname, 1.0),
                    priority=priority,
                )
            )
            continue

        if not isinstance(fact.value, (int, float)):
            verdicts.append(
                Verdict(
                    concept_qname=qname,
                    measure_id=target_concept,
                    decision="REJECT",
                    reject_reason="NON_NUMERIC_PROSE",
                    priority=0.0,
                )
            )
            continue

        prefix = split_concept_qname(qname)[0]
        if prefix and prefix not in CORE_PREFIXES:
            verdicts.append(
                Verdict(
                    concept_qname=qname,
                    measure_id=target_concept,
                    decision="UNKNOWN",
                    unknown_reason="UNSEEN_SIGNATURE",
                    priority=priority,
                )
            )
        else:
            verdicts.append(
                Verdict(
                    concept_qname=qname,
                    measure_id=target_concept,
                    decision="REJECT",
                    reject_reason="OTHER_STATEMENT",
                    priority=priority,
                )
            )

    return tuple(verdicts)
