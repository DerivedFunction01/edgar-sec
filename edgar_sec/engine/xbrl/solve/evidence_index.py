"""Filing-local evidence records derived from one filing's bundle artefacts.

A record is a pure function of the bundle parquets plus the concept
table; absence of an entry or a signal is silence, never negative
evidence. No persisted artefact exists: records live in-process only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.normalize.lexicon import EvidenceContext
from edgar_sec.engine.xbrl.solve.cohort_scan import plan_cohort_scan
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry, ConceptTable
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.serialization import canonical_json

_QNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[A-Za-z_][A-Za-z0-9_.\-]*$")

_HORIZON_GROUP = "MATURITY_HORIZON"
_HORIZON_FALLBACK = frozenset({"M_CURRENT", "M_NONCURRENT"})

_BUNDLE_ARTEFACTS = (
    "facts.parquet",
    "presentation_arcs.parquet",
    "calculation_arcs.parquet",
    "declarations.parquet",
)

DeclarationTuple = tuple[str | None, str | None, str | None, str | None]
PresArc = tuple[str, str | None, float | None]
CalcArc = tuple[str, float, str | None]


def _require_qname(qname: object) -> str:
    """Return a well-formed qname; a malformed one is a build refusal."""
    if not isinstance(qname, str) or not _QNAME_RE.match(qname):
        raise ValueError(f"malformed qname in bundle artefact: {qname!r}")
    return qname


def _pres_key(arc: PresArc) -> tuple[str, str, float]:
    return (arc[0], arc[1] or "", arc[2] if arc[2] is not None else float("-inf"))


def _calc_key(arc: CalcArc) -> tuple[str, float, str]:
    return (arc[0], arc[1], arc[2] or "")


@dataclass(frozen=True, slots=True)
class ConceptEvidence:
    """One concept's filing-local evidence: raw blocks plus derived signals."""

    qname: str
    reported: bool = False
    reported_undimensioned: bool = False
    fact_count: int = 0
    period_types: tuple[str, ...] = ()
    declaration: DeclarationTuple | None = None
    pres_parents: tuple[PresArc, ...] = ()
    pres_children: tuple[PresArc, ...] = ()
    pres_roles: tuple[str, ...] = ()
    calc_parents: tuple[CalcArc, ...] = ()
    calc_children: tuple[CalcArc, ...] = ()
    placed: bool = False
    attested_placed: bool = False
    pres_horizon: str | None = None
    pres_horizon_ancestors: tuple[str, ...] = ()
    calc_horizon: str | None = None
    calc_horizon_ancestors: tuple[str, ...] = ()
    placement_horizon: str | None = None
    placement_horizon_source: str | None = None
    placement_conflict: bool = False
    calc_parent_heads: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible mapping for the equality oracle."""
        return {
            "qname": self.qname,
            "reported": self.reported,
            "reported_undimensioned": self.reported_undimensioned,
            "fact_count": self.fact_count,
            "period_types": list(self.period_types),
            "declaration": list(self.declaration) if self.declaration else None,
            "pres_parents": [list(arc) for arc in self.pres_parents],
            "pres_children": [list(arc) for arc in self.pres_children],
            "pres_roles": list(self.pres_roles),
            "calc_parents": [list(arc) for arc in self.calc_parents],
            "calc_children": [list(arc) for arc in self.calc_children],
            "placed": self.placed,
            "attested_placed": self.attested_placed,
            "pres_horizon": self.pres_horizon,
            "pres_horizon_ancestors": list(self.pres_horizon_ancestors),
            "calc_horizon": self.calc_horizon,
            "calc_horizon_ancestors": list(self.calc_horizon_ancestors),
            "placement_horizon": self.placement_horizon,
            "placement_horizon_source": self.placement_horizon_source,
            "placement_conflict": self.placement_conflict,
            "calc_parent_heads": list(self.calc_parent_heads),
        }


@dataclass(frozen=True, slots=True)
class FilingEvidenceRecord:
    """One filing's evidence record, keyed by its accession."""

    accession: str
    firm: str
    bundle_fingerprint: str
    concepts: Mapping[str, ConceptEvidence]

    @property
    def concept_count(self) -> int:
        """Count of per-concept entries in the record."""
        return len(self.concepts)

    def entry(self, qname: str) -> ConceptEvidence | None:
        """One concept's evidence, or None when the filing is silent on it."""
        return self.concepts.get(qname)

    def evidence_context(self, qname: str) -> EvidenceContext:
        """The decomposition context for one qname under this filing."""
        entry = self.concepts.get(qname)
        satisfied = entry is not None and entry.attested_placed
        return EvidenceContext(self.accession, qname, satisfied)

    def to_dict(self) -> dict:
        """Serialize header plus entries, qname-ordered, for canonical JSON."""
        return {
            "accession": self.accession,
            "firm": self.firm,
            "bundle_fingerprint": self.bundle_fingerprint,
            "concept_count": self.concept_count,
            "concepts": {
                qname: self.concepts[qname].to_dict() for qname in sorted(self.concepts)
            },
        }

    def canonical(self) -> str:
        """The record's canonical-JSON serialization: its equality oracle."""
        return canonical_json(self.to_dict())


