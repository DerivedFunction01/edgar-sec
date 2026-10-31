"""Cross-firm equivalence lookup over cohort bundle facts, DuckDB-direct.

Candidate generation classifies against the concept table's atoms; fact
retrieval joins bundle facts.parquet at query time. Compatibility is
checked before ranking: incompatible facts return flagged, never dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry, ConceptTable
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    UNRELATED,
    LadderClassification,
    classify_ladder_pair,
)
from edgar_sec.engine.xbrl.solve.evidence_index import (
    EvidenceIndex,
    build_evidence_index,
)
from edgar_sec.infra.storage.duckdb import connect, sql_path_list

_ANNUAL_SPAN_DAYS = 300

_FACT_COLUMNS = (
    "accession, concept_qname, numeric_value, unit, period_type, "
    "start_date, end_date, instant_date"
)


@dataclass(frozen=True, slots=True)
class CohortCandidate:
    """One (filing, concept) pair classified against the target atom."""

    accession: str
    firm: str
    qname: str
    atom: Atom
    tier: str
    rule: str
    direction: str
    via_default: bool
    modifier_distance: int
    residual_intent: int
    residual_total: int
    via_filing_local: bool = False


@dataclass(frozen=True, slots=True)
class CohortFact:
    """One candidate fact's lookup payload: value, unit, and period.

    Decimals, dimensions, and context stay in the bundle; the
    per-filing path serves them for a filing a consumer opens.
    """

    accession: str
    qname: str
    value: float | None
    unit: str | None
    period_type: str
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None


@dataclass(frozen=True, slots=True)
class CohortFactMatch:
    """One candidate fact with its compatibility verdict against the source."""

    accession: str
    firm: str
    qname: str
    atom: Atom
    tier: str
    rule: str
    direction: str
    via_default: bool
    fact: CohortFact
    compatible: bool
    incompatibility: str = ""
    via_filing_local: bool = False


def _row_to_fact(row: Sequence[object]) -> CohortFact:
    """One facts.parquet row (in _FACT_COLUMNS order) as a CohortFact."""
    return CohortFact(
        accession=str(row[0]),
        qname=str(row[1]),
        value=float(row[2]) if row[2] is not None else None,
        unit=str(row[3]) if row[3] is not None else None,
        period_type=str(row[4]),
        start_date=str(row[5]) if row[5] is not None else None,
        end_date=str(row[6]) if row[6] is not None else None,
        instant_date=str(row[7]) if row[7] is not None else None,
    )


def _fiscal_key(fact: XbrlFact | CohortFact) -> tuple[int, bool] | None:
    """Fiscal alignment key: period year, and annual span for durations."""
    if fact.period_type == "instant":
        if not fact.instant_date:
            return None
        return int(fact.instant_date[:4]), True
    if not fact.end_date:
        return None
    annual = True
    if fact.start_date:
        span = (
            date.fromisoformat(fact.end_date) - date.fromisoformat(fact.start_date)
        ).days
        annual = span >= _ANNUAL_SPAN_DAYS
    return int(fact.end_date[:4]), annual


class CohortLookup:
    """Equivalence queries over a fixed cohort, served from the concept table."""

    def __init__(
        self,
        table: ConceptTable,
        entries: Sequence[CohortEntry],
    ) -> None:
        """Bind the concept table, the cohort entries, and their evidence index."""
        self._table = table
        self._entries = tuple(entries)
        self._firms = {entry.accession: entry.firm for entry in self._entries}
        self._paths = sql_path_list([str(entry.facts_path) for entry in self._entries])
        self._evidence = build_evidence_index(self._entries, table)
        self._con = None
        self._unit_classes: dict[str | None, str] = {}

    @property
    def evidence(self) -> EvidenceIndex:
        """The filing-local evidence index built for this lookup's cohort."""
        return self._evidence

    def close(self) -> None:
        """Close the lookup's DuckDB connection, if opened."""
        if self._con is not None:
            self._con.close()
            self._con = None

    def _connection(self):
        """The lookup's shared DuckDB connection, opened on first use."""
        if self._con is None:
            self._con = connect()
        return self._con

    def _target(self, target: str | Atom) -> tuple[str, Atom]:
        """Resolve a query target to its qname (empty for atom targets) and atom."""
        if isinstance(target, str):
            return target, self._table.tokenize(target).atom
        return "", target

    def _derived(self, qname: str) -> str | None:
        """A qname's derived horizon from the concept table, if it has one."""
        if qname and qname in self._table:
            return self._table.record(qname).derived_horizon
        return None

    def _placement(self, accession: str | None, qname: str) -> str | None:
        """A qname's placement horizon under one filing's record, if it speaks."""
        if accession is None or not qname:
            return None
        entry = self._evidence.entry(accession, qname)
        return entry.placement_horizon if entry is not None else None

    def _classify(
        self,
        target_qname: str,
        target_atom: Atom,
        candidate_qname: str,
        *,
        accession: str | None = None,
        target_accession: str | None = None,
    ) -> LadderClassification:
        """Classify one (accession, candidate) row under the full ladder.

        The candidate is presumed under its own filing's record; the
        target only under the query's accession, never a candidate's.
        """
        taxonomy = self._table.taxonomy
        return classify_ladder_pair(
            target_atom,
            self._table.record(candidate_qname).atom,
            taxonomy.default_coordinates,
            tuple(taxonomy.sibling_groups) or None,
            target_derived_horizon=self._derived(target_qname),
            candidate_derived_horizon=self._derived(candidate_qname),
            target_placement_horizon=self._placement(target_accession, target_qname),
            candidate_placement_horizon=self._placement(accession, candidate_qname),
            same_qname=bool(target_qname) and target_qname == candidate_qname,
        )

    def _pool(self, target_qname: str, target_atom: Atom) -> tuple[str, ...]:
        """Qnames any row of which could classify non-UNRELATED to the target.

        Checked over stated, derived, default, and both placement
        variants, so a filing-local NEAR survives the pool cut.
        """
        taxonomy = self._table.taxonomy
        groups = tuple(taxonomy.sibling_groups) or None
        defaults = taxonomy.default_coordinates
        target_derived = self._derived(target_qname)
        members = ("M_CURRENT", "M_NONCURRENT")
        pool = []
        for qname, record in self._table.records.items():
            variants: list[LadderClassification] = [
                classify_ladder_pair(
                    target_atom,
                    record.atom,
                    defaults,
                    groups,
                    target_derived_horizon=target_derived,
                    candidate_derived_horizon=record.derived_horizon,
                    same_qname=bool(target_qname) and target_qname == qname,
                )
            ]
            if record.derived_horizon is None and not (
                record.atom.modifiers & frozenset(members)
            ):
                variants += [
                    classify_ladder_pair(
                        target_atom,
                        record.atom,
                        defaults,
                        groups,
                        target_derived_horizon=target_derived,
                        candidate_placement_horizon=horizon,
                    )
                    for horizon in members
                ]
                variants += [
                    classify_ladder_pair(
                        target_atom,
                        record.atom,
                        defaults,
                        groups,
                        target_placement_horizon=horizon,
                        candidate_derived_horizon=record.derived_horizon,
                    )
                    for horizon in members
                ]
            if any(item.tier != UNRELATED for item in variants):
                pool.append(qname)
        return tuple(sorted(pool))

    @staticmethod
    def _rank_key(
        result: LadderClassification, qname: str, residual: tuple[int, int]
    ) -> tuple:
        """Sort key mirroring the ladder order: tier, rung, distance, residuals."""
        return (
            0 if result.tier == EXACT else 1,
            2 if result.via_default else 1 if result.via_filing_local else 0,
            result.modifier_distance,
            residual[0],
            residual[1],
            qname,
        )

    def equivalents(
        self,
        target: str | Atom,
        *,
        accession: str | None = None,
    ) -> tuple[CohortCandidate, ...]:
        """Ranked (filing, concept) candidate pairs for a target, cohort-wide.

        A per-accession filter on the same query serves per-filing
        classification consumers.
        """
        target_qname, target_atom = self._target(target)
        pool = self._pool(target_qname, target_atom)
        if not pool or not self._entries:
            return ()
        query = (
            "SELECT DISTINCT accession, concept_qname FROM read_parquet("
            f"{self._paths}) WHERE concept_qname = ANY(?)"
        )
        params: list[object] = [list(pool)]
        if accession is not None:
            query += " AND accession = ?"
            params.append(accession)
        rows = self._connection().execute(query, params).fetchall()
        candidates = []
        for row in rows:
            row_accession, qname = str(row[0]), str(row[1])
            result = self._classify(
                target_qname,
                target_atom,
                qname,
                accession=row_accession,
                target_accession=accession,
            )
            if result.tier == UNRELATED:
                continue
            intent, total = self._table.residual_counts[qname]
            candidates.append(
                (
                    self._rank_key(result, qname, (intent, total)),
                    row_accession,
                    CohortCandidate(
                        accession=row_accession,
                        firm=self._firms.get(row_accession, ""),
                        qname=qname,
                        atom=self._table.record(qname).atom,
                        tier=result.tier,
                        rule=result.rule,
                        direction=result.direction,
                        via_default=result.via_default,
                        modifier_distance=result.modifier_distance,
                        residual_intent=intent,
                        residual_total=total,
                        via_filing_local=result.via_filing_local,
                    ),
                )
            )
        candidates.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in candidates)

    def _unit_class(self, unit: str | None) -> str:
        """Memoized taxonomy unit class for a raw unit token."""
        if unit not in self._unit_classes:
            self._unit_classes[unit] = self._table.taxonomy.normalize_unit(unit)
        return self._unit_classes[unit]

    def _incompatibility(self, source: XbrlFact, fact: CohortFact) -> str:
        """Name the first compatibility failure, or empty when compatible.

        Unit class first, then period kind, then fiscal alignment — the
        order a reader adjudicates a candidate by.
        """
        if self._unit_class(fact.unit) != self._unit_class(source.unit):
            return "unit"
        if fact.period_type != source.period_type:
            return "period_kind"
        source_key = _fiscal_key(source)
        if source_key is not None and _fiscal_key(fact) != source_key:
            return "fiscal_period"
        return ""

    def equivalent_facts(
        self,
        source: XbrlFact,
        *,
        accession: str | None = None,
    ) -> tuple[CohortFactMatch, ...]:
        """Candidate facts for the source fact's concept across the cohort.

        Compatible matches present first in rank order; incompatible
        facts follow, flagged, in the same rank order.
        """
        target_qname, target_atom = self._target(source.concept_qname)
        pool = self._pool(target_qname, target_atom)
        if not pool or not self._entries:
            return ()
        query = (
            f"SELECT {_FACT_COLUMNS} FROM read_parquet({self._paths}) "
            "WHERE concept_qname = ANY(?)"
        )
        params: list[object] = [list(pool)]
        if accession is not None:
            query += " AND accession = ?"
            params.append(accession)
        rows = self._connection().execute(query, params).fetchall()
        classified: dict[tuple[str, str], LadderClassification] = {}
        matches = []
        for row in rows:
            fact = _row_to_fact(row)
            reason = self._incompatibility(source, fact)
            key = (fact.accession, fact.qname)
            if key not in classified:
                classified[key] = self._classify(
                    target_qname,
                    target_atom,
                    fact.qname,
                    accession=fact.accession,
                    target_accession=accession,
                )
            item = classified[key]
            if item.tier == UNRELATED:
                continue
            matches.append(
                CohortFactMatch(
                    accession=fact.accession,
                    firm=self._firms.get(fact.accession, ""),
                    qname=fact.qname,
                    atom=self._table.record(fact.qname).atom,
                    tier=item.tier,
                    rule=item.rule,
                    direction=item.direction,
                    via_default=item.via_default,
                    fact=fact,
                    compatible=not reason,
                    incompatibility=reason,
                    via_filing_local=item.via_filing_local,
                )
            )

        def rank_key(item: CohortFactMatch) -> tuple:
            result = classified[(item.accession, item.qname)]
            residual = self._table.residual_counts[item.qname]
            return self._rank_key(result, item.qname, residual)

        matches.sort(
            key=lambda item: item.fact.instant_date or item.fact.end_date or "",
            reverse=True,
        )
        matches.sort(
            key=lambda item: (
                0 if item.compatible else 1,
                rank_key(item),
                item.accession,
            )
        )
        return tuple(matches)


__all__ = ["CohortCandidate", "CohortFact", "CohortFactMatch", "CohortLookup"]
