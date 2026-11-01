"""Ergonomic XBRL facts, statement graphs, and algebraic financial facade."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.comparison import ComparisonView, compare_companies
from edgar_sec.apps.client.composition import (
    ChainTerms,
    CompositionResult,
    evaluate_chain,
)
from edgar_sec.apps.client.facts import (
    AxisCoordinate,
    XbrlFactSet,
    build_fact_set_from_lookup,
    build_fact_set_from_snapshot,
    build_fact_set_from_table,
    facts_from_arrow_table,
    snapshot_rows,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.apps.client.display import filing_header
from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.location import (
    FIDELITY_BUNDLE,
    FIDELITY_INSTANCE,
    FIDELITY_LOOKUP,
    FIDELITY_SNAPSHOT,
    FactLocation,
    build_location,
)
from edgar_sec.apps.client.search import FactSearch, search_facts
from edgar_sec.apps.client.fiscal import FiscalYearQueries, duration_length_class
from edgar_sec.apps.client.statements import XbrlStatements
from edgar_sec.apps.client.views import StatementView
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    ConceptLabel,
    FilingXbrl,
    LinkbaseBundle,
    PresentationArc,
)
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    StatementNode,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortFactMatch
from edgar_sec.engine.xbrl.solve.cohort_scan import iter_cohort_batches
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry, ConceptTable
from edgar_sec.engine.xbrl.solve.evidence_index import (
    FilingEvidenceRecord,
    build_filing_evidence,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.storage.storage import (
    calculation_arcs_from_arrow_table,
    declarations_from_arrow_table,
    definition_arcs_from_arrow_table,
    presentation_arcs_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.archive import (
    bundle_namespaces,
    current_table,
    table_for_namespaces,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for

_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"


def _labels_by_concept(labels: Sequence[ConceptLabel]) -> dict[str, str]:
    best: dict[str, tuple[tuple[int, int], str]] = {}
    for label in labels:
        rank = (
            0 if label.role_uri == _STANDARD_LABEL_ROLE else 1,
            0 if label.lang == "en-US" else 1,
        )
        current = best.get(label.concept_qname)
        if current is None or rank < current[0]:
            best[label.concept_qname] = (rank, label.label)
    return {qname: text for qname, (_, text) in best.items()}


class Xbrl:
    """Unified Layer 5 XBRL client facade providing algebraic graphs and fact queries."""

    def __init__(
        self,
        filing_xbrl: FilingXbrl,
        taxonomy: DomainTaxonomy | None = None,
    ) -> None:
        self._populate(filing_xbrl, taxonomy)

    def _populate(
        self,
        filing_xbrl: FilingXbrl,
        taxonomy: DomainTaxonomy | None = None,
        *,
        fact_set: XbrlFactSet | None = None,
        evidence_record: FilingEvidenceRecord | None = None,
        arc_suppliers: dict[str, Any] | None = None,
    ) -> None:
        """Shared construction path for loaded and cohort-sourced facades."""
        self._filing = filing_xbrl
        self._taxonomy = taxonomy or load_domain_taxonomy()
        self._evidence_record = evidence_record
        self._axes_cache: tuple[AxisCoordinate, ...] | None = None
        self._financials: XbrlFinancials | None = None
        self._arcs_deferred = arc_suppliers is not None

        linkbases = self._filing.linkbases
        if arc_suppliers is not None:
            calc_source: Any = arc_suppliers["calculation"]
            def_source: Any = arc_suppliers["definition"]
            pres_source: Any = arc_suppliers["presentation"]
        else:
            calc_source = linkbases.calculation_arcs if linkbases else ()
            def_source = linkbases.definition_arcs if linkbases else ()
            pres_source = linkbases.presentation_arcs if linkbases else ()
        raw_labels = linkbases.labels if linkbases else ()
        self._labels = _labels_by_concept(raw_labels)

        if fact_set is not None:
            self.facts = fact_set
            merged: Any = None
        else:
            merged = self._merged_declarations(tuple(calc_source))
            self.facts = XbrlFactSet(
                self._filing.facts, self._taxonomy, declarations=merged
            )
        kernel = FilingKernel(
            self._filing.facts,
            calc_source,
            self._taxonomy,
            self._labels,
            records=self.facts.records,
            declarations=(
                merged
                if merged is not None
                else lambda: self._merged_declarations(kernel.calculation_arcs)
            ),
            definition_arcs=def_source,
            presentation_arcs=pres_source,
            cik=(self._filing.cik.to_10digit() if int(self._filing.cik) else None),
            accession=str(self._filing.accession),
        )
        self._kernel = kernel
        self._provenance = (
            FIDELITY_INSTANCE if filing_xbrl.instance_document else FIDELITY_BUNDLE
        )
        self.statements = XbrlStatements(self._kernel)

        kb = EvidenceKnowledgeBase(self._taxonomy)
        solver = XbrlConstraintSolver(kb)
        self._query_engine = FinancialQueryEngine(
            solver, declarations=self._kernel.declarations
        )
        self._fiscal = FiscalYearQueries(
            self._filing.facts, self._taxonomy, self._query_engine
        )

    @property
    def financials(self) -> XbrlFinancials:
        """The algebraic financials surface, built on first access."""
        if self._financials is None:
            self._financials = XbrlFinancials(
                self._kernel,
                composition_resolver=self._resolve_composition,
            )
        return self._financials

    @classmethod
    def from_cohort(
        cls,
        table: ConceptTable,
        entries: Sequence[CohortEntry],
        accession: str,
    ) -> Xbrl:
        """Build a facade for one cohort filing from the Phase 3 scan.

        Facts are full-fidelity from the scanned bundle; records come from the concept table.
        """
        import pyarrow.parquet as pq

        def arc_supplier(path: Path, reader: Any) -> Any:
            """Zero-arg loader reading one arc parquet on first use."""

            def load() -> tuple:
                return reader(pq.read_table(path)) if path.exists() else ()

            return load

        for batch, tables in iter_cohort_batches(entries):
            for entry, arrow in zip(batch, tables, strict=True):
                if entry.accession != accession:
                    continue
                facts = facts_from_arrow_table(arrow)
                bundle_dir = entry.facts_path.parent
                decl_path = bundle_dir / "declarations.parquet"
                declarations = (
                    declarations_from_arrow_table(read_declarations_parquet(decl_path))
                    if decl_path.exists()
                    else ()
                )
                bundle = FilingXbrl(
                    accession=AccessionNumber.from_any(accession),
                    cik=Cik(0),
                    facts=facts,
                    linkbases=LinkbaseBundle(declarations=declarations),
                    namespaces=tuple(sorted(bundle_namespaces(bundle_dir).items())),
                )
                instance = object.__new__(cls)
                instance._populate(
                    bundle,
                    table.taxonomy,
                    fact_set=build_fact_set_from_table(facts, table),
                    evidence_record=build_filing_evidence(entry, table),
                    arc_suppliers={
                        "calculation": arc_supplier(
                            bundle_dir / "calculation_arcs.parquet",
                            calculation_arcs_from_arrow_table,
                        ),
                        "presentation": arc_supplier(
                            bundle_dir / "presentation_arcs.parquet",
                            presentation_arcs_from_arrow_table,
                        ),
                        "definition": arc_supplier(
                            bundle_dir / "definition_arcs.parquet",
                            definition_arcs_from_arrow_table,
                        ),
                    },
                )
                return instance
        raise ValueError(f"accession {accession} not among cohort entries")

    @classmethod
    def from_lookup(
        cls,
        table: ConceptTable,
        matches: Sequence[CohortFactMatch],
        accession: str,
    ) -> Xbrl:
        """Build a display facade from equivalence-lookup matches.

        Lookup facts are a projection (no dimensions, decimals, or
        arcs); records carry the matches' tier and rule.
        """
        selected = tuple(m for m in matches if m.accession == accession)
        fact_set = build_fact_set_from_lookup(selected, table)
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(accession),
            cik=Cik(0),
            facts=tuple(fact_set),
            linkbases=None,
        )
        instance = object.__new__(cls)
        instance._populate(bundle, table.taxonomy, fact_set=fact_set)
        instance._provenance = FIDELITY_LOOKUP
        return instance

    @classmethod
    def from_snapshot(
        cls,
        artifacts_root: Path | str,
        snapshot_id: str,
        accession: str,
        *,
        table: ConceptTable | None = None,
    ) -> Xbrl:
        """Build a projection facade from one accession's snapshot solved nodes.

        Facts carry no unit, dimensions, or decimals; the snapshot's
        calculation and presentation arcs ride on the linkbase bundle.
        """
        nodes, calc_arcs, pres_arcs = snapshot_rows(
            artifacts_root, snapshot_id, accession
        )
        if not nodes:
            raise ValueError(f"accession {accession} not in snapshot {snapshot_id}")
        taxonomy = table.taxonomy if table is not None else load_domain_taxonomy()
        fact_set = build_fact_set_from_snapshot(nodes, taxonomy, table)
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(accession),
            cik=Cik(int(nodes[0]["cik"] or 0)),
            facts=tuple(fact_set),
            linkbases=LinkbaseBundle(
                calculation_arcs=calc_arcs, presentation_arcs=pres_arcs
            ),
        )
        instance = object.__new__(cls)
        instance._populate(bundle, taxonomy, fact_set=fact_set)
        instance._provenance = FIDELITY_SNAPSHOT
        return instance

    def _merged_declarations(
        self, arcs: tuple[CalculationArc, ...]
    ) -> dict[str, ConceptDeclaration]:
        """Bundle declarations merged over the filing-vintage archive table."""
        extension = {}
        if self._filing.linkbases is not None:
            extension = {
                item.concept_qname: item for item in self._filing.linkbases.declarations
            }
        if self._filing.namespaces:
            table = table_for_namespaces(dict(self._filing.namespaces))
        else:
            table = current_table()
        qnames = {fact.concept_qname for fact in self._filing.facts}
        for arc in arcs:
            qnames.update((arc.parent_qname, arc.child_qname))
        merged = {}
        for qname in sorted(qnames):
            declaration = declaration_for(qname, table, extension)
            if declaration is not None:
                merged[qname] = declaration
        return merged

    @property
    def accession(self) -> str:
        """Return the filing accession number."""
        return str(self._filing.accession)

    @property
    def cik(self) -> str:
        """Return the filer CIK."""
        return str(self._filing.cik)

    @property
    def linkbases(self) -> LinkbaseBundle | None:
        """Return raw linkbase bundle attached to this filing.

        A deferred facade materializes its arc sets for this call, so
        the returned bundle always carries the filing's full arcs.
        """
        base = self._filing.linkbases
        if base is None or not self._arcs_deferred:
            return base
        return LinkbaseBundle(
            calculation_arcs=self._kernel.calculation_arcs,
            presentation_arcs=self._kernel.presentation_arcs,
            labels=base.labels,
            declarations=base.declarations,
            definition_arcs=self._kernel.definition_arcs,
        )

    @property
    def evidence(self) -> FilingEvidenceRecord | None:
        """This filing's evidence record; only cohort facades carry one."""
        return self._evidence_record

    @property
    def axes(self) -> tuple[AxisCoordinate, ...]:
        """Dimensional coordinates used by this filing's facts."""
        if self._axes_cache is None:
            self._axes_cache = self.facts.dimensions()
        return self._axes_cache

    def query(
        self,
        term: str,
        mode: QueryMode | str = QueryMode.REPORTED_ONLY,
        fiscal_year: int | None = None,
        scope: FactScope | None = None,
        length_class: str | None = None,
        dimension_policy: str | None = None,
    ) -> FinancialQueryResult:
        """Query a concept, synthesizing an exact scope from fiscal_year if needed.

        An explicit scope is executed verbatim; unknown mode strings raise ValueError. dimension_policy names an opt-in totals policy for the fiscal-year path.
        """
        query_mode = self._parse_query_mode(mode)
        policy = self._parse_dimension_policy(dimension_policy)
        arcs = self._kernel.calculation_arcs
        if scope is not None:
            return self._execute_query(term, query_mode, scope, arcs)
        accession = self._scope_accession()
        candidates = (
            self._fiscal.candidate_scopes(
                accession, fiscal_year, dimension_policy=policy
            )
            if fiscal_year is not None
            else ()
        )
        if not candidates:
            return self._execute_query(
                term, query_mode, FactScope(accession=accession), arcs
            )
        return self._fiscal.execute(
            term,
            query_mode,
            fiscal_year,
            candidates,
            arcs,
            length_class=length_class,
            dimension_policy=policy,
        )

    def search(self, term: str, *, limit: int | None = None) -> FactSearch:
        """Rank this filing's facts by coordinate closeness to a term.

        Retrieval only: a hit confers no equivalence status and
        never feeds query() or solver results.
        """
        return search_facts(
            term, tuple(self.facts), self.facts.records, self._taxonomy, limit=limit
        )

    def locate(self, qname: str, *, period: str | None = None) -> FactLocation:
        """Locate a concept: document, role paths, calc parents, context.

        Descriptive only. Period (an ISO instant or duration end
        date) selects the fact whose context block is carried.
        """
        return build_location(
            self._kernel,
            self._filing,
            self.statements._catalog(),
            qname,
            period=period,
            fidelity=self._provenance,
        )

    @staticmethod
    def _parse_query_mode(mode: QueryMode | str) -> QueryMode:
        if isinstance(mode, QueryMode):
            return mode
        try:
            return QueryMode(mode)
        except ValueError:
            raise ValueError(f"Unknown XBRL query mode: {mode!r}") from None

    @staticmethod
    def _parse_dimension_policy(policy: str | None) -> str | None:
        if policy is None or policy == "horizon_totals":
            return policy
        raise ValueError(f"Unknown XBRL dimension policy: {policy!r}")

    def _execute_query(
        self,
        term: str,
        mode: QueryMode,
        scope: FactScope,
        arcs: Sequence[CalculationArc],
    ) -> FinancialQueryResult:
        query = FinancialQuery(term=term, scope=scope, mode=mode)
        return self._query_engine.execute(
            query, facts=self._filing.facts, calculation_arcs=arcs
        )

    def _scope_accession(self) -> str:
        accessions = {str(fact.accession) for fact in self._filing.facts}
        if len(accessions) == 1:
            return accessions.pop()
        return str(self._filing.accession)

    def graph(
        self,
        root_concept: str,
        period_type: str = "duration",
        year: int | str | None = None,
    ) -> StatementView:
        """Construct an algebraic StatementView for any arbitrary concept in the filing."""
        arcs = self._kernel.calculation_arcs
        graph = build_statement_graph(
            root_concept=root_concept,
            statement_type=f"Custom: {root_concept}",
            facts=self._filing.facts,
            arcs=arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            period_type=period_type,
            year=year,
            graph_cls=StatementGraph,
        )
        header = filing_header(
            self._kernel.registrant_name, self._kernel.cik, self._kernel.accession
        )
        return StatementView(graph, header=header)

    def chain(
        self,
        child_concept: str,
        root_concept: str,
        period_type: str = "duration",
        year: int | str | None = None,
    ) -> tuple[StatementNode, ...]:
        """Trace the upward topological rollup chain from child concept to root."""
        stmt = self.graph(root_concept, period_type=period_type, year=year)
        return stmt.chain(child_concept)

    def compare(
        self,
        others: Sequence[Xbrl],
        metrics: Sequence[str] | None = None,
        year: int | str | None = None,
    ) -> ComparisonView:
        """Compare this filing against other filings across coordinate subspaces."""
        return compare_companies([self, *others], metrics=metrics, year=year)

    def _resolve_composition(
        self, terms: ChainTerms, fiscal_year: int | None
    ) -> CompositionResult:
        """Composition entry point injected into the financials delegates."""
        return self.compose(terms, fiscal_year=fiscal_year)

    def compose(
        self,
        terms: ChainTerms,
        *,
        fiscal_year: int | None = None,
        mode: QueryMode | str = QueryMode.REPORTED_ONLY,
        dimension_policy: str | None = None,
    ) -> CompositionResult:
        """Evaluate a user-composed add/subtract chain over named operands."""
        query_mode = self._parse_query_mode(mode)
        policy = self._parse_dimension_policy(dimension_policy)
        arcs = self._kernel.calculation_arcs
        return evaluate_chain(
            lambda term: self._resolve_operand(term, query_mode, fiscal_year, policy),
            terms,
            arcs,
        )

    def _resolve_operand(
        self,
        term: str,
        mode: QueryMode,
        fiscal_year: int | None,
        dimension_policy: str | None = None,
    ) -> FinancialQueryResult:
        """Operand ladder: name/reported, tokenizer equivalence, derived.

        Presumption below the name is the engine's ladder: derived,
        filing-local placement, then presumed_atom's global defaults.
        """
        result = self.query(
            term, mode=mode, fiscal_year=fiscal_year, dimension_policy=dimension_policy
        )
        if result.value is not None or mode is not QueryMode.REPORTED_ONLY:
            return result
        equivalent = self._tokenizer_equivalent(term, fiscal_year)
        if equivalent is not None:
            return equivalent
        derived = self.query(
            term,
            mode=QueryMode.VERIFY_DERIVATION,
            fiscal_year=fiscal_year,
            dimension_policy=dimension_policy,
        )
        return derived if derived.value is not None else result

    def _tokenizer_equivalent(
        self, term: str, fiscal_year: int | None
    ) -> FinancialQueryResult | None:
        """Resolve an example fact (or alias target) by atom equivalence."""
        if self._taxonomy.token_lexicon is None or not self.facts.records:
            return None
        tokenizer = ConceptTokenizer(self._taxonomy)
        if ":" in term:
            target_atoms = (tokenizer.tokenize(term).atom,)
        else:
            target_atoms = self._taxonomy.query_alias_atoms(term)
        if not target_atoms:
            return None
        for atom in target_atoms:
            required = {m for m in atom.modifiers if not m.startswith("V_")}
            by_year: dict[str, list] = {}
            for fact in self.facts:
                if fact.dimensions or not isinstance(fact.value, (int, float)):
                    continue
                if fact.unit in ("pure", "shares", "item", "ratio"):
                    continue
                if fact.start_date and fact.end_date:
                    if (
                        duration_length_class(fact.start_date, fact.end_date)
                        != "ANNUAL"
                    ):
                        continue
                record = self.facts.records.get(fact.concept_qname)
                if record is None or record.atom.head != atom.head:
                    continue
                if not required.issubset(record.atom.modifiers):
                    continue
                date = (
                    fact.instant_date
                    if fact.period_type == "instant"
                    else fact.end_date
                )
                if date and len(date[:4]) == 4 and date[:4].isdigit():
                    by_year.setdefault(date[:4], []).append((fact, record))
            if not by_year:
                continue
            year = str(fiscal_year) if fiscal_year is not None else max(by_year)
            pool = by_year.get(year)
            if not pool:
                continue
            fact, record = max(pool, key=lambda pair: abs(float(pair[0].value)))
            exact = record.atom.head == atom.head and set(record.atom.modifiers) == set(
                atom.modifiers
            )
            return FinancialQueryResult(
                query=FinancialQuery(
                    term=term,
                    scope=FactScope(accession=self._scope_accession()),
                ),
                status=QueryStatus.REPORTED if exact else QueryStatus.DERIVED,
                candidate_qnames=(fact.concept_qname,),
                candidate_facts=(fact,),
                target_atom=atom,
                reported_fact=fact,
            )
        return None

    def __repr__(self) -> str:
        return f"<Xbrl accession={self._filing.accession} facts={len(self.facts)}>"
