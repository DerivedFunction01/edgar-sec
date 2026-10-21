"""Predict extension-concept placement from filing and taxonomy structure."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    infer_semantic_frame,
)
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.gold import PlacementPrediction


def _concept_for_atom(
    kb: EvidenceKnowledgeBase,
    atom: Atom,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc],
) -> str | None:
    lexicon = kb.taxonomy.token_lexicon
    if lexicon is None:
        return None
    candidates = {fact.concept_qname for fact in facts}
    for arc in calculation_arcs:
        candidates.add(arc.parent_qname)
        candidates.add(arc.child_qname)
    exact: list[str] = []
    broader: list[tuple[int, str]] = []
    for qname in candidates:
        candidate_atom = decompose_concept(qname, lexicon)[0]
        if candidate_atom == atom:
            exact.append(qname)
        elif candidate_atom.is_a(atom):
            broader.append((len(candidate_atom.modifiers), qname))
    if exact:
        return sorted(exact)[0]
    if broader:
        broader.sort(key=lambda item: (-item[0], item[1]))
        return broader[0][1]
    return None


def solve_placements(
    kb: EvidenceKnowledgeBase,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc] = (),
    *,
    firm: str = "",
    sector: str = "",
    year: int | str = "",
    enable_head_induction: bool = True,
) -> tuple[PlacementPrediction, ...]:
    calc_parents: dict[str, tuple[str, float]] = {
        arc.child_qname: (arc.parent_qname, arc.weight) for arc in calculation_arcs
    }
    predictions: list[PlacementPrediction] = []

    for fact in facts:
        qname = fact.concept_qname
        if qname in calc_parents:
            parent, weight = calc_parents[qname]
            predictions.append(
                PlacementPrediction(
                    concept_qname=qname,
                    predicted_parent=parent,
                    predicted_weight=weight,
                    is_abstained=False,
                )
            )
            continue

        best_rule = None
        best_spec = 0
        for rule in kb.rules:
            if rule.concept_qname == qname:
                spec, _ = kb.scope_specificity(rule.scope, firm, sector, year)
                if spec > best_spec:
                    best_spec = spec
                    best_rule = rule

        if best_rule is not None:
            predictions.append(
                PlacementPrediction(
                    concept_qname=qname,
                    predicted_parent=best_rule.target_node,
                    predicted_weight=best_rule.weight,
                    is_abstained=False,
                )
            )
            continue

        if enable_head_induction and kb.taxonomy.atom_relations is not None:
            lexicon = kb.taxonomy.token_lexicon
            if lexicon is not None:
                atom, _, _, _ = decompose_concept(qname, lexicon)
            else:
                frame = infer_semantic_frame(
                    qname,
                    kb.taxonomy,
                    unit=fact.unit,
                    balance=fact.balance,
                )
                atom = Atom(frame.prime_head, frozenset(frame.modifiers))
            edges = kb.taxonomy.atom_relations.find_inherited_edges(atom, "PART_OF")
            if edges:
                best_edge = edges[0]
                filing_name = _concept_for_atom(
                    kb, best_edge.target, facts, calculation_arcs
                )
                if filing_name is not None:
                    pred_parent = filing_name
                else:
                    head_def = kb.taxonomy.prime_head(best_edge.target.head)
                    target_concept = (
                        head_def.canonical_concept
                        if head_def and head_def.canonical_concept
                        else best_edge.target.head
                    )
                    pred_parent = (
                        f"us-gaap:{target_concept}"
                        if ":" not in target_concept
                        else target_concept
                    )
                predictions.append(
                    PlacementPrediction(
                        concept_qname=qname,
                        predicted_parent=pred_parent,
                        predicted_weight=best_edge.algebraic_weight,
                        is_abstained=False,
                    )
                )
                continue

        predictions.append(
            PlacementPrediction(
                concept_qname=qname,
                predicted_parent=None,
                predicted_weight=None,
                is_abstained=True,
            )
        )

    return tuple(predictions)
