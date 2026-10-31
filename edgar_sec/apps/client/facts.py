"""Fluent querying and tabular serialization of XBRL instance facts."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.normalize.decomposer import residual_counts
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.concept_table import ConceptRecord, ConceptTable
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortFact, CohortFactMatch
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer, TokenizedFact
from edgar_sec.engine.xbrl.taxonomy.archive import CURRENT_SLICES, load_slice
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.resolution import compile_virtual_views
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.pipelines.xbrl_review.paths import xbrl_paths
from edgar_sec.pipelines.xbrl_review.snapshot.specs import XBRL_RELATIONS


@dataclass(frozen=True, slots=True)
class DisplayRecord:
    """One concept's tokenized record as carried by a display fact set.

    Lookup-sourced records also carry the equivalence tier and rule
    that produced the set; directly loaded records leave them empty.
    """

    qname: str
    atom: Atom
    presumed_atom: Atom
    residuals: tuple[str, ...] = ()
    derived_horizon: str | None = None
    item_type: str | None = None
    tier: str = ""
    rule: str = ""

    @property
    def presumed_signature(self) -> str:
        """Canonical signature of the presumed atom."""
        return canonical_json(self.presumed_atom.to_dict())

    @property
    def residual_mass(self) -> tuple[int, int]:
        """(intent, total) residual mass of the stated decomposition."""
        return residual_counts(self.residuals)

    @classmethod
    def from_tokenized(
        cls, record: TokenizedFact, item_type: str | None = None
    ) -> DisplayRecord:
        """Carry a tokenizer record, plus the declared item type when known."""
        return cls(
            qname=record.qname,
            atom=record.atom,
            presumed_atom=record.presumed_atom,
            residuals=record.residuals,
            derived_horizon=record.derived_horizon,
            item_type=item_type,
        )


def display_record_from_table(
    record: ConceptRecord, *, tier: str = "", rule: str = ""
) -> DisplayRecord:
    """Carry a concept-table record as a display record."""
    return DisplayRecord(
        qname=record.qname,
        atom=record.atom,
        presumed_atom=record.presumed_atom,
        residuals=record.residuals,
        derived_horizon=record.derived_horizon,
        item_type=record.item_type,
        tier=tier,
        rule=rule,
    )


def _table_records(
    qnames: Sequence[str],
    table: ConceptTable,
    tiers: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, DisplayRecord]:
    records: dict[str, DisplayRecord] = {}
    for qname in qnames:
        tier, rule = (tiers or {}).get(qname, ("", ""))
        if qname in table:
            records[qname] = display_record_from_table(
                table.record(qname), tier=tier, rule=rule
            )
        else:
            declaration = table.declaration(qname)
            records[qname] = DisplayRecord.from_tokenized(
                table.tokenize(qname),
                declaration.item_type if declaration is not None else None,
            )
    return records


def facts_from_arrow_table(table: pa.Table) -> tuple[XbrlFact, ...]:
    """Full-fidelity XbrlFact tuples from a bundle facts.parquet table."""
    return tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=(
                row["numeric_value"]
                if row["numeric_value"] is not None
                else row["text_value"]
            ),
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in table.to_pylist()
    )


def build_fact_set_from_table(
    facts: Sequence[XbrlFact], table: ConceptTable
) -> XbrlFactSet:
    """Fact set whose records come from the Phase 3 concept table."""
    records = _table_records(sorted({f.concept_qname for f in facts}), table)
    return XbrlFactSet(facts, table.taxonomy, records=records)


def fact_from_cohort_fact(fact: CohortFact) -> XbrlFact:
    """Project a lookup payload fact to a display fact (no dimensions)."""
    return XbrlFact(
        accession=AccessionNumber.from_any(fact.accession),
        concept_qname=fact.qname,
        value=fact.value,
        unit=fact.unit,
        period_type=fact.period_type,
        start_date=fact.start_date,
        end_date=fact.end_date,
        instant_date=fact.instant_date,
    )


def build_fact_set_from_lookup(
    matches: Sequence[CohortFactMatch], table: ConceptTable
) -> XbrlFactSet:
    """Fact set from equivalence-lookup matches; records carry tier/rule."""
    facts = tuple(fact_from_cohort_fact(match.fact) for match in matches)
    tiers: dict[str, tuple[str, str]] = {}
    for match in matches:
        tiers.setdefault(match.qname, (match.tier, match.rule))
    records = _table_records(sorted({f.concept_qname for f in facts}), table, tiers)
    return XbrlFactSet(facts, table.taxonomy, records=records)


_NODE_COLUMNS = (
    "accession",
    "concept_qname",
    "period",
    "cik",
    "prime_head",
    "modifiers_json",
    "reported_value",
    "derived_value",
)


def snapshot_rows(
    artifacts_root: Path | str, snapshot_id: str, accession: str
) -> tuple[
    list[dict[str, Any]], tuple[CalculationArc, ...], tuple[PresentationArc, ...]
]:
    """One accession's solved nodes and arcs, merged over the snapshot lineage."""
    paths = xbrl_paths(artifacts_root)
    if not DAGCatalog(paths.snapshots_root).has_snapshot(snapshot_id):
        raise ValueError(
            f"snapshot {snapshot_id} not found under {paths.snapshots_root}"
        )
    lineage = walk_lineage(paths.snapshots_root, snapshot_id)
    with connect() as con:
        views = compile_virtual_views(
            con, XBRL_RELATIONS, lineage, paths.snapshots_root
        )
        node_view = sql_identifier(views["solved_nodes"])
        node_rows = con.execute(
            f"SELECT accession, concept_qname, period, cik, prime_head, "
            f"modifiers_json, reported_value, derived_value FROM {node_view} "
            "WHERE accession = ? ORDER BY concept_qname, period",
            [accession],
        ).fetchall()
        calc_view = sql_identifier(views["calculation_arcs"])
        calc_rows = con.execute(
            f'SELECT parent_qname, child_qname, weight, "order", role_uri '
            f"FROM {calc_view} WHERE accession = ? ORDER BY parent_qname, child_qname",
            [accession],
        ).fetchall()
        pres_view = sql_identifier(views["presentation_arcs"])
        pres_rows = con.execute(
            f'SELECT parent_qname, child_qname, "order", role_uri '
            f"FROM {pres_view} WHERE accession = ? ORDER BY parent_qname, child_qname",
            [accession],
        ).fetchall()
    nodes = [dict(zip(_NODE_COLUMNS, row, strict=True)) for row in node_rows]
    calc = tuple(
        CalculationArc(
            parent_qname=row[0],
            child_qname=row[1],
            weight=row[2],
            order=row[3],
            role_uri=row[4],
        )
        for row in calc_rows
    )
    pres = tuple(
        PresentationArc(
            parent_qname=row[0], child_qname=row[1], order=row[2], role_uri=row[3]
        )
        for row in pres_rows
    )
    return nodes, calc, pres