class EvidenceIndex:
    """Per-process evidence records keyed by accession."""

    def __init__(self, records: Mapping[str, FilingEvidenceRecord]) -> None:
        """Bind the built records; absence of an accession is silence."""
        self._records = dict(records)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, accession: str) -> bool:
        return accession in self._records

    @property
    def records(self) -> Mapping[str, FilingEvidenceRecord]:
        """All filing records, keyed by accession."""
        return self._records

    def record(self, accession: str) -> FilingEvidenceRecord | None:
        """One filing's record, or None when the filing is not indexed."""
        return self._records.get(accession)

    def entry(self, accession: str, qname: str) -> ConceptEvidence | None:
        """One (accession, qname) evidence entry, or None when silent."""
        record = self._records.get(accession)
        return record.entry(qname) if record is not None else None

    def evidence_context(self, accession: str, qname: str) -> EvidenceContext:
        """The decomposition context keyed by exactly (accession, qname)."""
        record = self._records.get(accession)
        if record is None:
            return EvidenceContext(accession, qname, False)
        return record.evidence_context(qname)


def _read_rows(path: Path, columns: list[str]) -> list[dict]:
    """Rows of an optional bundle parquet; a missing artefact reads empty."""
    if not path.is_file():
        return []
    return pq.read_table(path, columns=columns).to_pylist()


def _horizon_members(table: ConceptTable) -> frozenset[str]:
    """The MATURITY_HORIZON axis members declared by the taxonomy."""
    for group in table.taxonomy.sibling_groups:
        if group.group == _HORIZON_GROUP:
            return frozenset(group.members)
    return _HORIZON_FALLBACK


def _walk_horizon(
    start: str,
    parents: Mapping[str, tuple[tuple[str, str | None], ...]],
    table: ConceptTable,
    members: frozenset[str],
) -> tuple[str | None, tuple[str, ...], bool]:
    """Nearest-depth horizon over same-role ancestor edges, cycle-guarded.

    Returns (modifier, deciding ancestors, conflict). Dual-horizon
    ancestors state the whole, not a portion: no signal, walk past them.
    """
    frontier = [(parent, role) for parent, role in parents.get(start, ())]
    visited = {(start, None)}
    while frontier:
        stating: dict[str, str] = {}
        following: list[tuple[str, str | None]] = []
        for qname, role in frontier:
            if qname == start or (qname, role) in visited:
                continue
            visited.add((qname, role))
            following.extend(
                (parent, role)
                for parent, parent_role in parents.get(qname, ())
                if parent_role == role
            )
            if qname not in table:
                continue
            stated = table.record(qname).atom.modifiers & members
            if len(stated) == 1:
                stating[qname] = next(iter(stated))
        if stating:
            values = set(stating.values())
            if len(values) > 1:
                return None, (), True
            return next(iter(values)), tuple(sorted(stating)), False
        frontier = following
    return None, (), False


def _derive_horizons(
    concepts: dict[str, ConceptEvidence], table: ConceptTable
) -> dict[str, ConceptEvidence]:
    """Fill the §2.3 horizon fields from the raw blocks plus table atoms."""
    members = _horizon_members(table)
    pres_up = {
        qname: tuple((arc[0], arc[1]) for arc in entry.pres_parents)
        for qname, entry in concepts.items()
    }
    calc_up = {
        qname: tuple((arc[0], arc[2]) for arc in entry.calc_parents)
        for qname, entry in concepts.items()
    }
    derived: dict[str, ConceptEvidence] = {}
    for qname, entry in concepts.items():
        pres, pres_ancestors, pres_conflict = _walk_horizon(
            qname, pres_up, table, members
        )
        calc, calc_ancestors, calc_conflict = _walk_horizon(
            qname, calc_up, table, members
        )
        conflict = pres_conflict or calc_conflict
        horizon: str | None = None
        source: str | None = None
        if pres is not None and calc is not None:
            if pres == calc:
                horizon, source = pres, "both"
            else:
                conflict = True
        elif pres is not None:
            horizon, source = pres, "presentation"
        elif calc is not None:
            horizon, source = calc, "calculation"
        derived[qname] = replace(
            entry,
            pres_horizon=pres,
            pres_horizon_ancestors=pres_ancestors,
            calc_horizon=calc,
            calc_horizon_ancestors=calc_ancestors,
            placement_horizon=horizon,
            placement_horizon_source=source,
            placement_conflict=conflict,
        )
    return derived


def _bundle_fingerprint(bundle_dir: Path) -> str:
    """Digest over the sorted (filename, digest) pairs of the source parquets."""
    pairs = []
    for name in sorted(_BUNDLE_ARTEFACTS):
        path = bundle_dir / name
        pairs.append([name, file_sha256(path) if path.is_file() else None])
    return sha256_text(canonical_json(pairs))


