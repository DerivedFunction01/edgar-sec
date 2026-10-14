"""Typed atom relations graph, inheritance lookup, and algebraic evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.schema.atoms import Atom


@dataclass(frozen=True, slots=True)
class RelationTypeSemantics:
    """Formal semantics declaration for an inter-atom relation type."""

    relation_type: str
    algebraic_class: str
    directionality: str
    is_computed: bool
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelationTypeSemantics:
        """Construct RelationTypeSemantics from dictionary."""
        return cls(
            relation_type=str(data.get("relation_type", "")).upper(),
            algebraic_class=str(data.get("algebraic_class", "")).upper(),
            directionality=str(data.get("directionality", "")).upper(),
            is_computed=bool(data.get("is_computed", False)),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class AtomRelation:
    """Directed or bidirectional edge between atom coordinates in the knowledge graph."""

    edge_id: str
    relation_type: str
    source: Atom
    target: Atom
    algebraic_weight: float = 1.0
    formula_id: str | None = None
    operator: str | None = None
    source_concept: str | None = None
    target_concept: str | None = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtomRelation:
        """Construct AtomRelation from dictionary representation."""
        return cls(
            edge_id=str(data.get("edge_id", "")),
            relation_type=str(data.get("relation_type", "")).upper(),
            source=Atom.from_dict(data.get("source", {})),
            target=Atom.from_dict(data.get("target", {})),
            algebraic_weight=float(data.get("algebraic_weight", 1.0)),
            formula_id=data.get("formula_id"),
            operator=data.get("operator"),
            source_concept=data.get("source_concept"),
            target_concept=data.get("target_concept"),
            description=str(data.get("description", "")),
        )


class AtomRelationGraph:
    """Indexed relation graph supporting inherited edge lookup over the atom lattice."""

    def __init__(
        self,
        relations: tuple[AtomRelation, ...],
        semantics: tuple[RelationTypeSemantics, ...] = (),
    ) -> None:
        """Initialize relation graph with source and target indexing."""
        self._relations = relations
        self._semantics = {s.relation_type: s for s in semantics}
        self._by_source_head: dict[str, list[AtomRelation]] = {}
        self._by_target_head: dict[str, list[AtomRelation]] = {}
        for rel in relations:
            self._by_source_head.setdefault(rel.source.head, []).append(rel)
            self._by_target_head.setdefault(rel.target.head, []).append(rel)

    @property
    def relations(self) -> tuple[AtomRelation, ...]:
        """All declared atom relations."""
        return self._relations

    @classmethod
    def load_json(
        cls, relations_path: Path | str, semantics_path: Path | str | None = None
    ) -> AtomRelationGraph:
        """Load relation graph from JSON files."""
        with open(relations_path, encoding="utf-8") as f:
            rel_data = json.load(f)
        relations = tuple(AtomRelation.from_dict(item) for item in rel_data)
        semantics: tuple[RelationTypeSemantics, ...] = ()
        if semantics_path and Path(semantics_path).is_file():
            with open(semantics_path, encoding="utf-8") as f:
                sem_data = json.load(f)
            semantics = tuple(
                RelationTypeSemantics.from_dict(item) for item in sem_data
            )
        return cls(relations, semantics)

    def find_inherited_edges(
        self, atom: Atom, relation_type: str | None = None
    ) -> list[AtomRelation]:
        """Find edges where the given atom is a taxonomic subtype of edge source."""
        candidates = self._by_source_head.get(atom.head, [])
        matched: list[AtomRelation] = []
        target_type = relation_type.upper() if relation_type else None
        for edge in candidates:
            if target_type and edge.relation_type != target_type:
                continue
            if atom.is_a(edge.source):
                matched.append(edge)
        return matched

    def find_parent_targets(
        self, atom: Atom, relation_type: str = "PART_OF"
    ) -> list[tuple[Atom, float]]:
        """Return parent atom targets and weights that this atom contributes to."""
        edges = self.find_inherited_edges(atom, relation_type)
        return [(e.target, e.algebraic_weight) for e in edges]

    def find_contra_target(self, atom: Atom) -> tuple[Atom, float] | None:
        """Return contra-target atom and netting weight if atom is a contra account."""
        edges = self.find_inherited_edges(atom, "CONTRA_OF")
        if not edges:
            return None
        return (edges[0].target, edges[0].algebraic_weight)

    def find_duals(self, atom: Atom) -> list[Atom]:
        """Find corresponding stock/flow dual atoms connected by DUAL_OF edges."""
        duals: list[Atom] = []
        for edge in self.find_inherited_edges(atom, "DUAL_OF"):
            duals.append(edge.target)
        for edge in self._by_target_head.get(atom.head, []):
            if edge.relation_type == "DUAL_OF" and atom.is_a(edge.target):
                duals.append(edge.source)
        return duals