def _snapshot_period_fields(
    period: str, period_type: str | None
) -> tuple[str, str | None, str | None, str | None]:
    """Rebuild fact period fields from a solved node's single period label."""
    if "/" in period:
        start, _, end = period.partition("/")
        return "duration", start or None, end or None, None
    if period_type == "duration":
        return "duration", None, period or None, None
    return "instant", None, None, period or None


def build_fact_set_from_snapshot(
    rows: Sequence[Mapping[str, Any]],
    taxonomy: DomainTaxonomy,
    table: ConceptTable | None = None,
) -> XbrlFactSet:
    """Fact set from snapshot solved nodes; a projection with no unit or dimensions.

    Records come from the concept table when given, else from each
    node's snapshot atom, whose presumed atom is the atom itself.
    """
    archive: dict[str, ConceptDeclaration] | None = None
    if table is None:
        archive = {
            declaration.concept_qname: declaration
            for taxonomy_name, version in CURRENT_SLICES
            for declaration in load_slice(taxonomy_name, version)
        }
    declarations: dict[str, ConceptDeclaration | None] = {}
    for row in rows:
        qname = row["concept_qname"]
        if qname not in declarations:
            declarations[qname] = (
                table.declaration(qname)
                if table is not None
                else (archive or {}).get(qname)
            )
    facts: list[XbrlFact] = []
    for row in rows:
        qname = row["concept_qname"]
        declaration = declarations[qname]
        period_type, start, end, instant = _snapshot_period_fields(
            row["period"] or "",
            declaration.period_type if declaration is not None else None,
        )
        facts.append(
            XbrlFact(
                accession=AccessionNumber.from_any(row["accession"]),
                concept_qname=qname,
                value=(
                    row["reported_value"]
                    if row["reported_value"] is not None
                    else row["derived_value"]
                ),
                period_type=period_type,
                start_date=start,
                end_date=end,
                instant_date=instant,
            )
        )
    if table is not None:
        records = _table_records(sorted({f.concept_qname for f in facts}), table)
    else:
        records = {}
        for row in rows:
            qname = row["concept_qname"]
            if qname in records:
                continue
            atom = Atom(row["prime_head"], frozenset(json.loads(row["modifiers_json"])))
            declaration = declarations[qname]
            records[qname] = DisplayRecord(
                qname=qname,
                atom=atom,
                presumed_atom=atom,
                item_type=declaration.item_type if declaration is not None else None,
            )
    return XbrlFactSet(facts, taxonomy, records=records)


