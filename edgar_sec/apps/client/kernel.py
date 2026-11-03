"""Shared per-filing state behind the client statement surfaces.

One kernel per filing carries the facts, arcs, records, and the
engine composer both surfaces consume, so their state cannot diverge.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from edgar_sec.apps.client.equity_rollforward import build_equity_rollforward
from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.views import EquityRollforwardView
from edgar_sec.engine.xbrl.normalize.filed_metadata import (
    FiledMetadata,
    filed_metadata as read_filed_metadata,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    DefinitionArc,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.solve.statement import (
    BalanceSheetGraph,
    CashFlowGraph,
    IncomeStatementGraph,
    period_rank,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def _span_length_class(fact: XbrlFact) -> str | None:
    """Length class of a fact's span; None when the fact carries no span."""
    if not fact.start_date or not fact.end_date:
        return None
    return normalize_time_coordinate(
        fact.period_type, fact.instant_date, fact.start_date, fact.end_date
    ).length_class


def _resolve_arcs(source: Any) -> tuple:
    """Materialize an arc source: call a supplier once, else tuple it."""
    return tuple(source() if callable(source) else source)


class LazyMapping(Mapping):
    """A mapping whose payload is computed once, on first read.

    It stands for its payload from construction (never falsy), so a
    consumer's `mapping or {}` keeps it; any read materializes it.
    """

    def __init__(self, supplier: Callable[[], Mapping[Any, Any]]) -> None:
        self._supplier: Callable[[], Mapping[Any, Any]] | None = supplier
        self._data: dict[Any, Any] | None = None

    def _materialize(self) -> dict[Any, Any]:
        """The payload dict, computing and caching it on first call."""
        if self._data is None:
            supplier, self._supplier = self._supplier, None
            self._data = dict(supplier())  # type: ignore[union-attr]
        return self._data

    def __getitem__(self, key: Any) -> Any:
        return self._materialize()[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._materialize())

    def __len__(self) -> int:
        return len(self._materialize())

    def __bool__(self) -> bool:
        return True


