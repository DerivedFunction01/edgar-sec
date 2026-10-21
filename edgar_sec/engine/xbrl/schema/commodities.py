"""Commodity instrument graph: IS_A category closure and attested firm links."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


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
    """A firm's attested relation to one instrument, citing corpus concepts."""

    firm: str
    instrument: str
    relation: str
    concepts: tuple[str, ...]


class CommodityGraph:
    """DAG of commodity nodes with IS_A-only category expansion."""

    def __init__(
        self,
        nodes: tuple[CommodityNode, ...],
        edges: tuple[tuple[str, str, str], ...],
        links: tuple[FirmCommodityLink, ...],
        unseeded_classes: tuple[str, ...] = (),
    ) -> None:
        """Index nodes, IS_A parents, and firm links for lookup."""
        self._nodes = {node.id: node for node in nodes}
        self._parents: dict[str, set[str]] = {}
        self._children: dict[str, set[str]] = {}
        for source, target, edge_type in edges:
            if edge_type != "IS_A":
                continue
            self._parents.setdefault(source, set()).add(target)
            self._children.setdefault(target, set()).add(source)
        self._edges = edges
        self._links = links
        self._unseeded = unseeded_classes

    @classmethod
    def load_json(cls, path: Path | str) -> CommodityGraph:
        """Load the commodity graph from its taxonomy JSON file."""
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
        links = tuple(
            FirmCommodityLink(
                firm=str(item["firm"]),
                instrument=str(item["instrument"]),
                relation=str(item["relation"]),
                concepts=tuple(str(c) for c in item.get("concepts", [])),
            )
            for item in data.get("links", [])
        )
        return cls(nodes, edges, links, tuple(data.get("unseeded_classes", [])))

    @property
    def nodes(self) -> tuple[CommodityNode, ...]:
        """All seeded graph nodes."""
        return tuple(self._nodes.values())

    @property
    def links(self) -> tuple[FirmCommodityLink, ...]:
        """All attested firm-to-instrument links."""
        return self._links

    @property
    def unseeded_classes(self) -> tuple[str, ...]:
        """Designed classes recorded without nodes (no attested links yet)."""
        return self._unseeded

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

    def links_for(
        self, instrument: str | None = None, relation: str | None = None
    ) -> tuple[FirmCommodityLink, ...]:
        """Firm links filtered by instrument and/or relation."""
        return tuple(
            link
            for link in self._links
            if (instrument is None or link.instrument == instrument)
            and (relation is None or link.relation == relation)
        )
