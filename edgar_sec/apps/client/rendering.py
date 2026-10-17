"""ASCII visualization, formatting, and tabular export for financial graphs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementGraph,
    StatementNode,
)


def _format_cell(val: float | None) -> str:
    if val is None:
        return "-"
    if val < 0:
        return f"$({abs(val):,.0f})"
    return f"${val:,.0f}"


def _format_pct(pct: float | None) -> str:
    if pct is None:
        return "-"
    return f"{pct * 100:+.1f}%"


def render_statement_table(
    graph: StatementGraph,
    view: str = "standard",
) -> str:
    """Render statement as a multi-column accounting table with side-by-side years."""
    if not graph.root:
        return f"[{graph.statement_type.upper()}: (empty)]"

    years = sorted(graph.years)
    visited: set[str] = set()
    ordered_nodes: list[tuple[StatementNode, int]] = []

    def _traverse(node: StatementNode, depth: int) -> None:
        if node.concept_qname in visited:
            return
        visited.add(node.concept_qname)
        children = graph.children(node.concept_qname)
        for child in children:
            _traverse(child, depth + 1)
        ordered_nodes.append((node, depth))

    _traverse(graph.root, 0)

    if view == "summary":
        ordered_nodes = [
            (n, d)
            for n, d in ordered_nodes
            if d <= 1 or n.concept_qname == graph.root_qname
        ]

    col_widths = [42] + [18] * len(years) + [12]
    headers = ["Financial Concept"] + [f"FY {y}" for y in years] + ["YoY (%)"]
    sep = "=" * (sum(col_widths) + len(col_widths) * 2)
    sub_sep = "-" * (sum(col_widths) + len(col_widths) * 2)

    lines: list[str] = [
        f"[{graph.statement_type.upper()}]",
        sep,
        "  ".join(
            h.ljust(col_widths[i]) if i == 0 else h.rjust(col_widths[i])
            for i, h in enumerate(headers)
        ),
        sub_sep,
    ]

    for node, depth in ordered_nodes:
        indent = "  " * depth
        label = (
            node.label if view != "detailed" else f"{node.label} [{node.concept_qname}]"
        )
        name_cell = (indent + label)[: col_widths[0]].ljust(col_widths[0])
        val_cells = [
            _format_cell(node.values.get(y)).rjust(col_widths[i + 1])
            for i, y in enumerate(years)
        ]
        pct_cell = _format_pct(node.yoy_pct).rjust(col_widths[-1])
        row_str = "  ".join([name_cell] + val_cells + [pct_cell])
        lines.append(row_str)

    lines.append(sep)
    return "\n".join(lines)


def render_comparison_table(
    cohort_data: Mapping[str, Mapping[str, float | None]],
    metric_labels: Sequence[tuple[str, str]],
) -> str:
    """Render cross-company comparison table aligning canonical metrics and ratios."""
    companies = list(cohort_data.keys())
    col_w_metric = 28
    col_w_data = 18
    sep_len = col_w_metric + len(companies) * (col_w_data + 2)
    sep = "=" * sep_len
    sub_sep = "-" * sep_len

    headers = [metric.ljust(col_w_metric) for metric in ["Metric"]] + [
        c.rjust(col_w_data) for c in companies
    ]
    lines = [
        sep,
        "  ".join(headers),
        sub_sep,
    ]

    for key, label in metric_labels:
        row = [label.ljust(col_w_metric)]
        for c in companies:
            val = cohort_data[c].get(key)
            if (
                key.endswith("_pct")
                or key.endswith("_margin")
                or key.endswith("_ratio")
            ):
                cell = (
                    f"{val * 100:.1f}%".rjust(col_w_data)
                    if val is not None
                    else "-".rjust(col_w_data)
                )
            else:
                cell = _format_cell(val).rjust(col_w_data)
            row.append(cell)
        lines.append("  ".join(row))

    lines.append(sep)
    return "\n".join(lines)


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
    """Render ASCII summary of derivative gross-to-net exposures and risk buckets."""
    lines = [
        "[DERIVATIVE PORTFOLIO EXPOSURE]",
        f"  Notional Commitment:  {f'${graph.notional_amount:,.0f}' if graph.notional_amount else 'None'}",
        f"  Gross Assets:         {f'${graph.gross_assets:,.0f}' if graph.gross_assets else 'None'}",
        f"  Net Assets:           {f'${graph.net_assets:,.0f}' if graph.net_assets else 'None'}",
        f"  Gross Liabilities:    {f'${graph.gross_liabilities:,.0f}' if graph.gross_liabilities else 'None'}",
        f"  Net Liabilities:      {f'${graph.net_liabilities:,.0f}' if graph.net_liabilities else 'None'}",
        f"  Collateral Offsets:   {f'${graph.collateral_offsets:,.0f}' if graph.collateral_offsets else 'None'}",
        f"  Master Netting:       {f'${graph.master_netting_offsets:,.0f}' if graph.master_netting_offsets else 'None'}",
    ]
    if graph.by_risk:
        lines.append("  Risk Categories:")
        for risk, pos in graph.by_risk.items():
            rt = graph.risk_totals.get(risk, {})
            assets = rt.get("gross_assets", 0.0)
            liab = rt.get("gross_liabilities", 0.0)
            lines.append(
                f"    - {risk.replace('_', ' ').title()}: {len(pos)} positions "
                f"| Assets: ${assets:,.0f} | Liab: ${liab:,.0f}"
            )
    lines.append(f"  Reported Positions:   {len(graph.positions)} line items")
    return "\n".join(lines)


def render_debt_ascii(graph: DebtStructureGraph) -> str:
    """Render ASCII summary of capital debt structure and maturities."""
    lines = [
        "[DEBT AND CAPITAL STRUCTURE]",
        f"  Total Debt:           {f'${graph.total_debt:,.0f}' if graph.total_debt else 'None'}",
        f"  Commercial Paper:     {f'${graph.commercial_paper:,.0f}' if graph.commercial_paper else 'None'}",
        f"  Current Maturities:   {f'${graph.current_debt:,.0f}' if graph.current_debt else 'None'}",
        f"  Long-Term Debt:       {f'${graph.long_term_debt:,.0f}' if graph.long_term_debt else 'None'}",
        f"  Lease Obligations:    {f'${graph.leases:,.0f}' if graph.leases else 'None'}",
    ]
    if graph.maturities_by_year:
        lines.append("  Maturity Schedule:")
        for yr, val in sorted(graph.maturities_by_year.items()):
            lines.append(f"    - FY {yr}: ${val:,.0f}")
    lines.append(f"  Reported Instruments: {len(graph.positions)} line items")
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
