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
    NEAR,
    UNRELATED,
    RankedEquivalent,
    classify_pair,
    presumed_atom,
    rank_equivalents,
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
        """Bind the concept table and the cohort's bundle entries."""
        self._table = table
        self._entries = tuple(entries)
        self._firms = {entry.accession: entry.firm for entry in self._entries}
        self._paths = sql_path_list([str(entry.facts_path) for entry in self._entries])
        self._con = None
        self._unit_classes: dict[str | None, str] = {}

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

    def _ranked(self, target: str | Atom) -> tuple[RankedEquivalent, ...]:
        """Rank the table's concepts against a qname or atom target.

        A classify pass over the distinct atoms selects the pool; the
        target qname stays empty so the concept itself can rank exact.
        """
        if isinstance(target, str):
            target_atom = self._table.tokenize(target).atom
        else:
            target_atom = target
        target_qname = ""
        taxonomy = self._table.taxonomy
        groups = tuple(taxonomy.sibling_groups) or None
        defaults = taxonomy.default_coordinates
        presumed_target = presumed_atom(target_atom, defaults, groups)
        pool: list[tuple[str, Atom]] = []
        for atom, qnames in self._table.qnames_by_atom.items():
            if classify_pair(target_atom, atom) != UNRELATED:
                pool.extend((qname, atom) for qname in qnames)
            elif defaults and (
                classify_pair(presumed_target, presumed_atom(atom, defaults, groups))
                == NEAR
            ):
                pool.extend((qname, atom) for qname in qnames)
        return rank_equivalents(
            target_qname,
            target_atom,
            pool,
            defaults,
            sibling_groups=groups,
            residual_counts=self._table.residual_counts,
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
        ranked = self._ranked(target)
        if not ranked or not self._entries:
            return ()
        by_qname = {item.qname: item for item in ranked}
        query = (
            "SELECT DISTINCT accession, concept_qname FROM read_parquet("
            f"{self._paths}) WHERE concept_qname = ANY(?)"
        )
        params: list[object] = [list(by_qname)]
        if accession is not None:
            query += " AND accession = ?"
            params.append(accession)
        rows = self._connection().execute(query, params).fetchall()
        order = {item.qname: index for index, item in enumerate(ranked)}
        candidates = [
            CohortCandidate(
                accession=str(row[0]),
                firm=self._firms.get(str(row[0]), ""),
                qname=str(row[1]),
                atom=by_qname[str(row[1])].atom,
                tier=by_qname[str(row[1])].tier,
                rule=by_qname[str(row[1])].rule,
                direction=by_qname[str(row[1])].direction,
                via_default=by_qname[str(row[1])].via_default,
                modifier_distance=by_qname[str(row[1])].modifier_distance,
                residual_intent=by_qname[str(row[1])].residual_intent_count,
                residual_total=by_qname[str(row[1])].residual_total_count,
            )
            for row in rows
        ]
        candidates.sort(key=lambda item: (order[item.qname], item.accession))
        return tuple(candidates)

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
        ranked = self._ranked(source.concept_qname)
        if not ranked or not self._entries:
            return ()
        by_qname = {item.qname: item for item in ranked}
        order = {item.qname: index for index, item in enumerate(ranked)}
        query = (
            f"SELECT {_FACT_COLUMNS} FROM read_parquet({self._paths}) "
            "WHERE concept_qname = ANY(?)"
        )
        params: list[object] = [list(by_qname)]
        if accession is not None:
            query += " AND accession = ?"
            params.append(accession)
        rows = self._connection().execute(query, params).fetchall()
        matches = []
        for row in rows:
            fact = _row_to_fact(row)
            reason = self._incompatibility(source, fact)
            item = by_qname[fact.qname]
            matches.append(
                CohortFactMatch(
                    accession=fact.accession,
                    firm=self._firms.get(fact.accession, ""),
                    qname=fact.qname,
                    atom=item.atom,
                    tier=item.tier,
                    rule=item.rule,
                    direction=item.direction,
                    via_default=item.via_default,
                    fact=fact,
                    compatible=not reason,
                    incompatibility=reason,
                )
            )
        matches.sort(
            key=lambda item: item.fact.instant_date or item.fact.end_date or "",
            reverse=True,
        )
        matches.sort(
            key=lambda item: (
                0 if item.compatible else 1,
                order[item.qname],
                item.accession,
            )
        )
        return tuple(matches)


__all__ = ["CohortCandidate", "CohortFact", "CohortFactMatch", "CohortLookup"]