def build_display_records(
    facts: Sequence[XbrlFact],
    taxonomy: DomainTaxonomy,
    declarations: Mapping[str, ConceptDeclaration] | None = None,
) -> dict[str, DisplayRecord]:
    """Tokenize each distinct concept once through the tokenizer service."""
    if taxonomy.token_lexicon is None:
        return {}
    tokenizer = ConceptTokenizer(taxonomy)
    records: dict[str, DisplayRecord] = {}
    for qname in sorted({fact.concept_qname for fact in facts}):
        declaration = declarations.get(qname) if declarations else None
        tokenized = tokenizer.tokenize(qname, declaration)
        item_type = declaration.item_type if declaration is not None else None
        records[qname] = DisplayRecord.from_tokenized(tokenized, item_type)
    return records


class XbrlFactQueryBuilder:
    """Fluent query builder for filtering and resolving XBRL facts."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        taxonomy: DomainTaxonomy,
        records: Mapping[str, DisplayRecord] | None = None,
    ) -> None:
        self._facts = list(facts)
        self._taxonomy = taxonomy
        self._records = records

    def _display_records(self) -> Mapping[str, DisplayRecord]:
        if self._records is None:
            self._records = build_display_records(self._facts, self._taxonomy)
        return self._records

    def concept(self, pattern: str) -> XbrlFactQueryBuilder:
        """Filter facts whose concept QName contains the given substring."""
        self._facts = [f for f in self._facts if pattern in f.concept_qname]
        return self

    def atom(
        self,
        head: str,
        modifiers: Sequence[str] = (),
        excluded_modifiers: Sequence[str] = (),
    ) -> XbrlFactQueryBuilder:
        """Filter facts matching specific subatomic head and modifier coordinates."""
        if self._taxonomy.token_lexicon is None:
            return self
        records = self._display_records()
        required_mods = set(modifiers)
        banned_mods = set(excluded_modifiers)
        filtered: list[XbrlFact] = []
        for f in self._facts:
            record = records.get(f.concept_qname)
            if record is None:
                continue
            a = record.atom
            if a.head == head and required_mods.issubset(a.modifiers):
                if not banned_mods or not (banned_mods & a.modifiers):
                    filtered.append(f)
        self._facts = filtered
        return self

    def period(
        self,
        period_type: str | None = None,
        year: int | str | None = None,
    ) -> XbrlFactQueryBuilder:
        """Filter facts by period type (instant/duration) and fiscal year."""
        if period_type:
            self._facts = [f for f in self._facts if f.period_type == period_type]
        if year is not None:
            yr_str = str(year)
            self._facts = [
                f
                for f in self._facts
                if (
                    f.instant_date if f.period_type == "instant" else f.end_date or ""
                ).startswith(yr_str)
            ]
        return self

    def unit(self, unit_name: str) -> XbrlFactQueryBuilder:
        """Filter facts reported in a specific unit (e.g. USD, shares)."""
        self._facts = [f for f in self._facts if f.unit == unit_name]
        return self

    def dimensions(
        self,
        axis_or_explicit: Mapping[str, str] | None = None,
        has_dimensions: bool | None = None,
    ) -> XbrlFactQueryBuilder:
        """Filter facts by dimensional coordinates or presence of hypercubes."""
        if has_dimensions is True:
            self._facts = [f for f in self._facts if bool(f.dimensions)]
        elif has_dimensions is False:
            self._facts = [f for f in self._facts if not f.dimensions]
        if axis_or_explicit:
            self._facts = [
                f
                for f in self._facts
                if all(f.dimensions.get(k) == v for k, v in axis_or_explicit.items())
            ]
        return self

    def axis_family(self, family: str) -> XbrlFactQueryBuilder:
        """Filter facts dimensioned on at least one axis of the given family."""
        self._facts = [
            f
            for f in self._facts
            if any(
                self._taxonomy.classify_axis(axis) == family for axis in f.dimensions
            )
        ]
        return self

    def member(self, member_qname: str) -> XbrlFactQueryBuilder:
        """Filter facts carrying the given member on any axis."""
        self._facts = [f for f in self._facts if member_qname in f.dimensions.values()]
        return self

    def text_contains(self, needle: str) -> XbrlFactQueryBuilder:
        """Filter string-valued facts whose filed text contains the needle.

        Matching is case-insensitive over the raw filed value (text
        blocks carry their HTML); numeric facts never match.
        """
        folded = needle.casefold()
        self._facts = [
            f
            for f in self._facts
            if isinstance(f.value, str) and folded in f.value.casefold()
        ]
        return self

    def latest_period(self) -> XbrlFactQueryBuilder:
        """Reduce to facts at the set's principal reporting coordinate.

        The coordinate is the modal instant (balance-sheet date), or
        the modal duration end when the set has no instant facts.
        """
        instants = Counter(
            f.instant_date for f in self._facts if f.instant_date is not None
        )
        if instants:
            coordinate = instants.most_common(1)[0][0]
        else:
            ends = Counter(
                f.end_date
                for f in self._facts
                if f.period_type == "duration" and f.end_date is not None
            )
            if not ends:
                self._facts = []
                return self
            coordinate = ends.most_common(1)[0][0]
        self._facts = [
            f
            for f in self._facts
            if f.instant_date == coordinate
            or (f.period_type == "duration" and f.end_date == coordinate)
        ]
        return self

    def face_only(self) -> XbrlFactQueryBuilder:
        """Filter for non-dimensional face financial statement facts."""
        self._facts = [f for f in self._facts if not f.dimensions]
        return self

    def filter(self, predicate: Callable[[XbrlFact], bool]) -> XbrlFactQueryBuilder:
        """Filter facts by custom caller predicate."""
        self._facts = [f for f in self._facts if predicate(f)]
        return self

    def execute(self) -> XbrlFactSet:
        """Materialize filtered facts into an immutable XbrlFactSet."""
        return XbrlFactSet(self._facts, self._taxonomy, records=self._records)


@dataclass(frozen=True, slots=True)
class AxisCoordinate:
    """One axis used by a fact set: its family and member usage counts."""

    axis: str
    family: str
    members: tuple[tuple[str, int], ...]


class XbrlFactSet:
    """Immutable sequence of facts with tabular serialization and query chaining."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        taxonomy: DomainTaxonomy,
        *,
        declarations: Mapping[str, ConceptDeclaration] | None = None,
        records: Mapping[str, DisplayRecord] | None = None,
    ) -> None:
        self._facts = tuple(facts)
        self._taxonomy = taxonomy
        self._records = (
            dict(records)
            if records is not None
            else build_display_records(self._facts, taxonomy, declarations)
        )

    @property
    def records(self) -> Mapping[str, DisplayRecord]:
        """Tokenized display records by concept qname, computed once."""
        return self._records

    def record_for(self, qname: str) -> DisplayRecord | None:
        """Return a concept's display record, or None when untokenized."""
        return self._records.get(qname)

    def dimensions(self) -> tuple[AxisCoordinate, ...]:
        """Dimensional coordinates used by this set, grouped by axis.

        Each axis carries its declared family and the members filed
        on it with their fact counts; a dimension-free set returns ().
        """
        members_by_axis: dict[str, Counter[str]] = {}
        for fact in self._facts:
            for axis, member in fact.dimensions.items():
                members_by_axis.setdefault(axis, Counter())[member] += 1
        return tuple(
            AxisCoordinate(
                axis=axis,
                family=self._taxonomy.classify_axis(axis),
                members=tuple(sorted(counts.items())),
            )
            for axis, counts in sorted(members_by_axis.items())
        )

    def __len__(self) -> int:
        return len(self._facts)

    def __iter__(self) -> Iterator[XbrlFact]:
        return iter(self._facts)

    def __getitem__(self, idx: int) -> XbrlFact:
        return self._facts[idx]

    def first(self) -> XbrlFact | None:
        """Return the first fact in the set, or None if empty."""
        return self._facts[0] if self._facts else None

    def query(self, concept: str | None = None, **kwargs: Any) -> XbrlFactQueryBuilder:
        """Spawn a fluent query builder seeded with current facts."""
        builder = XbrlFactQueryBuilder(self._facts, self._taxonomy, self._records)
        if concept:
            builder.concept(concept)
        if "unit" in kwargs:
            builder.unit(kwargs["unit"])
        if "period_type" in kwargs:
            builder.period(kwargs["period_type"])
        if "year" in kwargs:
            builder.period(year=kwargs["year"])
        return builder

    def to_dataframe(self) -> Any:
        """Export facts to a Polars or Pandas DataFrame, or list of dicts."""
        table = self.to_arrow()
        try:
            import polars as pl

            return pl.from_arrow(table)
        except ImportError:
            try:
                import pandas as pd

                return table.to_pandas()
            except ImportError:
                return table.to_pylist()

    def to_arrow(self) -> pa.Table:
        """Export facts to an Apache Arrow columnar Table."""
        return pa.Table.from_pylist(
            [
                {
                    "accession": str(f.accession),
                    "concept_qname": f.concept_qname,
                    "value": str(f.value) if f.value is not None else None,
                    "numeric_value": (
                        float(f.value) if isinstance(f.value, (int, float)) else None
                    ),
                    "unit": f.unit,
                    "decimals": f.decimals,
                    "period_type": f.period_type,
                    "start_date": f.start_date,
                    "end_date": f.end_date,
                    "instant_date": f.instant_date,
                    "dimensions": dict(f.dimensions),
                }
                for f in self._facts
            ]
        )
