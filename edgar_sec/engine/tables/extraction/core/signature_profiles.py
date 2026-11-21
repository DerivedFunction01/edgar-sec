"""Signature profile types, assembled from the subject-evidence map.

The map is the shared contract: its measured terms, edges, channel
weights, and inheritance pricing in the competition layer's shapes.
"""

# Weights are smoothed log odds ratios of member vs foreign-member
# channel presence; foreign support joins families on term+channel.

from __future__ import annotations

import math
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subject_evidence import load_map

PROV_SUBJECT_EVIDENCE_MAP = "subject-evidence-map:v1"

CHANNELS = ("caption", "leadin", "notehead", "lead_title", "stub")
_MAP_CHANNEL = {"note_heading": "notehead"}
DEFAULT_INHERITANCE_FACTOR = 0.5


@dataclass(frozen=True, slots=True)
class SignatureTerm:
    """One measured profile term in one evidence channel."""

    family: str
    channel: str
    term: str
    weight: float
    member_hits: int
    foreign_hits: int
    provenance: str = PROV_SUBJECT_EVIDENCE_MAP


@dataclass(frozen=True, slots=True)
class ContainmentEdge:
    """A measured edge: subset vocabulary legitimately inside a parent."""

    subset: str
    parent: str
    discount: float
    support: str
    provenance: str = PROV_SUBJECT_EVIDENCE_MAP


@dataclass(frozen=True, slots=True)
class LadderTerm:
    """One debt/lease shared term with its per-subject supports."""

    term: str
    support_debt: int
    support_lease: int
    provenance: str = PROV_SUBJECT_EVIDENCE_MAP


def _channel(name: str) -> str:
    return _MAP_CHANNEL.get(name, name)


def _weight(support: int, members: int, foreign: int, foreign_members: int) -> float:
    """Smoothed log odds of channel presence, member vs foreign."""
    p_in = (support + 1.0) / (members + 2.0)
    p_out = (foreign + 1.0) / (foreign_members + 2.0)
    return round(min(max(math.log(p_in / p_out), 0.0), 3.0), 3)


def _assemble() -> tuple[tuple[SignatureTerm, ...], tuple[ContainmentEdge, ...]]:
    """Assemble terms and edges from the map, the profile's only source."""
    evidence = load_map()
    members = evidence.labelled_members
    total_members = sum(members.values())
    by_term: dict[tuple[str, str], int] = {}
    for spec in evidence.terms:
        key = (_channel(spec.channel), spec.term)
        by_term[key] = by_term.get(key, 0) + spec.support
    terms = []
    for spec in evidence.terms:
        channel = _channel(spec.channel)
        foreign = by_term[(channel, spec.term)] - spec.support
        terms.append(
            SignatureTerm(
                spec.family,
                channel,
                spec.term,
                _weight(
                    spec.support,
                    members[spec.family],
                    foreign,
                    total_members - members[spec.family],
                ),
                spec.support,
                foreign,
            )
        )
    edges = tuple(
        ContainmentEdge(
            edge.family,
            edge.other_family,
            edge.share,
            f"{edge.kind} support {edge.support} ({edge.basis})",
        )
        for edge in evidence.containment_edges
    )
    return tuple(terms), edges


SIGNATURE_TERMS, CONTAINMENT_EDGES = _assemble()

LADDER_EDGE_TERMS: tuple[LadderTerm, ...] = tuple(
    LadderTerm(spec.term, spec.support_debt, spec.support_lease)
    for spec in load_map().edge_terms
    if spec.edge == "debt_maturity/lease_maturity"
)

CHANNEL_WEIGHTS: dict[str, float] = {
    _channel(spec.channel): spec.weight for spec in load_map().channels
}

INHERITANCE_FACTORS: dict[str, float] = {
    row.family: row.title_decides_share for row in load_map().inheritance
}
