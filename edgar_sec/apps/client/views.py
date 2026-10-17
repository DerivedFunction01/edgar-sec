"""Presentation views wrapping algebraic statement graphs and portfolios."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.rendering import (
    debt_to_dataframe,
    derivatives_to_dataframe,
    render_debt_ascii,
    render_derivatives_ascii,
    render_statement_ascii,
    statement_to_dataframe,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainOutcome
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

    def render_ascii(self, show_yoy: bool = True) -> str:
        """Render hierarchical ASCII tree with multi-year and YoY values."""
        return render_statement_ascii(self.graph, show_yoy=show_yoy)

    def __str__(self) -> str:
        return self.render_ascii()

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

    def by_risk(self, risk_type: str) -> tuple[Any, ...]:
        return self.graph.by_risk(risk_type)

    def by_structure(self, structure: str) -> tuple[Any, ...]:
        return self.graph.by_structure(structure)

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
