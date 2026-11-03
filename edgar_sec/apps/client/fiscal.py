"""Fiscal-year tier machinery behind the facade's fiscal-year queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from edgar_sec.domain.forms.common.aliases import is_transition_form
from edgar_sec.engine.xbrl.normalize.filed_metadata import (
    FiledMetadata,
    filed_metadata,
    fiscal_year_containing,
    focus_length_class,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.apps.client.composition import CompositionResult
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    StatementNode,
    period_rank,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

_SUCCESS_STATUSES = frozenset(
    {QueryStatus.REPORTED, QueryStatus.DERIVED, QueryStatus.VERIFIED}
)
_SERVING_LENGTH_CLASSES = frozenset({"ANNUAL", "QUARTER", "YTD_2Q", "YTD_3Q"})
_PRECEDENCE_RANK = {
    QueryStatus.VERIFIED: 0,
    QueryStatus.REPORTED: 1,
    QueryStatus.CONFLICT: 2,
    QueryStatus.DERIVED: 3,
    QueryStatus.AMBIGUOUS: 4,
    QueryStatus.UNAVAILABLE: 5,
}


def duration_length_class(start: str, end: str) -> str:
    return normalize_time_coordinate("duration", None, start, end).length_class


def fact_length_class(fact: XbrlFact) -> str | None:
    """Length class of one fact's span; INSTANT for an instant fact."""
    if fact.period_type == "instant":
        return "INSTANT"
    if fact.start_date and fact.end_date:
        return duration_length_class(fact.start_date, fact.end_date)
    return None


def node_length_class(node: StatementNode, year: str | None = None) -> str | None:
    """Length class of the fact a node serves, at a year or its latest.

    The served fact is the node's best-ranked numeric fact of the year,
    the same winner the graph builder picked for the node's value.
    """
    if year is None:
        if node.value is None or not node.values:
            return None
        year = max(node.values)
    best: tuple[tuple[int, int], XbrlFact] | None = None
    for fact in node.facts:
        if not isinstance(fact.value, (int, float)):
            continue
        if (fact.instant_date or fact.end_date or "")[:4] != year:
            continue
        rank = period_rank(fact)
        if best is None or rank > best[0]:
            best = (rank, fact)
    return fact_length_class(best[1]) if best is not None else None


def graph_span_class(graph: StatementGraph | None) -> str | None:
    """Length class a statement graph's root serves at its latest year."""
    if graph is None or graph.root is None:
        return None
    return node_length_class(graph.root)


def chain_span_class(*attempts: tuple[float | None, str | None]) -> str | None:
    """Served class of an `or` chain: first truthy, else the last served."""
    last: str | None = None
    for value, cls in attempts:
        if value:
            return cls
        if value is not None:
            last = cls
    return last


def composition_span_class(result: CompositionResult) -> str | None:
    """Length class of a composed chain's shared operand period."""
    for operand in result.operands:
        key = operand.period_key
        if not key:
            continue
        if key.startswith("duration:"):
            _, start, end = key.split(":", 2)
            return duration_length_class(start, end)
        if key.startswith("instant:"):
            return "INSTANT"
    return None


def statement_year_classes(graph: StatementGraph) -> dict[str, str]:
    """Served length class per graph year, from the root node's winners."""
    root = graph.root
    if root is None:
        return {}
    classes: dict[str, str] = {}
    for year in graph.years:
        served = node_length_class(root, year)
        if served is not None:
            classes[year] = served
    return classes


def duration_span_key(period: tuple[str, str]) -> tuple[int, str, str]:
    start, end = period
    try:
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        span = -1
    return (-span, start, end)


def filed_length_class(
    facts: Sequence[XbrlFact], metadata: FiledMetadata
) -> str | None:
    """The length class a filing declares for its own focus period.

    The dei period focus names it; where dei is silent, the most-carried
    duration ending at the period end derives it, if corroborated.
    """
    focus = focus_length_class(metadata.period_focus)
    if focus is not None:
        return focus if _class_corroborated(facts, metadata, focus) else None
    derived = _span_derived_class(facts, metadata)
    if derived is not None and _class_corroborated(facts, metadata, derived):
        return derived
    return None


