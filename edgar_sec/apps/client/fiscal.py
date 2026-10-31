"""Fiscal-year tier machinery behind the facade's fiscal-year queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

_SUCCESS_STATUSES = frozenset(
    {QueryStatus.REPORTED, QueryStatus.DERIVED, QueryStatus.VERIFIED}
)
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


def duration_span_key(period: tuple[str, str]) -> tuple[int, str, str]:
    start, end = period
    try:
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        span = -1
    return (-span, start, end)


class FiscalYearQueries:
    """Candidate-scope synthesis and tiered answering for one filing."""

    def __init__(
        self,
        facts: tuple[XbrlFact, ...],
        taxonomy: DomainTaxonomy,
        engine: FinancialQueryEngine,
    ) -> None:
        self._facts = facts
        self._taxonomy = taxonomy
        self._engine = engine

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
        year = str(fiscal_year)
        durations: set[tuple[str, str]] = set()
        instants: set[str] = set()
        for fact in self._facts:
            if fact.dimensions:
                continue
            if (
                fact.period_type == "duration"
                and fact.start_date
                and fact.end_date
                and fact.end_date[:4] == year
            ):
                durations.add((fact.start_date, fact.end_date))
            elif (
                fact.period_type == "instant"
                and fact.instant_date
                and fact.instant_date[:4] == year
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
        duration_tier, instant_tier = self._fiscal_year_tiers(
            fiscal_year, candidates, length_class
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
            message=f"no {length_class or 'ANNUAL'} period ending in fiscal year {fiscal_year}",
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

    def _modal_instant(self, fiscal_year: int) -> str | None:
        """Instant carrying the most undimensioned instant facts ending in fiscal_year."""
        counts: dict[str, int] = {}
        year = str(fiscal_year)
        for fact in self._facts:
            if (
                not fact.dimensions
                and fact.period_type == "instant"
                and fact.instant_date
                and fact.instant_date[:4] == year
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
