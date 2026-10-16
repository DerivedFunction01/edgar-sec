"""Classify candidate facts for a target concept."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.schema.models import CalculationArc, Verdict, XbrlFact


def _local_name(qname: str) -> str:
    return qname.split(":")[-1]


def classify_candidate_facts(
    target_concept: str,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc] = (),
) -> tuple[Verdict, ...]:
    target_local = _local_name(target_concept)
    child_arc_map = {
        arc.child_qname: arc.weight
        for arc in calculation_arcs
        if arc.parent_qname == target_concept
        or _local_name(arc.parent_qname) == target_local
    }
    child_locals = {_local_name(qname) for qname in child_arc_map}

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
        q_local = _local_name(qname)
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

        if ":" in qname and not qname.startswith(("us-gaap:", "dei:")):
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