class FilingKernel:
    """One filing's facts, arcs, records, and composer, shared by both surfaces."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc]
        | Callable[[], Sequence[CalculationArc]],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
        *,
        records: Mapping[str, DisplayRecord] | None = None,
        declarations: Mapping[str, ConceptDeclaration]
        | Callable[[], Mapping[str, ConceptDeclaration]]
        | None = None,
        definition_arcs: Sequence[DefinitionArc]
        | Callable[[], Sequence[DefinitionArc]] = (),
        presentation_arcs: Sequence[PresentationArc]
        | Callable[[], Sequence[PresentationArc]] = (),
        cik: str | None = None,
        accession: str | None = None,
    ) -> None:
        self.facts = tuple(facts)
        self._calculation_arcs_source: Any = calculation_arcs
        self._calculation_arcs: tuple[CalculationArc, ...] | None = None
        self._definition_arcs_source: Any = definition_arcs
        self._definition_arcs: tuple[DefinitionArc, ...] | None = None
        self._presentation_arcs_source: Any = presentation_arcs
        self._presentation_arcs: tuple[PresentationArc, ...] | None = None
        self.cik = cik
        self.accession = accession
        self.taxonomy = taxonomy
        self.labels = dict(labels or {})
        self.records = dict(records or {})
        if callable(declarations):
            self.declarations: Mapping[str, ConceptDeclaration] = LazyMapping(
                declarations
            )
        else:
            self.declarations = dict(declarations or {})
        self._tokenizer = (
            ConceptTokenizer(taxonomy) if taxonomy.token_lexicon is not None else None
        )
        self._atom_cache: dict[str, Atom | None] = {}
        self._composer: StatementComposer | None = None
        self._composition_cache: dict[
            tuple[str, str | None, int | str | None], Any
        ] = {}
        self._graph_cache: dict[tuple, Any] = {}
        self._best_ranked_cache: dict[
            tuple[bool | None, str, bool],
            dict[tuple[str, str], tuple[tuple[int, int], float]],
        ] = {}
        self._series_cache: dict[tuple, dict[str, float]] = {}
        self._facts_by_qname: dict[str, tuple[XbrlFact, ...]] | None = None
        self._filed_metadata: FiledMetadata | None = None
        self._facts_by_head: dict[str | None, tuple[XbrlFact, ...]] | None = None

    @property
    def calculation_arcs(self) -> tuple[CalculationArc, ...]:
        """Calculation arcs, loaded on first access when supplied lazily."""
        if self._calculation_arcs is None:
            self._calculation_arcs = _resolve_arcs(self._calculation_arcs_source)
            self._calculation_arcs_source = None
        return self._calculation_arcs

    @calculation_arcs.setter
    def calculation_arcs(self, arcs: Sequence[CalculationArc]) -> None:
        self._calculation_arcs = tuple(arcs)
        self._calculation_arcs_source = None

    @property
    def definition_arcs(self) -> tuple[DefinitionArc, ...]:
        """Definition arcs, loaded on first access when supplied lazily."""
        if self._definition_arcs is None:
            self._definition_arcs = _resolve_arcs(self._definition_arcs_source)
            self._definition_arcs_source = None
        return self._definition_arcs

    @definition_arcs.setter
    def definition_arcs(self, arcs: Sequence[DefinitionArc]) -> None:
        self._definition_arcs = tuple(arcs)
        self._definition_arcs_source = None

    @property
    def presentation_arcs(self) -> tuple[PresentationArc, ...]:
        """Presentation arcs, loaded on first access when supplied lazily."""
        if self._presentation_arcs is None:
            self._presentation_arcs = _resolve_arcs(self._presentation_arcs_source)
            self._presentation_arcs_source = None
        return self._presentation_arcs

    @presentation_arcs.setter
    def presentation_arcs(self, arcs: Sequence[PresentationArc]) -> None:
        self._presentation_arcs = tuple(arcs)
        self._presentation_arcs_source = None

    @property
    def composer(self) -> StatementComposer:
        """The statement composer, built on first use from the calc arcs."""
        if self._composer is None:
            self._composer = StatementComposer(
                self.facts,
                self.calculation_arcs,
                self.taxonomy,
                self.labels,
                atom_resolver=self.atom,
            )
        return self._composer

    @property
    def registrant_name(self) -> str | None:
        """The filer's dei registrant name, when the cover facts carry it."""
        for fact in self.facts_by_qname().get("dei:EntityRegistrantName", ()):
            if isinstance(fact.value, str) and fact.value:
                return fact.value
        return None

    @property
    def filed_metadata(self) -> FiledMetadata:
        """The filing's filed dei period/fiscal metadata block."""
        if self._filed_metadata is None:
            self._filed_metadata = read_filed_metadata(self.facts)
        return self._filed_metadata

    def facts_by_qname(self) -> dict[str, tuple[XbrlFact, ...]]:
        """Facts indexed by concept qname, built once per filing."""
        if self._facts_by_qname is None:
            index: dict[str, list[XbrlFact]] = {}
            for fact in self.facts:
                index.setdefault(fact.concept_qname, []).append(fact)
            self._facts_by_qname = {
                qname: tuple(facts) for qname, facts in index.items()
            }
        return self._facts_by_qname

    def facts_by_head(self) -> dict[str | None, tuple[XbrlFact, ...]]:
        """Facts indexed by atom head, built once per filing.

        Facts whose concept resolves to no atom group under None.
        """
        if self._facts_by_head is None:
            index: dict[str | None, list[XbrlFact]] = {}
            for fact in self.facts:
                atom = self.atom(fact.concept_qname)
                index.setdefault(atom.head if atom else None, []).append(fact)
            self._facts_by_head = {head: tuple(facts) for head, facts in index.items()}
        return self._facts_by_head

    def compose_income_statement(
        self, period: str | None = None, year: int | str | None = None
    ) -> IncomeStatementGraph:
        """The filing's income-statement composition, built once per key."""
        return self._compose("income", period, year)

    def compose_balance_sheet(
        self, period: str | None = None, year: int | str | None = None
    ) -> BalanceSheetGraph:
        """The filing's balance-sheet composition, built once per key."""
        return self._compose("balance", period, year)

    def compose_cash_flow(
        self, period: str | None = None, year: int | str | None = None
    ) -> CashFlowGraph:
        """The filing's cash-flow composition, built once per key."""
        return self._compose("cash", period, year)

    def _compose(self, kind: str, period: str | None, year: int | str | None) -> Any:
        key = (kind, period, year)
        if key not in self._composition_cache:
            builder = {
                "income": self.composer.compose_income_statement,
                "balance": self.composer.compose_balance_sheet,
                "cash": self.composer.compose_cash_flow,
            }[kind]
            self._composition_cache[key] = builder(period, year)
        return self._composition_cache[key]

    def graph_once(self, key: tuple, build: Callable[[], Any]) -> Any:
        """Build a derived graph once per key and share the instance.

        Sharing is safe: graph nodes are frozen dataclasses and every
        consumer reads; surfaces wrap the shared graph per call.
        """
        if key not in self._graph_cache:
            self._graph_cache[key] = build()
        return self._graph_cache[key]

    def best_ranked(
        self,
        *,
        instant: bool | None,
        length_class: str,
        monetary_only: bool,
    ) -> dict[tuple[str, str], tuple[tuple[int, int], float]]:
        """Best fact per (concept, year) by period rank, one scan per key.

        instant selects the dating: True reads instant dates, False end
        dates, None whichever date the fact carries.
        """
        key = (instant, length_class, monetary_only)
        if key in self._best_ranked_cache:
            return self._best_ranked_cache[key]
        best: dict[tuple[str, str], tuple[tuple[int, int], float]] = {}
        for f in self.facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            if monetary_only and f.unit in ("pure", "shares", "item", "ratio"):
                continue
            span_class = _span_length_class(f)
            if span_class is not None and span_class != length_class:
                continue
            if instant is True:
                dt = f.instant_date
            elif instant is False:
                dt = f.end_date
            else:
                dt = f.instant_date or f.end_date
            if not dt:
                continue
            fact_key = (f.concept_qname, dt[:4])
            rank = period_rank(f)
            if fact_key not in best or rank > best[fact_key][0]:
                best[fact_key] = (rank, float(f.value))
        self._best_ranked_cache[key] = best
        return best

    def series(
        self, key: tuple, compute: Callable[[], dict[str, float]]
    ) -> dict[str, float]:
        """Memoized series scan; the result is shared — treat as read-only."""
        if key not in self._series_cache:
            self._series_cache[key] = compute()
        return self._series_cache[key]

    def atom(self, qname: str) -> Atom | None:
        """Atom for a concept: the display record, else the tokenizer."""
        record = self.records.get(qname)
        if record is not None:
            return record.atom
        if qname not in self._atom_cache:
            if self._tokenizer is None:
                self._atom_cache[qname] = None
            else:
                tokenized = self._tokenizer.tokenize(
                    qname, self.declarations.get(qname)
                )
                self._atom_cache[qname] = tokenized.atom
        return self._atom_cache[qname]

    def equity_rollforward(
        self,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> EquityRollforwardView:
        """Resolve the statement of changes in equity, verified by identity."""
        graph = self.graph_once(
            ("equity_rollforward", member_qname, year),
            lambda: build_equity_rollforward(
                self.facts,
                self.records,
                self.taxonomy,
                self.labels,
                year,
                member_qname=member_qname,
                definition_arcs=self.definition_arcs,
            ),
        )
        return EquityRollforwardView(graph)
