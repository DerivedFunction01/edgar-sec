"""Geography resolution: pure functions over the substrate's records.

Resolution returns facts — node lookup, ancestor walks,
containment, domicile-relative status. It decides no consumer's
verdict: a tag, a seat, or a unit class stays with its consumer.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.world.geography_edges import EDGES, GeoEdge
from edgar_sec.domain.world.geography_places import COUNTRIES, REGIONS


@dataclass(frozen=True, slots=True)
class GeoResolution:
    """A node resolved relative to a domicile: facts, not a verdict."""

    canonical_node: str
    is_domestic: bool
    is_foreign: bool
    ancestor_regions: tuple[str, ...]
    decomposition_schemes: tuple[str, ...]


def nodes() -> tuple[str, ...]:
    """Every declared node: the DAG's countries and region members."""
    return tuple(
        sorted({edge.child for edge in EDGES} | {edge.parent for edge in EDGES})
    )


def decomposition_schemes() -> tuple[str, ...]:
    """The hierarchy's decomposition schemes, in declaration order."""
    return tuple(dict.fromkeys(edge.scheme for edge in EDGES))


def domicile_node_for(edges: tuple[GeoEdge, ...], country_code: str) -> str | None:
    """The country node an edge set declares for a domicile code."""
    node = f"country:{country_code.upper()}"
    if any(node in (edge.child, edge.parent) for edge in edges):
        return node
    return None


def domicile_node(country_code: str) -> str | None:
    """The declared country node for a domicile country code, if any."""
    return domicile_node_for(EDGES, country_code)


def match_node(edges: tuple[GeoEdge, ...], token: str) -> str | None:
    """The node an edge set declares for a token, scanning in order.
    Per edge, exact match wins over local-part match; first edge
    decides. Lexicon indexicals stay with the lexicon's consumer.
    """
    cleaned = token.strip()
    local = cleaned.rsplit(":", 1)[-1].lower()
    for edge in edges:
        if cleaned in (edge.child, edge.parent):
            return edge.child if cleaned == edge.child else edge.parent
        child_local = edge.child.rsplit(":", 1)[-1].lower()
        parent_local = edge.parent.rsplit(":", 1)[-1].lower()
        if local in (child_local, parent_local):
            return edge.child if local == child_local else edge.parent
    return None


def node_for_token(token: str) -> str | None:
    """The declared node a raw token or node names, if any."""
    return match_node(EDGES, token)


def _walk(
    edges: tuple[GeoEdge, ...], node: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ancestors_found: list[str] = []
    schemes: list[str] = []
    frontier = [node]
    visited = {node}
    while frontier:
        current = frontier.pop(0)
        for edge in edges:
            if edge.child == current:
                if edge.parent not in visited:
                    visited.add(edge.parent)
                    frontier.append(edge.parent)
                    ancestors_found.append(edge.parent)
                if edge.scheme not in schemes:
                    schemes.append(edge.scheme)
    return tuple(ancestors_found), tuple(schemes)


def ancestors(node: str, edges: tuple[GeoEdge, ...] = EDGES) -> tuple[str, ...]:
    """Ancestor regions of a node, breadth-first, in walk order."""
    return _walk(edges, node)[0]


def is_contained(child: str, ancestor: str, edges: tuple[GeoEdge, ...] = EDGES) -> bool:
    """Whether child is the ancestor node itself or sits under it."""
    return child == ancestor or ancestor in ancestors(child, edges)


def resolve_node(
    node: str,
    domicile_code: str = "US",
    edges: tuple[GeoEdge, ...] = EDGES,
) -> GeoResolution:
    """Resolve a known node against an edge set, domicile-relative.
    Domestic means the domicile's own country node exactly; a node
    the edge set does not declare resolves with no ancestors.
    """
    domicile = domicile_node_for(edges, domicile_code)
    target_ancestors, schemes = _walk(edges, node)
    return GeoResolution(
        canonical_node=node,
        is_domestic=node == domicile,
        is_foreign=node != domicile,
        ancestor_regions=target_ancestors,
        decomposition_schemes=schemes,
    )


def resolve(
    token_or_node: str,
    domicile_code: str = "US",
    edges: tuple[GeoEdge, ...] = EDGES,
) -> GeoResolution | None:
    """Resolve a token or node against an edge set, domicile-relative."""
    target = match_node(edges, token_or_node)
    if target is None:
        return None
    return resolve_node(target, domicile_code, edges)


def place_terms() -> tuple[str, ...]:
    """The place vocabulary: country and region names and phrases.
    Membership is the whole contract — no term here admits, tags,
    or seats anything by itself.
    """
    terms = {
        phrase
        for record in (*COUNTRIES.values(), *REGIONS.values())
        for phrase in (record.name.lower(), *record.phrases)
    }
    return tuple(sorted(terms))


__all__ = [
    "GeoResolution",
    "ancestors",
    "decomposition_schemes",
    "domicile_node",
    "domicile_node_for",
    "is_contained",
    "match_node",
    "node_for_token",
    "nodes",
    "place_terms",
    "resolve",
    "resolve_node",
]