class _Accumulator:
    """Mutable per-concept build state, frozen into ConceptEvidence at the end."""

    def __init__(self) -> None:
        self.fact_count = 0
        self.undimensioned = False
        self.period_types: set[str] = set()
        self.declaration: DeclarationTuple | None = None
        self.pres_parents: list[PresArc] = []
        self.pres_children: list[PresArc] = []
        self.calc_parents: list[CalcArc] = []
        self.calc_children: list[CalcArc] = []


def build_filing_evidence(
    entry: CohortEntry, table: ConceptTable
) -> FilingEvidenceRecord:
    """Derive one filing's evidence record from its bundle parquets.

    Refuses a bundle whose facts accession disagrees with the entry,
    or any malformed fact qname or arc endpoint.
    """
    bundle_dir = entry.facts_path.parent
    acc: dict[str, _Accumulator] = {}

    def slot(qname: str) -> _Accumulator:
        return acc.setdefault(qname, _Accumulator())

    fact_rows = _read_rows(
        entry.facts_path,
        ["accession", "concept_qname", "dimensions_json", "period_type"],
    )
    accessions = {str(row["accession"]) for row in fact_rows}
    if accessions != {entry.accession}:
        raise ValueError(
            f"bundle facts accession {sorted(accessions)} disagrees with "
            f"cohort entry {entry.accession}"
        )
    for row in fact_rows:
        qname = _require_qname(row["concept_qname"])
        state = slot(qname)
        state.fact_count += 1
        if json.loads(row["dimensions_json"]) == {}:
            state.undimensioned = True
        state.period_types.add(str(row["period_type"]))

    for row in _read_rows(
        bundle_dir / "presentation_arcs.parquet",
        ["parent_qname", "child_qname", "order", "role_uri"],
    ):
        parent = _require_qname(row["parent_qname"])
        child = _require_qname(row["child_qname"])
        order = float(row["order"]) if row["order"] is not None else None
        role = str(row["role_uri"]) if row["role_uri"] is not None else None
        slot(child).pres_parents.append((parent, role, order))
        slot(parent).pres_children.append((child, role, order))

    for row in _read_rows(
        bundle_dir / "calculation_arcs.parquet",
        ["parent_qname", "child_qname", "weight", "order", "role_uri"],
    ):
        parent = _require_qname(row["parent_qname"])
        child = _require_qname(row["child_qname"])
        weight = float(row["weight"])
        role = str(row["role_uri"]) if row["role_uri"] is not None else None
        slot(child).calc_parents.append((parent, weight, role))
        slot(parent).calc_children.append((child, weight, role))

    for row in _read_rows(
        bundle_dir / "declarations.parquet",
        ["concept_qname", "item_type", "balance", "period_type", "substitution_group"],
    ):
        qname = _require_qname(row["concept_qname"])
        slot(qname).declaration = (
            row["item_type"],
            row["balance"],
            row["period_type"],
            row["substitution_group"],
        )

    concepts: dict[str, ConceptEvidence] = {}
    for qname in sorted(acc):
        state = acc[qname]
        pres_parents = tuple(sorted(state.pres_parents, key=_pres_key))
        pres_children = tuple(sorted(state.pres_children, key=_pres_key))
        calc_parents = tuple(sorted(state.calc_parents, key=_calc_key))
        calc_children = tuple(sorted(state.calc_children, key=_calc_key))
        roles = sorted(
            {arc[1] for arc in pres_parents + pres_children if arc[1] is not None}
        )
        placed = bool(pres_parents or pres_children or calc_parents or calc_children)
        heads = sorted(
            {table.record(arc[0]).atom.head for arc in calc_parents if arc[0] in table}
        )
        concepts[qname] = ConceptEvidence(
            qname=qname,
            reported=state.fact_count > 0,
            reported_undimensioned=state.undimensioned,
            fact_count=state.fact_count,
            period_types=tuple(sorted(state.period_types)),
            declaration=state.declaration,
            pres_parents=pres_parents,
            pres_children=pres_children,
            pres_roles=tuple(roles),
            calc_parents=calc_parents,
            calc_children=calc_children,
            placed=placed,
            attested_placed=state.fact_count > 0 and placed,
            calc_parent_heads=tuple(heads),
        )
    return FilingEvidenceRecord(
        accession=entry.accession,
        firm=entry.firm,
        bundle_fingerprint=_bundle_fingerprint(bundle_dir),
        concepts=MappingProxyType(_derive_horizons(concepts, table)),
    )


def build_evidence_index(
    entries: Sequence[CohortEntry], table: ConceptTable
) -> EvidenceIndex:
    """Build the index for a cohort, in the cohort scan's batch discipline."""
    records: dict[str, FilingEvidenceRecord] = {}
    if not entries:
        return EvidenceIndex(records)
    step = plan_cohort_scan(entries).batch_cardinality
    for start in range(0, len(entries), step):
        for entry in entries[start : start + step]:
            records[entry.accession] = build_filing_evidence(entry, table)
        reclaim()
    return EvidenceIndex(records)


__all__ = [
    "CalcArc",
    "ConceptEvidence",
    "DeclarationTuple",
    "EvidenceIndex",
    "FilingEvidenceRecord",
    "PresArc",
    "build_evidence_index",
    "build_filing_evidence",
]
