"""Domain graph: IS_A category closure and pattern-derived firm links."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.schema.atoms import Atom


@dataclass(frozen=True, slots=True)
class CommodityNode:
    """A class, group, or instrument coordinate in the commodity DAG."""

    id: str
    kind: str
    klass: str = ""
    base: str = ""
    form: str = ""
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class FirmCommodityLink:
    """A firm's derived relation to one instrument, citing corpus concepts."""

    firm: str
    instrument: str
    relation: str
    concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LinkPattern:
    """Declared coordinate pattern deriving firm links from concept atoms."""

    instrument: str
    relation: str
    head: str = ""
    require_mods: tuple[str, ...] = ()
    require_any_mods: tuple[str, ...] = ()
    mods_within: tuple[str, ...] | None = None
    tokens_all: tuple[str, ...] = ()
    tokens_any: tuple[str, ...] = ()
    tokens_none: tuple[str, ...] = ()
    textblock: str = "exclude"

    def matches(self, atom: Atom, tokens: tuple[str, ...]) -> bool:
        """True when a concept's atom and name tokens satisfy the pattern."""
        if self.head and atom.head != self.head:
            return False
        mods = set(atom.modifiers)
        if not set(self.require_mods) <= mods:
            return False
        if self.require_any_mods and not set(self.require_any_mods) & mods:
            return False
        if self.mods_within is not None and not mods <= set(self.mods_within):
            return False
        token_set = set(tokens)
        if not set(self.tokens_all) <= token_set:
            return False
        if self.tokens_any and not set(self.tokens_any) & token_set:
            return False
        if set(self.tokens_none) & token_set:
            return False
        # The atom's text coordinate decides when it carries one; a
        # declaration-less atom falls back to the name-token test.
        is_textblock = "M_TEXT_NODE" in mods or {"text", "block"} <= token_set
        if self.textblock == "exclude" and is_textblock:
            return False
        return self.textblock != "require" or is_textblock


class CommodityGraph:
    """DAG of commodity nodes with IS_A-only category expansion."""

    def __init__(
        self,
        nodes: tuple[CommodityNode, ...],
        edges: tuple[tuple[str, str, str], ...],
        link_patterns: tuple[LinkPattern, ...],
        unseeded_classes: tuple[str, ...] = (),
    ) -> None:
        """Index nodes, IS_A parents, and link patterns for derivation."""
        self._nodes = {node.id: node for node in nodes}
        self._parents: dict[str, set[str]] = {}
        self._children: dict[str, set[str]] = {}
        for source, target, edge_type in edges:
            if edge_type != "IS_A":
                continue
            self._parents.setdefault(source, set()).add(target)
            self._children.setdefault(target, set()).add(source)
        self._edges = edges
        self._link_patterns = link_patterns
        self._unseeded = unseeded_classes

    @classmethod
    def load_json(cls, path: Path | str) -> CommodityGraph:
        """Load the domain graph from its taxonomy JSON file."""
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        nodes = tuple(
            CommodityNode(
                id=str(item["id"]),
                kind=str(item["kind"]),
                klass=str(item.get("class", "")),
                base=str(item.get("base", "")),
                form=str(item.get("form", "")),
                origin=item.get("origin"),
            )
            for item in data.get("nodes", [])
        )
        edges = tuple(
            (str(e["source"]), str(e["target"]), str(e["type"]))
            for e in data.get("edges", [])
        )
        patterns = tuple(
            LinkPattern(
                instrument=str(item["instrument"]),
                relation=str(item["relation"]),
                head=str(item.get("head", "")),
                require_mods=tuple(item.get("require_mods", ())),
                require_any_mods=tuple(item.get("require_any_mods", ())),
                mods_within=(
                    tuple(item["mods_within"]) if "mods_within" in item else None
                ),
                tokens_all=tuple(item.get("tokens_all", ())),
                tokens_any=tuple(item.get("tokens_any", ())),
                tokens_none=tuple(item.get("tokens_none", ())),
                textblock=str(item.get("textblock", "exclude")),
            )
            for item in data.get("link_patterns", [])
        )
        return cls(nodes, edges, patterns, tuple(data.get("unseeded_classes", [])))

    @property
    def nodes(self) -> tuple[CommodityNode, ...]:
        """All seeded graph nodes."""
        return tuple(self._nodes.values())

    @property
    def link_patterns(self) -> tuple[LinkPattern, ...]:
        """Declared coordinate patterns from which firm links derive."""
        return self._link_patterns

    @property
    def unseeded_classes(self) -> tuple[str, ...]:
        """Designed classes recorded without nodes (no attested links yet)."""
        return self._unseeded

    def derive_links(
        self,
        firm: str,
        concepts: Iterable[str],
        classify: Callable[[str], tuple[Atom, tuple[str, ...]]],
    ) -> tuple[FirmCommodityLink, ...]:
        """Derive a firm's links by matching its concepts against patterns."""
        classified = {concept: classify(concept) for concept in concepts}
        matched_by_link: dict[tuple[str, str], set[str]] = {}
        for pattern in self._link_patterns:
            matched = matched_by_link.setdefault(
                (pattern.instrument, pattern.relation), set()
            )
            for concept, (atom, tokens) in classified.items():
                if pattern.matches(atom, tokens):
                    matched.add(concept)
        return tuple(
            FirmCommodityLink(
                firm=firm,
                instrument=instrument,
                relation=relation,
                concepts=tuple(sorted(matched)),
            )
            for (instrument, relation), matched in matched_by_link.items()
            if matched
        )

    def expand(self, node_id: str) -> frozenset[str]:
        """Category expansion: node plus everything under it via IS_A only."""
        seen = {node_id}
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for child in self._children.get(current, ()):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return frozenset(seen)