def _span_derived_class(
    facts: Sequence[XbrlFact], metadata: FiledMetadata
) -> str | None:
    """Length class of the most-carried duration ending at the period end."""
    counts: dict[tuple[str, str], int] = {}
    for fact in facts:
        if fact.dimensions or fact.period_type != "duration":
            continue
        if not fact.start_date or not fact.end_date:
            continue
        if metadata.period_end is not None and fact.end_date != metadata.period_end:
            continue
        key = (fact.start_date, fact.end_date)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    start, end = max(
        counts, key=lambda key: (counts[key], -duration_span_key(key)[0], key)
    )
    derived = duration_length_class(start, end)
    return derived if derived in _SERVING_LENGTH_CLASSES else None


def _class_corroborated(
    facts: Sequence[XbrlFact], metadata: FiledMetadata, length_class: str
) -> bool:
    """Whether the filing's spans corroborate a declared length class.

    The class's most-carried period at the period end must be a longest
    span there; a longer span leaves the two in disagreement.
    """
    period_end = metadata.period_end
    if period_end is None:
        return True
    counts: dict[tuple[str, str], int] = {}
    longest = 0
    for fact in facts:
        if fact.dimensions or fact.period_type != "duration":
            continue
        if not fact.start_date or fact.end_date != period_end:
            continue
        span = -duration_span_key((fact.start_date, fact.end_date))[0]
        longest = max(longest, span)
        if duration_length_class(fact.start_date, fact.end_date) == length_class:
            key = (fact.start_date, fact.end_date)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return False
    chosen = max(counts, key=lambda key: (counts[key], -duration_span_key(key)[0], key))
    return -duration_span_key(chosen)[0] >= longest


def transition_period(
    facts: Sequence[XbrlFact], metadata: FiledMetadata
) -> tuple[str, str] | None:
    """A transition filing's stub period; None for other filings.

    The stub is the most-carried undimensioned duration period,
    preferring one ending at the filed period end.
    """
    if not is_transition_form(metadata.document_type):
        return None
    counts: dict[tuple[str, str], int] = {}
    for fact in facts:
        if fact.dimensions or fact.period_type != "duration":
            continue
        if not fact.start_date or not fact.end_date:
            continue
        key = (fact.start_date, fact.end_date)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    at_end = [key for key in counts if key[1] == metadata.period_end]
    pool = at_end or list(counts)
    return max(pool, key=lambda key: (counts[key], -duration_span_key(key)[0], key))


def transition_length_class(
    facts: Sequence[XbrlFact], metadata: FiledMetadata
) -> str | None:
    """Length class of a transition filing's stub period; None otherwise."""
    period = transition_period(facts, metadata)
    if period is None:
        return None
    return duration_length_class(period[0], period[1])


