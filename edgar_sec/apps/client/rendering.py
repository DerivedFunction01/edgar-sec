"""ASCII visualization, formatting, and tabular export for financial graphs."""

from __future__ import annotations

from typing import Any

from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementGraph,
    StatementNode,
)


def render_statement_ascii(graph: StatementGraph, show_yoy: bool = True) -> str:
    """Render hierarchical ASCII tree with multi-year and YoY values."""
    lines: list[str] = [f"[{graph.statement_type.upper()}: {graph.root_qname}]"]
    if graph.years:
        lines.append(f"  Reported Periods: {', '.join(graph.years)}")

    def _traverse(node: StatementNode, indent: str = "  ") -> None:
        val_str = f"${node.value:,.0f}" if node.value is not None else "(unreported)"
        sign = "(+)" if node.weight > 0 else "(-)"
        yoy_info = ""
        if show_yoy and node.yoy_change is not None and node.yoy_pct is not None:
            yoy_info = f" | YoY: {node.yoy_change:+,.0f} ({node.yoy_pct * 100:+.1f}%)"
        lines.append(
            f"{indent}{sign} {node.label} [{node.concept_qname}]: {val_str}{yoy_info}"
        )
        for child in graph.children(node.concept_qname):
            _traverse(child, indent + "  ")

    root = graph.root
    if root:
        _traverse(root)
    return "\n".join(lines)


def render_derivatives_ascii(graph: DerivativePortfolioGraph) -> str:
    """Render ASCII summary of derivative gross-to-net exposures."""
    lines = [
        "[DERIVATIVE PORTFOLIO EXPOSURE]",
        f"  Notional Commitment:  {f'${graph.notional_amount:,.0f}' if graph.notional_amount else 'None'}",
        f"  Gross Assets:         {f'${graph.gross_assets:,.0f}' if graph.gross_assets else 'None'}",
        f"  Net Assets:           {f'${graph.net_assets:,.0f}' if graph.net_assets else 'None'}",
        f"  Gross Liabilities:    {f'${graph.gross_liabilities:,.0f}' if graph.gross_liabilities else 'None'}",
        f"  Net Liabilities:      {f'${graph.net_liabilities:,.0f}' if graph.net_liabilities else 'None'}",
        f"  Collateral Offsets:   {f'${graph.collateral_offsets:,.0f}' if graph.collateral_offsets else 'None'}",
        f"  Master Netting:       {f'${graph.master_netting_offsets:,.0f}' if graph.master_netting_offsets else 'None'}",
        f"  Reported Positions:   {len(graph.positions)} line items",
    ]
    return "\n".join(lines)


def render_debt_ascii(graph: DebtStructureGraph) -> str:
    """Render ASCII summary of capital debt structure."""
    lines = [
        "[DEBT AND CAPITAL STRUCTURE]",
        f"  Total Debt:           {f'${graph.total_debt:,.0f}' if graph.total_debt else 'None'}",
        f"  Current Maturities:   {f'${graph.current_debt:,.0f}' if graph.current_debt else 'None'}",
        f"  Long-Term Debt:       {f'${graph.long_term_debt:,.0f}' if graph.long_term_debt else 'None'}",
        f"  Lease Obligations:    {f'${graph.leases:,.0f}' if graph.leases else 'None'}",
        f"  Reported Instruments: {len(graph.positions)} line items",
    ]
    return "\n".join(lines)


def statement_to_dataframe(graph: StatementGraph, include_yoy: bool = True) -> Any:
    """Export statement nodes and multi-year series to a DataFrame."""
    records: list[dict[str, Any]] = []
    for node in graph.nodes.values():
        rec: dict[str, Any] = {
            "concept": node.concept_qname,
            "label": node.label,
            "weight": node.weight,
            "depth": node.depth,
            "value": node.value,
        }
        for yr in graph.years:
            rec[f"fy_{yr}"] = node.values.get(yr)
        if include_yoy:
            rec["yoy_change"] = node.yoy_change
            rec["yoy_pct"] = node.yoy_pct
        records.append(rec)
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def derivatives_to_dataframe(graph: DerivativePortfolioGraph) -> Any:
    """Export derivative positions to a DataFrame or records."""
    records = [
        {
            "concept": pos.concept_qname,
            "label": pos.label,
            "value": pos.value,
            "head": pos.atom.head,
            "modifiers": list(pos.atom.modifiers),
        }
        for pos in graph.positions
    ]
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def debt_to_dataframe(graph: DebtStructureGraph) -> Any:
    """Export debt positions to a DataFrame or records."""
    records = [
        {
            "concept": pos.concept_qname,
            "label": pos.label,
            "value": pos.value,
            "head": pos.atom.head,
            "modifiers": list(pos.atom.modifiers),
        }
        for pos in graph.positions
    ]
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records
