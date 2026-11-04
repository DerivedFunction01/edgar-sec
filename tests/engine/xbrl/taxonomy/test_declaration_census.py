"""Declaration census over the taxonomy data.

Every frame, modifier, and lexicon entry fires on the archive universe,
the constructed battery, or a witness built from its own phrase.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept_expression,
    split_camel_case,
)
from edgar_sec.engine.xbrl.normalize.lexicon import EvidenceContext, LexiconEntry
from edgar_sec.engine.xbrl.normalize.numbers import collapse_number_phrases
from edgar_sec.engine.xbrl.schema.models import qname_local
from edgar_sec.engine.xbrl.taxonomy.archive import (
    CURRENT_SLICES,
    current_table,
    load_slice,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.engine.xbrl.taxonomy.item_types import (
    item_type_local,
    percent_coordinate_rule,
    text_coordinate_rule,
)
from tests.support import load_fixture

_EVIDENCE = EvidenceContext(accession="census", qname="", satisfied=True)


@dataclass
class _Census:
    taxonomy: DomainTaxonomy
    live_entries: set[int] = field(default_factory=set)
    atom_modifiers: set[str] = field(default_factory=set)
    frame_hits: dict[str, list[tuple[float, frozenset]]] = field(default_factory=dict)


def _witness_names(entry: LexiconEntry) -> tuple[str, ...]:
    """Constructed names built from an entry's own phrase, in filed shapes."""
    parts = []
    for token in entry.phrase:
        if token == "num":
            parts.append("5")
        elif token == "ord":
            parts.append("Third")
        else:
            parts.append(token.capitalize())
    base = "ext:" + "".join(parts)
    names = [base, base + "Abstract", base + "Net"]
    if entry.scope_next:
        names.append(base + entry.scope_next[0].capitalize())
    return tuple(names)


def _observe(
    census: _Census, taxonomy: DomainTaxonomy, qname: str, evidence=None
) -> None:
    """Record one decomposition's entry, modifier, and frame evidence."""
    lexicon = taxonomy.token_lexicon
    assert lexicon is not None
    expr = decompose_concept_expression(qname, lexicon, evidence=evidence)
    for match in expr.matches:
        census.live_entries.add(id(match.entry))
    census.atom_modifiers.update(expr.atom.modifiers)
    tokens, _, _ = collapse_number_phrases(split_camel_case(qname_local(qname)))
    lowered = tuple(token.lower() for token in tokens)
    for frame in taxonomy.grammatical_frames:
        prefix = frame.prefix_tokens
        if lowered[: len(prefix)] == prefix:
            census.frame_hits.setdefault(frame.frame_id, []).append(
                (expr.direction, expr.atom.modifiers)
            )


@pytest.fixture(scope="module")
def census() -> _Census:
    """One census pass over the universe, the battery, and witnesses."""
    taxonomy = load_domain_taxonomy()
    lexicon = taxonomy.token_lexicon
    assert lexicon is not None
    result = _Census(taxonomy=taxonomy)
    names = sorted(current_table())
    battery = [row["name"] for row in load_fixture("xbrl/act_battery.json")["rows"]]
    for qname in names + battery:
        _observe(result, taxonomy, qname)
    gated = {e.phrase[0] for e in lexicon.entries if e.requires_evidence}
    for qname in names:
        tokens = {t.lower() for t in split_camel_case(qname_local(qname))}
        if gated & tokens:
            _observe(result, taxonomy, qname, evidence=_EVIDENCE)
    for entry in lexicon.entries:
        if id(entry) in result.live_entries:
            continue
        for witness in _witness_names(entry):
            _observe(result, taxonomy, witness, evidence=_EVIDENCE)
    return result


def test_no_dead_lexicon_entries(census: _Census) -> None:
    """Every lexicon entry is selected on some universe, battery, or witness name."""
    taxonomy = census.taxonomy
    assert taxonomy.token_lexicon is not None
    dead = [
        " ".join(entry.phrase)
        for entry in taxonomy.token_lexicon.entries
        if id(entry) not in census.live_entries
    ]
    assert dead == []


def test_no_dead_frames(census: _Census) -> None:
    """Every frame's declared direction (and act, when declared) is realized."""
    taxonomy = census.taxonomy
    dead = []
    for frame in taxonomy.grammatical_frames:
        hits = census.frame_hits.get(frame.frame_id, [])
        fired = any(
            direction == frame.direction
            and (frame.act_modifier is None or frame.act_modifier in modifiers)
            for direction, modifiers in hits
        )
        if not fired:
            dead.append(frame.frame_id)
    assert dead == []


def _referenced_modifiers(taxonomy: DomainTaxonomy) -> set[str]:
    """Modifier ids the relation, alias, group, and default data consult."""
    referenced: set[str] = set()
    if taxonomy.atom_relations is not None:
        for relation in taxonomy.atom_relations.relations:
            referenced.update(relation.source.modifiers)
            referenced.update(relation.target.modifiers)
    for alias in taxonomy.query_aliases:
        for target in alias.targets:
            referenced.update(target.modifiers)
    for group in taxonomy.sibling_groups:
        referenced.update(group.members)
    for coordinate in taxonomy.default_coordinates:
        referenced.update(coordinate.identity_modifiers)
        referenced.add(coordinate.presumed_modifier)
    for frame in taxonomy.grammatical_frames:
        if frame.act_modifier is not None:
            referenced.add(frame.act_modifier)
    return referenced


def _type_channel_modifiers(taxonomy: DomainTaxonomy) -> set[str]:
    """Modifier ids asserted from declared item types over the universe."""
    fired: set[str] = set()
    item_types = set()
    for taxonomy_name, version in CURRENT_SLICES:
        for declaration in load_slice(taxonomy_name, version):
            if declaration.item_type is not None:
                item_types.add(item_type_local(declaration.item_type))
    for rule in (text_coordinate_rule(taxonomy), percent_coordinate_rule(taxonomy)):
        if rule is not None and item_types & set(rule.item_types):
            fired.add(rule.modifier_id)
    return fired


def test_no_dead_modifiers(census: _Census) -> None:
    """Every modifier record lands in an atom or is consulted as data."""
    taxonomy = census.taxonomy
    assert taxonomy.token_lexicon is not None
    live = set(census.atom_modifiers)
    live.update(_referenced_modifiers(taxonomy))
    live.update(_type_channel_modifiers(taxonomy))
    for entry in taxonomy.token_lexicon.entries:
        if id(entry) in census.live_entries:
            live.update(entry.asserted_modifier_ids())
    dead = [
        modifier.modifier_id
        for modifier in taxonomy.subatomic_modifiers
        if modifier.modifier_id not in live
    ]
    assert dead == []