class FiscalYearQueries:
    """Candidate-scope synthesis and tiered answering for one filing."""

    def __init__(
        self,
        facts: tuple[XbrlFact, ...],
        taxonomy: DomainTaxonomy,
        engine: FinancialQueryEngine,
        *,
        metadata: FiledMetadata | None = None,
    ) -> None:
        self._facts = facts
        self._taxonomy = taxonomy
        self._engine = engine
        self._metadata = metadata if metadata is not None else filed_metadata(facts)
        self._window_year, self._window_offset = self._dei_window()

    def _dei_window(self) -> tuple[int | None, int]:
        """The filing's own fiscal year in dei terms, and its naming offset.

        The offset is the filed focus minus the FYE-window year of the
        period end: 0 for ending-year naming, -1 for start-year naming.
        """
        md = self._metadata
        if md.fiscal_year_end is None or md.period_end is None:
            return None, 0
        try:
            containing = fiscal_year_containing(md.period_end, md.fiscal_year_end)
        except ValueError:
            return None, 0
        own = md.fiscal_year if md.fiscal_year is not None else containing
        return own, own - containing

    def _in_fiscal_year(self, day: str, fiscal_year: int) -> bool:
        """Whether a period end or instant date belongs to the fiscal year.

        The dei FYE window governs when the request names the filing's own year in dei terms and the calendar rule would miss its periods.
        """
        md = self._metadata
        fye = md.fiscal_year_end
        if (
            fye is not None
            and self._window_year is not None
            and self._window_year == fiscal_year
            and md.period_end is not None
            and md.period_end[:4] != str(fiscal_year)
        ):
            try:
                containing = fiscal_year_containing(day, fye)
            except ValueError:
                return day[:4] == str(fiscal_year)
            return containing + self._window_offset == fiscal_year
        return day[:4] == str(fiscal_year)

    def _execute_query(
        self,
        term: str,
        mode: QueryMode,
        scope: FactScope,
        arcs: Sequence[CalculationArc],
    ) -> FinancialQueryResult:
        query = FinancialQuery(term=term, scope=scope, mode=mode)
        return self._engine.execute(query, facts=self._facts, calculation_arcs=arcs)

    def candidate_scopes(
        self,
        accession: str,
        fiscal_year: int,
        *,
        dimension_policy: str | None = None,
    ) -> tuple[FactScope, ...]:
        durations: set[tuple[str, str]] = set()
        instants: set[str] = set()
        for fact in self._facts:
            if fact.dimensions:
                continue
            if (
                fact.period_type == "duration"
                and fact.start_date
                and fact.end_date
                and self._in_fiscal_year(fact.end_date, fiscal_year)
            ):
                durations.add((fact.start_date, fact.end_date))
            elif (
                fact.period_type == "instant"
                and fact.instant_date
                and self._in_fiscal_year(fact.instant_date, fiscal_year)
            ):
                instants.add(fact.instant_date)
        periods: list[tuple[str | None, str | None, str | None]] = [
            (start, end, None)
            for start, end in sorted(durations, key=duration_span_key)
        ]
        periods.extend((None, None, instant) for instant in sorted(instants))
        scopes: list[FactScope] = []
        for start, end, instant in periods:
            scopes.append(
                FactScope(
                    accession=accession,
                    start_date=start,
                    end_date=end,
                    instant_date=instant,
                )
            )
            for unit in self._period_units(start, end, instant):
                scopes.append(
                    FactScope(
                        accession=accession,
                        start_date=start,
                        end_date=end,
                        instant_date=instant,
                        unit=unit,
                    )
                )
        if dimension_policy == "horizon_totals":
            scopes.extend(self._horizon_total_scopes(accession, periods))
        return tuple(scopes)

    def _horizon_total_scopes(
        self,
        accession: str,
        periods: list[tuple[str | None, str | None, str | None]],
    ) -> list[FactScope]:
        """Exact scopes for facts dimensioned solely on HORIZON-family axes.

        One scope per distinct dimension dict filed at a harvested
        period, appended after that period's undimensioned scopes.
        """
        harvested = set(periods)
        dims_by_period: dict[
            tuple[str | None, str | None, str | None], set[tuple[tuple[str, str], ...]]
        ] = {}
        for fact in self._facts:
            if not fact.dimensions:
                continue
            if not all(
                self._taxonomy.classify_axis(axis) == "HORIZON"
                for axis in fact.dimensions
            ):
                continue
            if fact.period_type == "duration":
                key = (fact.start_date, fact.end_date, None)
            else:
                key = (None, None, fact.instant_date)
            if key in harvested:
                dims_by_period.setdefault(key, set()).add(
                    tuple(sorted(fact.dimensions.items()))
                )
        scopes: list[FactScope] = []
        for start, end, instant in periods:
            for dims in sorted(dims_by_period.get((start, end, instant), ())):
                scopes.append(
                    FactScope(
                        accession=accession,
                        start_date=start,
                        end_date=end,
                        instant_date=instant,
                        dimensions=dict(dims),
                    )
                )
        return scopes

    def execute(
        self,
        term: str,
        mode: QueryMode,
        fiscal_year: int,
        candidates: tuple[FactScope, ...],
        arcs: Sequence[CalculationArc],
        *,
        length_class: str | None = None,
        dimension_policy: str | None = None,
    ) -> FinancialQueryResult:
        """Answer from the faithful tiers: class-matched durations, then FYE instants.

        A scope answers only when its span's length class is the requested one (ANNUAL by default).
        """
        effective = length_class or self._filed_length_class()
        duration_tier, instant_tier = self._fiscal_year_tiers(
            fiscal_year, candidates, effective
        )
        outcome, first, results = self._tier_outcome(
            term, mode, duration_tier, arcs, dimension_policy=dimension_policy
        )
        if outcome is not None and outcome.status in _SUCCESS_STATUSES:
            return outcome
        if (
            outcome is not None
            and outcome.status != QueryStatus.UNAVAILABLE
            and self._tier_is_duration_opinion(results)
        ):
            return outcome
        if length_class is None or length_class == "INSTANT":
            instant_outcome, instant_first, _ = self._tier_outcome(
                term, mode, instant_tier, arcs, dimension_policy=dimension_policy
            )
        else:
            instant_outcome, instant_first = None, None
        if instant_outcome is not None and self._is_instant_substitution(
            term, instant_outcome, candidates, arcs
        ):
            instant_outcome = None
            instant_first = None
        if outcome is not None and outcome.status != QueryStatus.UNAVAILABLE:
            return instant_outcome if instant_outcome is not None else outcome
        if (
            instant_outcome is not None
            and instant_outcome.status != QueryStatus.UNAVAILABLE
        ):
            return instant_outcome
        if first is not None:
            return first
        if instant_first is not None:
            return instant_first
        scope = FactScope(accession=candidates[0].accession)
        return FinancialQueryResult(
            query=FinancialQuery(term=term, scope=scope),
            status=QueryStatus.UNAVAILABLE,
            message=f"no {effective or 'ANNUAL'} period ending in fiscal year {fiscal_year}",
        )

    def _filed_length_class(self) -> str | None:
        """The requested length class this filing declares for itself."""
        return filed_length_class(self._facts, self._metadata)

    def _is_instant_substitution(
        self,
        term: str,
        instant_outcome: FinancialQueryResult,
        candidates: tuple[FactScope, ...],
        arcs: Sequence[CalculationArc],
    ) -> bool:
        """Whether an instant-tier success substitutes another concept for the term.

        A substitution serves a concept outside the term's filing-wide candidates while a candidate carries the term as a duration.
        """
        if instant_outcome.status not in _SUCCESS_STATUSES:
            return False
        if instant_outcome.value is None:
            return False
        served = instant_outcome.reported_fact
        served_qname = served.concept_qname if served is not None else None
        if served_qname is None and instant_outcome.aggregate is not None:
            served_qname = instant_outcome.aggregate.measure_id
        if served_qname is None:
            return False
        if any(
            fact.concept_qname == served_qname and fact.period_type == "duration"
            for fact in self._facts
        ):
            return False
        probe = self._execute_query(
            term,
            QueryMode.REPORTED_ONLY,
            FactScope(accession=candidates[0].accession),
            arcs,
        )
        if served_qname in probe.candidate_qnames:
            return False
        return any(
            fact.concept_qname in probe.candidate_qnames
            and fact.period_type == "duration"
            and not fact.dimensions
            for fact in self._facts
        )

    def _tier_outcome(
        self,
        term: str,
        mode: QueryMode,
        scopes: tuple[FactScope, ...],
        arcs: Sequence[CalculationArc],
        *,
        dimension_policy: str | None = None,
    ) -> tuple[
        FinancialQueryResult | None,
        FinancialQueryResult | None,
        tuple[FinancialQueryResult, ...],
    ]:
        """Best outcome in the tier under the split precedence; ties keep scope order.

        Under a dimension policy, a dimensioned winner with a second
        distinct filed value on the tier is AMBIGUOUS, not a total.
        """
        first: FinancialQueryResult | None = None
        outcome: FinancialQueryResult | None = None
        results: list[FinancialQueryResult] = []
        for scope in scopes:
            result = self._execute_query(term, mode, scope, arcs)
            if first is None:
                first = result
            results.append(result)
            if outcome is None or (
                _PRECEDENCE_RANK[result.status] < _PRECEDENCE_RANK[outcome.status]
            ):
                outcome = result
        if (
            dimension_policy is not None
            and outcome is not None
            and outcome.status in (QueryStatus.REPORTED, QueryStatus.VERIFIED)
            and any(
                scope.dimensions and result is outcome
                for scope, result in zip(scopes, results, strict=True)
            )
        ):
            filed_values = {
                result.value
                for scope, result in zip(scopes, results, strict=True)
                if scope.dimensions
                and result.status in (QueryStatus.REPORTED, QueryStatus.VERIFIED)
            }
            if len(filed_values) > 1:
                outcome = FinancialQueryResult(
                    query=outcome.query,
                    status=QueryStatus.AMBIGUOUS,
                    candidate_qnames=outcome.candidate_qnames,
                    message=(
                        "multiple filed totals on total-carrying axes; "
                        "no single dimensioned total"
                    ),
                )
        return outcome, first, tuple(results)

    def _tier_is_duration_opinion(
        self, results: tuple[FinancialQueryResult, ...]
    ) -> bool:
        """Whether any candidate on the tier's results carries a duration fact here."""
        qnames = {qname for result in results for qname in result.candidate_qnames}
        return any(
            fact.concept_qname in qnames and fact.period_type == "duration"
            for fact in self._facts
        )

    def _fiscal_year_tiers(
        self,
        fiscal_year: int,
        candidates: tuple[FactScope, ...],
        length_class: str | None = None,
    ) -> tuple[tuple[FactScope, ...], tuple[FactScope, ...]]:
        """Split candidates into the class-matched duration group and the FYE instant group.

        The duration group is the most-carried period of the requested length class (ANNUAL by default).
        """
        target = length_class or "ANNUAL"
        groups: dict[tuple[str | None, str | None, str | None], list[FactScope]] = {}
        for scope in candidates:
            key = (scope.start_date, scope.end_date, scope.instant_date)
            groups.setdefault(key, []).append(scope)
        counts: dict[tuple[str | None, str | None, str | None], int] = {}
        for fact in self._facts:
            if fact.dimensions or fact.period_type != "duration":
                continue
            key = (fact.start_date, fact.end_date, None)
            if key in groups and key[0] and key[1]:
                if duration_length_class(key[0], key[1]) == target:
                    counts[key] = counts.get(key, 0) + 1
        annual = max(
            counts,
            key=lambda key: (
                counts[key],
                -duration_span_key((key[0] or "", key[1] or ""))[0],
                key,
            ),
            default=None,
        )
        if annual is None and self._transition_tier_applies(length_class):
            annual = self._transition_tier_key(groups)
        modal = self._modal_instant(fiscal_year)
        duration_tier = tuple(
            scope for scope in groups.get(annual, []) if annual is not None
        )
        instant_tier = tuple(
            scope
            for key, group in groups.items()
            if key[2] is not None and key[2] == modal
            for scope in group
        )
        return duration_tier, instant_tier

    def _transition_tier_applies(self, length_class: str | None) -> bool:
        """Whether the empty class tier is a transition filing's stub year.

        Only the dei focus class (or the default) may fall back: an
        explicit off-focus class request keeps the empty tier.
        """
        if not is_transition_form(self._metadata.document_type):
            return False
        focus = focus_length_class(self._metadata.period_focus)
        return length_class is None or length_class == focus

    def _transition_tier_key(
        self,
        groups: dict[tuple[str | None, str | None, str | None], list[FactScope]],
    ) -> tuple[str | None, str | None, str | None] | None:
        """Most-carried candidate duration period of a transition filing.

        The transition year's own period is a stub the length ladder
        classes below the focus class; it is the year's duration tier.
        """
        period = transition_period(self._facts, self._metadata)
        if period is not None and (period[0], period[1], None) in groups:
            return (period[0], period[1], None)
        counts: dict[tuple[str | None, str | None, str | None], int] = {}
        for fact in self._facts:
            if fact.dimensions or fact.period_type != "duration":
                continue
            key = (fact.start_date, fact.end_date, None)
            if key in groups and key[0] and key[1]:
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return None
        period_end = self._metadata.period_end
        at_end = [key for key in counts if key[1] == period_end]
        pool = at_end or list(counts)
        return max(
            pool,
            key=lambda key: (
                counts[key],
                -duration_span_key((key[0] or "", key[1] or ""))[0],
                key,
            ),
        )

    def _modal_instant(self, fiscal_year: int) -> str | None:
        """Instant carrying the most undimensioned instant facts in the fiscal year."""
        counts: dict[str, int] = {}
        for fact in self._facts:
            if (
                not fact.dimensions
                and fact.period_type == "instant"
                and fact.instant_date
                and self._in_fiscal_year(fact.instant_date, fiscal_year)
            ):
                counts[fact.instant_date] = counts.get(fact.instant_date, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: (item[1], item[0]))[0]

    def _period_units(
        self, start: str | None, end: str | None, instant: str | None
    ) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for fact in self._facts:
            if fact.dimensions or fact.unit is None:
                continue
            if instant is not None:
                matches = fact.period_type == "instant" and fact.instant_date == instant
            else:
                matches = (
                    fact.period_type == "duration"
                    and fact.start_date == start
                    and fact.end_date == end
                )
            if matches:
                counts[fact.unit] = counts.get(fact.unit, 0) + 1
        return tuple(sorted(counts, key=lambda unit: (-counts[unit], unit)))
