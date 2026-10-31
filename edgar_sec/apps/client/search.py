"""Tokenizer-driven close-match fact search over one filing's facts.

Search is retrieval, never equivalence: hits are ranked candidates
for inspection and never feed query() or solver results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    RankedEquivalent,
    coordinate_diff,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

if TYPE_CHECKING:
    from edgar_sec.apps.client.facts import DisplayRecord

_UNKNOWN_HEAD = "H_UNKNOWN"


@dataclass(frozen=True, slots=True)
class FactSearchHit:
    """One concept ranked against a search target, with its facts."""

    qname: str
    atom: Atom
    tier: str
    rule: str
    modifier_distance: int
    target_only: tuple[str, ...]
    hit_only: tuple[str, ...]
    swapped: tuple[str, str] | None
    residual_mass: tuple[int, int]
    facts: tuple[XbrlFact, ...]


@dataclass(frozen=True, slots=True)
class FactSearch:
    """A term search's outcome: the resolved target and its ranked hits.

    Partial marks a term whose decomposition left residuals or an
    unknown head; its hits rank the claimed coordinates only.
    """

    term: str
    target_atom: Atom | None
    term_residuals: tuple[str, ...] = ()
    partial: bool = False
    hits: tuple[FactSearchHit, ...] = ()


def resolve_search_targets(
    term: str, taxonomy: DomainTaxonomy
) -> tuple[tuple[Atom, ...], tuple[str, ...]]:
    """Resolve a search term to target atoms, mirroring the query engine.

    Declared alias specs win on the normalized term; any other term
    is decomposed, and its unclaimed tokens ride along as residuals.
    """
    normalized = "".join(
        character.casefold() for character in term if character.isalnum()
    )
    aliases = {record.alias: record.targets for record in taxonomy.query_aliases}
    if normalized in aliases:
        return aliases[normalized], ()
    lexicon = taxonomy.token_lexicon
    if lexicon is None:
        return (), ()
    atom, residuals, _, _ = decompose_concept(term, lexicon)
    return (atom,), residuals


def _rank_key(hit: FactSearchHit) -> tuple:
    """Ladder order: tier, modifier distance, residual mass, qname."""
    intent, total = hit.residual_mass
    return (
        0 if hit.tier == EXACT else 1,
        hit.modifier_distance,
        intent,
        total,
        hit.qname,
    )


def _to_hit(
    target: Atom,
    item: RankedEquivalent,
    facts: list[XbrlFact],
    residual_mass: tuple[int, int],
) -> FactSearchHit:
    """Assemble one ranked equivalent into a search hit with its diff."""
    diff = coordinate_diff(target, item.atom, item.rule)
    return FactSearchHit(
        qname=item.qname,
        atom=item.atom,
        tier=item.tier,
        rule=item.rule,
        modifier_distance=item.modifier_distance,
        target_only=diff.target_only,
        hit_only=diff.candidate_only,
        swapped=diff.swapped,
        residual_mass=residual_mass,
        facts=tuple(facts),
    )


def rank_search_hits(
    targets: Sequence[Atom],
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    *,
    limit: int | None = None,
) -> tuple[FactSearchHit, ...]:
    """Rank a fact pool's concepts against target atoms by the ladder.

    One routine serves the facade search and the builder's close_to
    stage; classification and diffs run on the records' stated atoms.
    """
    grouped: dict[str, list[XbrlFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.concept_qname, []).append(fact)
    candidates = tuple(
        sorted((qname, records[qname].atom) for qname in grouped if qname in records)
    )
    if not candidates:
        return ()
    counts = {qname: records[qname].residual_mass for qname, _ in candidates}
    groups = tuple(taxonomy.sibling_groups) or None
    best: dict[str, FactSearchHit] = {}
    for target in targets:
        ranked = rank_equivalents(
            "",
            target,
            candidates,
            (),
            sibling_groups=groups,
            residual_counts=counts,
        )
        for item in ranked:
            hit = _to_hit(target, item, grouped[item.qname], counts[item.qname])
            current = best.get(item.qname)
            if current is None or _rank_key(hit) < _rank_key(current):
                best[item.qname] = hit
    hits = tuple(sorted(best.values(), key=_rank_key))
    return hits if limit is None else hits[:limit]


def search_facts(
    term: str,
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    *,
    limit: int | None = None,
) -> FactSearch:
    """Search one filing's facts for close matches to a term.

    A term leaving residuals, or decomposing to an unknown head,
    still ranks its claimed coordinates and is marked partial.
    """
    targets, residuals = resolve_search_targets(term, taxonomy)
    usable = tuple(atom for atom in targets if atom.head != _UNKNOWN_HEAD)
    partial = bool(residuals) or len(usable) != len(targets)
    hits = (
        rank_search_hits(usable, facts, records, taxonomy, limit=limit)
        if usable
        else ()
    )
    return FactSearch(
        term=term,
        target_atom=targets[0] if len(targets) == 1 else None,
        term_residuals=residuals,
        partial=partial,
        hits=hits,
    )


def close_match_qnames(
    term: str,
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
) -> frozenset[str]:
    """Concept qnames of a term's EXACT and NEAR matches in a fact pool."""
    result = search_facts(term, facts, records, taxonomy)
    return frozenset(hit.qname for hit in result.hits)


__all__ = [
    "FactSearch",
    "FactSearchHit",
    "close_match_qnames",
    "rank_search_hits",
    "resolve_search_targets",
    "search_facts",
]
