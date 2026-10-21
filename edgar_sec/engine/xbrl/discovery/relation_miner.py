"""Mine atom relation candidates from bundle calculation and presentation arcs."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from edgar_sec.engine.xbrl.discovery.fixture_miner import BundleFacts
from edgar_sec.engine.xbrl.evidence.mining import SupportCounter
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.schema.atoms import Atom


@dataclass(frozen=True, slots=True)
class MinedRelation:
    """An arc-attested atom pair with firm/SIC support and an evidence tier."""

    source: Atom
    target: Atom
    relation_type: str
    evidence: str
    weight: float
    firm_count: int
    sic_count: int
    source_concept: str
    target_concept: str


def _is_structural(qname: str) -> bool:
    """True for abstracts, line items, and text blocks (never edge endpoints)."""
    local = qname.partition(":")[2]
    return local.endswith(("Abstract", "LineItems", "TextBlock"))


def mine_atom_relations(
    bundles: Sequence[BundleFacts],
    lexicon: TokenLexicon,
    *,
    min_calc_firms: int = 3,
    min_placement_firms: int = 5,
) -> tuple[MinedRelation, ...]:
    """Generalize arc pairs to head-level edges over modifier intersections."""
    atoms: dict[str, Atom] = {}

    def atom_of(qname: str) -> Atom:
        if qname not in atoms:
            atom, _res, _dir, _idx = decompose_concept(qname, lexicon)
            atoms[qname] = atom
        return atoms[qname]

    support = SupportCounter()
    keys: set[tuple[str, str, str]] = set()
    child_mods: dict[tuple[str, str, str], list[frozenset[str]]] = defaultdict(list)
    parent_mods: dict[tuple[str, str, str], list[frozenset[str]]] = defaultdict(list)
    weights: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    exemplars: dict[tuple[str, str, str], Counter] = defaultdict(Counter)

    def observe(
        bundle: BundleFacts,
        relation_type: str,
        parent_qname: str,
        child_qname: str,
        weight: float,
    ) -> None:
        if _is_structural(parent_qname) or _is_structural(child_qname):
            return
        if relation_type == "PLACEMENT" and (
            parent_qname.partition(":")[2].endswith(("Axis", "Domain"))
            or child_qname.partition(":")[2].endswith(("Axis", "Domain"))
        ):
            return
        if parent_qname == child_qname:
            return
        child, parent = atom_of(child_qname), atom_of(parent_qname)
        if child.head == "H_UNKNOWN" or parent.head == "H_UNKNOWN":
            return
        key = (relation_type, child.head, parent.head)
        keys.add(key)
        support.observe(key, bundle.firm, str(bundle.sic_code))
        child_mods[key].append(child.modifiers)
        parent_mods[key].append(parent.modifiers)
        weights[key][weight] += 1
        exemplars[key][(child_qname, parent_qname)] += 1

    for bundle in bundles:
        if bundle.calculation_arcs is not None:
            arcs = bundle.calculation_arcs.to_pylist()
            for arc in arcs:
                observe(
                    bundle,
                    "PART_OF",
                    arc["parent_qname"],
                    arc["child_qname"],
                    float(arc.get("weight") or 1.0),
                )
        if bundle.presentation_arcs is not None:
            for arc in bundle.presentation_arcs.to_pylist():
                observe(
                    bundle, "PLACEMENT", arc["parent_qname"], arc["child_qname"], 1.0
                )

    mined: list[MinedRelation] = []
    for key in keys:
        relation_type, child_head, parent_head = key
        firm_count = support.firm_count(key)
        threshold = (
            min_calc_firms if relation_type == "PART_OF" else min_placement_firms
        )
        if firm_count < threshold:
            continue
        shared_child = frozenset.intersection(*child_mods[key])
        shared_parent = frozenset.intersection(*parent_mods[key])
        source_concept, target_concept = exemplars[key].most_common(1)[0][0]
        mined.append(
            MinedRelation(
                source=Atom(child_head, shared_child),
                target=Atom(parent_head, shared_parent),
                relation_type=relation_type,
                evidence="calculation"
                if relation_type == "PART_OF"
                else "presentation",
                weight=float(weights[key].most_common(1)[0][0]),
                firm_count=firm_count,
                sic_count=support.sic_count(key),
                source_concept=source_concept,
                target_concept=target_concept,
            )
        )
    mined.sort(
        key=lambda r: (-r.firm_count, r.relation_type, r.source.head, r.target.head)
    )
    return tuple(mined)
