"""Presentation views wrapping algebraic statement graphs and portfolios."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.rendering import (
    cash_rollforward_to_dataframe,
    debt_to_dataframe,
    derivatives_to_dataframe,
    equity_rollforward_to_dataframe,
    level3_rollforward_to_dataframe,
    pension_funded_status_to_dataframe,
    render_cash_rollforward_ascii,
    render_debt_ascii,
    render_derivatives_ascii,
    render_equity_rollforward_ascii,
    render_level3_rollforward_ascii,
    render_pension_funded_status_ascii,
    render_segment_breakdown_ascii,
    render_statement_ascii,
    render_statement_table,
    segment_breakdown_to_dataframe,
    statement_to_dataframe,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainOutcome
from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    CashRollforwardGraph,
    EquityComponentRollforward,
    EquityRollforwardGraph,
    Level3RollforwardGraph,
    PensionFundedStatusGraph,
    PensionRollforwardSide,
    SegmentBreakdownGraph,
)
from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementGraph,
    StatementNode,
)


class StatementView:
    """Client wrapper providing tabular export and visual rendering over a graph."""

    def __init__(self, graph: StatementGraph) -> None:
        self.graph = graph

    @property
    def root(self) -> StatementNode | None:
        """Return the root statement node."""
        return self.graph.root

    @property
    def nodes(self) -> dict[str, StatementNode]:
        """Return the node dictionary."""
        return self.graph.nodes

    @property
    def years(self) -> tuple[str, ...]:
        """Return distinct reported fiscal years in the statement."""
        return self.graph.years

    def children(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return immediate children nodes rolling into this concept."""
        return self.graph.children(concept_qname)

    def parents(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return immediate parent nodes that this concept rolls up into."""
        return self.graph.parents(concept_qname)

    def chain(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return upward topological rollup chain from concept to root."""
        return self.graph.chain(concept_qname)

    def filter_year(self, year: int | str) -> StatementView:
        """Return a statement view filtered to a specific fiscal year."""
        return StatementView(self.graph.filter_year(year))

    def verify_antichain(self) -> AntiChainOutcome:
        """Verify non-double-counting and exact summation balance."""
        return self.graph.verify_antichain()

    def to_dataframe(self, include_yoy: bool = True) -> Any:
        """Export statement nodes and multi-year series to a DataFrame."""
        return statement_to_dataframe(self.graph, include_yoy=include_yoy)

    def render_table(self, view: str = "standard") -> str:
        """Render clean multi-column accounting statement table."""
        return render_statement_table(self.graph, view=view)

    def render_ascii(self, show_yoy: bool = True) -> str:
        """Render hierarchical ASCII tree with multi-year and YoY values."""
        return render_statement_ascii(self.graph, show_yoy=show_yoy)

    def __str__(self) -> str:
        return self.render_table()

    def __repr__(self) -> str:
        r = self.root.concept_qname if self.root else "None"
        return f"<StatementView statement={self.graph.statement_type!r} root={r!r} years={self.years}>"


class DerivativePortfolioView:
    """Presentation wrapper for gross-to-net derivative exposures."""

    def __init__(self, graph: DerivativePortfolioGraph) -> None:
        self.graph = graph

    @property
    def notional_amount(self) -> float | None:
        return self.graph.notional_amount

    @property
    def gross_assets(self) -> float | None:
        return self.graph.gross_assets

    @property
    def net_assets(self) -> float | None:
        return self.graph.net_assets

    @property
    def gross_liabilities(self) -> float | None:
        return self.graph.gross_liabilities

    @property
    def net_liabilities(self) -> float | None:
        return self.graph.net_liabilities

    @property
    def collateral_offsets(self) -> float | None:
        return self.graph.collateral_offsets

    @property
    def master_netting_offsets(self) -> float | None:
        return self.graph.master_netting_offsets

    @property
    def positions(self) -> tuple[Any, ...]:
        return self.graph.positions

    @property
    def risk_categories(self) -> tuple[str, ...]:
        return tuple(self.graph.by_risk.keys())

    @property
    def risk_totals(self) -> dict[str, dict[str, float]]:
        return dict(self.graph.risk_totals)

    def by_risk(self, risk_type: str) -> tuple[Any, ...]:
        return self.graph.positions_by_risk(risk_type)

    def by_structure(self, structure: str) -> tuple[Any, ...]:
        return tuple(
            p for p in self.graph.positions if structure.lower() in p.label.lower()
        )

    def to_dataframe(self) -> Any:
        """Export derivative positions to a tabular DataFrame."""
        return derivatives_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of derivative gross-to-net exposures."""
        return render_derivatives_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<DerivativePortfolioView gross_assets={self.gross_assets} "
            f"net_assets={self.net_assets} positions={len(self.positions)}>"
        )


class DebtStructureView:
    """Presentation wrapper for capital and funded debt structures."""

    def __init__(self, graph: DebtStructureGraph) -> None:
        self.graph = graph

    @property
    def total_debt(self) -> float | None:
        return self.graph.total_debt

    @property
    def commercial_paper(self) -> float | None:
        return self.graph.commercial_paper

    @property
    def current_debt(self) -> float | None:
        return self.graph.current_debt

    @property
    def long_term_debt(self) -> float | None:
        return self.graph.long_term_debt

    @property
    def leases(self) -> float | None:
        return self.graph.leases

    @property
    def maturities(self) -> tuple[Any, ...]:
        return self.graph.maturities

    @property
    def maturities_by_year(self) -> dict[str, float]:
        return dict(self.graph.maturities_by_year)

    def to_dataframe(self) -> Any:
        """Export debt tranches to a tabular DataFrame."""
        return debt_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of debt and capital structure."""
        return render_debt_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return f"<DebtStructureView total_debt={self.total_debt} tranches={len(self.maturities)}>"


class CashRollforwardView:
    """Presentation wrapper for the ASU 2016-18 cash rollforward."""

    def __init__(self, graph: CashRollforwardGraph) -> None:
        self.graph = graph

    @property
    def beginning(self) -> float | None:
        return self.graph.beginning

    @property
    def net_change(self) -> float | None:
        return self.graph.net_change

    @property
    def end(self) -> float | None:
        return self.graph.end

    @property
    def beginning_date(self) -> str | None:
        return self.graph.beginning_date

    @property
    def end_date(self) -> str | None:
        return self.graph.end_date

    @property
    def balance_sheet_total(self) -> float | None:
        return self.graph.balance_sheet_total

    @property
    def components(self) -> tuple[Any, ...]:
        return self.graph.components

    @property
    def rollforward_discrepancy(self) -> float | None:
        return self.graph.rollforward_discrepancy

    @property
    def rollforward_verified(self) -> bool | None:
        return self.graph.rollforward_verified

    @property
    def balance_sheet_discrepancy(self) -> float | None:
        return self.graph.balance_sheet_discrepancy

    @property
    def balance_sheet_verified(self) -> bool | None:
        return self.graph.balance_sheet_verified

    def to_dataframe(self) -> Any:
        """Export rollforward legs and components to a DataFrame."""
        return cash_rollforward_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of the rollforward and its checks."""
        return render_cash_rollforward_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<CashRollforwardView end={self.end} verified={self.rollforward_verified}>"
        )


class SegmentBreakdownView:
    """Presentation wrapper for a per-axis segment breakdown."""

    def __init__(self, graph: SegmentBreakdownGraph) -> None:
        self.graph = graph

    @property
    def concept_qname(self) -> str | None:
        return self.graph.concept_qname

    @property
    def axis_qname(self) -> str | None:
        return self.graph.axis_qname

    @property
    def total(self) -> float | None:
        return self.graph.total

    @property
    def members(self) -> tuple[Any, ...]:
        return self.graph.members

    @property
    def member_sum(self) -> float | None:
        return self.graph.member_sum

    @property
    def discrepancy(self) -> float | None:
        return self.graph.discrepancy

    @property
    def verified(self) -> bool | None:
        return self.graph.verified

    @property
    def values_by_member(self) -> dict[str, float]:
        return {member.member_qname: member.value for member in self.graph.members}

    def to_dataframe(self) -> Any:
        """Export segment members and the reported total to a DataFrame."""
        return segment_breakdown_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of the breakdown and its total check."""
        return render_segment_breakdown_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<SegmentBreakdownView concept={self.concept_qname} "
            f"axis={self.axis_qname} verified={self.verified}>"
        )


