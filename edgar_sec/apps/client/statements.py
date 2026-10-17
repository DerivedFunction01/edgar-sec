"""Statement graph factory and presentation gateway."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.apps.client.views import StatementView
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


class XbrlStatements:
    """Statement graph factory for operations, balance sheet, and cash flows."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
        self._taxonomy = taxonomy
        self._labels = dict(labels or {})
        self._composer = StatementComposer(
            self._facts, self._arcs, self._taxonomy, self._labels
        )

    def income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Operations rollup view."""
        graph = self._composer.compose_income_statement(period=period, year=year)
        return StatementView(graph)

    def balance_sheet(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Balance Sheet rollup view."""
        graph = self._composer.compose_balance_sheet(period=period, year=year)
        return StatementView(graph)

    def cash_flow_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Cash Flows rollup view."""
        graph = self._composer.compose_cash_flow(period=period, year=year)
        return StatementView(graph)
