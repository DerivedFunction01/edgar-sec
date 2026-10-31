"""Predict extension-concept placement from filing and taxonomy structure."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    infer_semantic_frame,
)
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    XbrlFact,
    split_concept_qname,
)
from edgar_sec.engine.xbrl.solve.gold import PlacementPrediction


class _CandidateAtomIndex:
    """Candidate decompositions for one solve call, built exactly once.

    Atom-to-concept resolution is memoised by target atom over this
    fixed index, so induction lookups never re-decompose candidates.
    """

    def __init__(
        self,
        lexicon: TokenLexicon,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
    ) -> None:
        self._lexicon = lexicon
        candidates = {fact.concept_qname for fact in facts}
        for arc in calculation_arcs:
            candidates.add(arc.parent_qname)
            candidates.add(arc.child_qname)
        self._atoms: dict[str, Atom] = {
            qname: decompose_concept(qname, lexicon)[0] for qname in candidates
        }
        self._concepts: dict[Atom, str | None] = {}

    def atom_for(self, qname: str) -> Atom:
        atom = self._atoms.get(qname)
        if atom is None:
            atom = decompose_concept(qname, self._lexicon)[0]
            self._atoms[qname] = atom
        return atom

    def concept_for_atom(self, atom: Atom) -> str | None:
        if atom in self._concepts:
            return self._concepts[atom]
        exact: list[str] = []
        broader: list[tuple[int, str]] = []
        for qname, candidate_atom in self._atoms.items():
            if candidate_atom == atom:
                exact.append(qname)
            elif candidate_atom.is_a(atom):
                broader.append((len(candidate_atom.modifiers), qname))
        result: str | None = None
        if exact:
            result = sorted(exact)[0]
        elif broader:
            broader.sort(key=lambda item: (-item[0], item[1]))
            result = broader[0][1]
        self._concepts[atom] = result
        return result


def _concept_for_atom(
    kb: EvidenceKnowledgeBase,
    atom: Atom,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc],
) -> str | None:
    lexicon = kb.taxonomy.token_lexicon
    if lexicon is None:
        return None
    return _CandidateAtomIndex(lexicon, facts, calculation_arcs).concept_for_atom(atom)


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
    candidate_index: _CandidateAtomIndex | None = None

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
                if candidate_index is None:
                    candidate_index = _CandidateAtomIndex(
                        lexicon, facts, calculation_arcs
                    )
                atom = candidate_index.atom_for(qname)
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
                filing_name = (
                    candidate_index.concept_for_atom(best_edge.target)
                    if candidate_index is not None
                    else _concept_for_atom(
                        kb, best_edge.target, facts, calculation_arcs
                    )
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
                        if not split_concept_qname(target_concept)[0]
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
