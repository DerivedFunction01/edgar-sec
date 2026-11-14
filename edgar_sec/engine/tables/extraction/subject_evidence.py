"""Subject-evidence map: measured caption/prose vocabulary, as data.

The map beside this module (subject_evidence_map.json) is the improvement
programme's shared contract — per-term subject evidence, measured edges,
inheritance pricing, Step 0 weights; free-text only, closure never negative.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MAP_FILE = "subject_evidence_map.json"
MAP_VERSION = "1"
CLOSURE_POLICY = "corroboration_only_never_negative"
CHANNELS = ("caption", "note_heading", "lead_title", "leadin", "stub")


@dataclass(frozen=True, slots=True)
class TermSpec:
    """One measured term: support/share/confidence over the corpora."""

    family: str
    channel: str
    term: str
    support: int
    support_b: int
    support_d: int
    share: float
    confidence: float
    source: str


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """One channel's Step 0 pricing: presence and decision counts."""

    channel: str
    weight: float
    presence_b: float
    presence_d: float
    correct_b: int
    wrong_b: int
    correct_d: int
    wrong_d: int


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    """One measured containment or shared-evidence edge."""

    kind: str
    family: str
    other_family: str
    support: int
    share: float
    named: bool
    basis: str


@dataclass(frozen=True, slots=True)
class EdgeTermSpec:
    """One term shared by an edge's two families, with its supports."""

    edge: str
    term: str
    support_debt: int
    support_lease: int


@dataclass(frozen=True, slots=True)
class AbsenceSpec:
    """A family the corpus priced as carrying no term evidence."""

    family: str
    labelled_members: int
    reason: str


@dataclass(frozen=True, slots=True)
class InheritanceSpec:
    """Header/title inheritance pricing for one family."""

    family: str
    members: int
    title_decides_support: int
    title_decides_share: float
    stub_wrong_support: int


@dataclass(frozen=True, slots=True)
class SubjectEvidenceMap:
    """The whole map, loaded once from its versioned data file."""

    version: str
    closure_policy: str
    families: tuple[str, ...]
    labelled_members: dict[str, int]
    channels: tuple[ChannelSpec, ...]
    terms: tuple[TermSpec, ...]
    containment_edges: tuple[EdgeSpec, ...]
    edge_terms: tuple[EdgeTermSpec, ...]
    inheritance: tuple[InheritanceSpec, ...]
    priced_absences: tuple[AbsenceSpec, ...]

    def terms_for(
        self, family: str, channel: str | None = None
    ) -> tuple[TermSpec, ...]:
        """The family's measured terms, optionally for one channel."""
        return tuple(
            t
            for t in self.terms
            if t.family == family and (channel is None or t.channel == channel)
        )

    def channel_weight(self, channel: str) -> float | None:
        """The channel's measured weight, or None when unpriced."""
        for spec in self.channels:
            if spec.channel == channel:
                return spec.weight
        return None

    def edges_for(self, family: str) -> tuple[EdgeSpec, ...]:
        """Measured edges touching a family, in either direction."""
        return tuple(
            e
            for e in self.containment_edges
            if e.family == family or e.other_family == family
        )


@lru_cache(maxsize=1)
def load_map() -> SubjectEvidenceMap:
    """Load and freeze the versioned map data beside this module."""
    with Path(__file__).with_name(MAP_FILE).open(encoding="utf-8") as fh:
        doc = json.load(fh)
    return SubjectEvidenceMap(
        version=str(doc["version"]),
        closure_policy=str(doc["closure_policy"]),
        families=tuple(doc["families"]),
        labelled_members={k: int(v) for k, v in doc["labelled_members"].items()},
        channels=tuple(
            ChannelSpec(
                channel=str(c["channel"]),
                weight=float(c["weight"]),
                presence_b=float(c["presence_b"]),
                presence_d=float(c["presence_d"]),
                correct_b=int(c["correct_b"]),
                wrong_b=int(c["wrong_b"]),
                correct_d=int(c["correct_d"]),
                wrong_d=int(c["wrong_d"]),
            )
            for c in doc["channels"]
        ),
        terms=tuple(
            TermSpec(
                family=str(t["family"]),
                channel=str(t["channel"]),
                term=str(t["term"]),
                support=int(t["support"]),
                support_b=int(t["support_b"]),
                support_d=int(t["support_d"]),
                share=float(t["share"]),
                confidence=float(t["confidence"]),
                source=str(t["source"]),
            )
            for t in doc["terms"]
        ),
        containment_edges=tuple(
            EdgeSpec(
                kind=str(e["kind"]),
                family=str(e["family"]),
                other_family=str(e["other_family"]),
                support=int(e["support"]),
                share=float(e["share"]),
                named=bool(e["named"]),
                basis=str(e["basis"]),
            )
            for e in doc["containment_edges"]
        ),
        edge_terms=tuple(
            EdgeTermSpec(
                edge=str(e["edge"]),
                term=str(e["term"]),
                support_debt=int(e["support_debt"]),
                support_lease=int(e["support_lease"]),
            )
            for e in doc["edge_terms"]
        ),
        inheritance=tuple(
            InheritanceSpec(
                family=str(r["family"]),
                members=int(r["members"]),
                title_decides_support=int(r["title_decides_support"]),
                title_decides_share=float(r["title_decides_share"]),
                stub_wrong_support=int(r["stub_wrong_support"]),
            )
            for r in doc["inheritance"]
        ),
        priced_absences=tuple(
            AbsenceSpec(
                family=str(a["family"]),
                labelled_members=int(a["labelled_members"]),
                reason=str(a["reason"]),
            )
            for a in doc["priced_absences"]
        ),
    )