class Level3RollforwardView:
    """Presentation wrapper for an ASC 820 Level-3 rollforward."""

    def __init__(self, graph: Level3RollforwardGraph) -> None:
        self.graph = graph

    @property
    def dimensions(self) -> tuple[tuple[str, str], ...]:
        return self.graph.dimensions

    @property
    def axis_qname(self) -> str | None:
        return self.graph.axis_qname

    @property
    def member_qname(self) -> str | None:
        return self.graph.member_qname

    @property
    def opening(self) -> float | None:
        return self.graph.opening

    @property
    def closing(self) -> float | None:
        return self.graph.closing

    @property
    def gains_earnings(self) -> float | None:
        return self.graph.gains_earnings

    @property
    def gains_oci(self) -> float | None:
        return self.graph.gains_oci

    @property
    def total_gains(self) -> float | None:
        return self.graph.total_gains

    @property
    def purchases(self) -> float | None:
        return self.graph.purchases

    @property
    def sales(self) -> float | None:
        return self.graph.sales

    @property
    def issues(self) -> float | None:
        return self.graph.issues

    @property
    def settlements(self) -> float | None:
        return self.graph.settlements

    @property
    def transfers_in(self) -> float | None:
        return self.graph.transfers_in

    @property
    def transfers_out(self) -> float | None:
        return self.graph.transfers_out

    @property
    def transfers_net(self) -> float | None:
        return self.graph.transfers_net

    @property
    def net_change(self) -> float | None:
        return self.graph.net_change

    @property
    def discrepancy(self) -> float | None:
        return self.graph.discrepancy

    @property
    def verified(self) -> bool | None:
        return self.graph.verified

    @property
    def change_verified(self) -> bool | None:
        return self.graph.change_verified

    @property
    def missing_components(self) -> tuple[str, ...]:
        return self.graph.missing_components

    @property
    def movements(self) -> tuple[Any, ...]:
        return self.graph.movements

    def to_dataframe(self) -> Any:
        """Export rollforward legs to a DataFrame."""
        return level3_rollforward_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of the rollforward and its checks."""
        return render_level3_rollforward_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<Level3RollforwardView member={self.member_qname} "
            f"closing={self.closing} verified={self.verified}>"
        )


class PensionFundedStatusView:
    """Presentation wrapper for a defined-benefit funded status (ASC 715)."""

    def __init__(self, graph: PensionFundedStatusGraph) -> None:
        self.graph = graph

    @property
    def dimensions(self) -> tuple[tuple[str, str], ...]:
        return self.graph.dimensions

    @property
    def plan_assets(self) -> PensionRollforwardSide:
        return self.graph.plan_assets

    @property
    def obligation(self) -> PensionRollforwardSide:
        return self.graph.obligation

    @property
    def assets_opening(self) -> float | None:
        return self.graph.plan_assets.opening

    @property
    def assets_closing(self) -> float | None:
        return self.graph.plan_assets.closing

    @property
    def obligation_opening(self) -> float | None:
        return self.graph.obligation.opening

    @property
    def obligation_closing(self) -> float | None:
        return self.graph.obligation.closing

    @property
    def assets_verified(self) -> bool | None:
        return self.graph.plan_assets.verified

    @property
    def obligation_verified(self) -> bool | None:
        return self.graph.obligation.verified

    @property
    def funded_status(self) -> float | None:
        return self.graph.funded_status

    @property
    def funded_status_filed(self) -> float | None:
        return self.graph.funded_status_filed

    @property
    def funded_verified(self) -> bool | None:
        return self.graph.funded_verified

    @property
    def missing_components(self) -> tuple[str, ...]:
        return self.graph.missing_components

    @property
    def movements(self) -> tuple[Any, ...]:
        return self.graph.movements

    def to_dataframe(self) -> Any:
        """Export both rollforwards' legs to a DataFrame."""
        return pension_funded_status_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of the funded status and its checks."""
        return render_pension_funded_status_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<PensionFundedStatusView funded={self.funded_status} "
            f"verified={self.funded_verified}>"
        )


class EquityRollforwardView:
    """Presentation wrapper for the statement of changes in equity."""

    def __init__(self, graph: EquityRollforwardGraph) -> None:
        self.graph = graph

    @property
    def axis_qname(self) -> str | None:
        return self.graph.axis_qname

    @property
    def balance_concept(self) -> str | None:
        return self.graph.balance_concept

    @property
    def opening(self) -> float | None:
        return self.graph.opening

    @property
    def closing(self) -> float | None:
        return self.graph.closing

    @property
    def components(self) -> tuple[EquityComponentRollforward, ...]:
        return self.graph.components

    def component(self, member_qname: str) -> EquityComponentRollforward | None:
        return self.graph.component(member_qname)

    @property
    def antichain_members(self) -> tuple[str, ...]:
        return self.graph.antichain_members

    @property
    def computed_closing(self) -> float | None:
        return self.graph.computed_closing

    @property
    def discrepancy(self) -> float | None:
        return self.graph.discrepancy

    @property
    def verified(self) -> bool | None:
        return self.graph.verified

    @property
    def components_sum(self) -> float | None:
        return self.graph.components_sum

    @property
    def components_discrepancy(self) -> float | None:
        return self.graph.components_discrepancy

    @property
    def components_verified(self) -> bool | None:
        return self.graph.components_verified

    @property
    def missing_components(self) -> tuple[str, ...]:
        return self.graph.missing_components

    @property
    def movements(self) -> tuple[Any, ...]:
        return self.graph.movements

    def to_dataframe(self) -> Any:
        """Export each component's legs and the total to a DataFrame."""
        return equity_rollforward_to_dataframe(self.graph)

    def render_ascii(self) -> str:
        """Render ASCII summary of the rollforward and its checks."""
        return render_equity_rollforward_ascii(self.graph)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<EquityRollforwardView closing={self.closing} verified={self.verified}>"
        )
