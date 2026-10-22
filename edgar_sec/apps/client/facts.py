"""Fluent querying and tabular serialization of XBRL instance facts."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from edgar_sec.engine.xbrl.normalize.decomposer import residual_counts
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration, XbrlFact
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer, TokenizedFact
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.foundation.serialization import canonical_json


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
