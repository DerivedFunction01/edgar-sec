"""ASCII visualization, formatting, and tabular export for financial graphs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from edgar_sec.apps.client.display import (
    choose_scale,
    class_display,
    display_label,
    format_cell,
    format_pct,
    format_scaled,
    wrap_label,
)
from edgar_sec.apps.client.facts import member_display_name
from edgar_sec.apps.client.fiscal import statement_year_classes
from edgar_sec.apps.client.presentation import PresentationView
from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    CashRollforwardGraph,
    EquityRollforwardGraph,
    FairValueHierarchyGraph,
    Level3RollforwardGraph,
    PensionFundedStatusGraph,
    SegmentBreakdownGraph,
)
from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementGraph,
    StatementNode,
)


def ordered_statement_nodes(
    graph: StatementGraph, view: str = "standard"
) -> list[tuple[StatementNode, int]]:
    """Statement nodes in table order: post-order, summary-filtered on request."""
    if not graph.root:
        return []
    visited: set[str] = set()
    ordered: list[tuple[StatementNode, int]] = []

    def _traverse(node: StatementNode, depth: int) -> None:
        if node.concept_qname in visited:
            return
        visited.add(node.concept_qname)
        for child in graph.children(node.concept_qname):
            _traverse(child, depth + 1)
        ordered.append((node, depth))

    _traverse(graph.root, 0)
    if view == "summary":
        ordered = [
            (n, d) for n, d in ordered if d <= 1 or n.concept_qname == graph.root_qname
        ]
    return ordered


def statement_year_headers(graph: StatementGraph, years: list[str]) -> list[str]:
    """Year column headers, naming the span class when it is not annual.

    A year served from a non-annual span reads "FY <year> (<class>)";
    annual and instant years keep the bare "FY <year>" form.
    """
    classes = statement_year_classes(graph)
    headers: list[str] = []
    for year in years:
        cls = classes.get(year)
        if cls is not None and cls not in ("ANNUAL", "INSTANT"):
            headers.append(f"FY {year} ({cls})")
        else:
            headers.append(f"FY {year}")
    return headers


def render_statement_table(
    graph: StatementGraph,
    view: str = "standard",
    *,
    scaled: bool = True,
    header: str | None = None,
) -> str:
    """Render statement as a multi-column accounting table with side-by-side years."""
    if not graph.root:
        return f"[{graph.statement_type.upper()}: (empty)]"

    years = sorted(graph.years)
    ordered_nodes = ordered_statement_nodes(graph, view)
    divisor, scale_label = (
        choose_scale(node.values.get(y) for node, _ in ordered_nodes for y in years)
        if scaled
        else (1.0, None)
    )

    col_widths = [42] + [18] * len(years) + [12]
    headers = ["Financial Concept"] + statement_year_headers(graph, years) + ["YoY (%)"]
    sep = "=" * (sum(col_widths) + len(col_widths) * 2)
    sub_sep = "-" * (sum(col_widths) + len(col_widths) * 2)

    lines: list[str] = []
    if header:
        lines.append(header)
    lines.append(f"[{graph.statement_type.upper()}]")
    if scale_label:
        lines.append(f"(in {scale_label})")
    lines.extend(
        [
            sep,
            "  ".join(
                h.ljust(col_widths[i]) if i == 0 else h.rjust(col_widths[i])
                for i, h in enumerate(headers)
            ),
            sub_sep,
        ]
    )

    blank_cells = [" " * w for w in col_widths[1:]]
    for node, depth in ordered_nodes:
        indent = "  " * depth
        label = display_label(node.label, node.concept_qname)
        if view == "detailed":
            label = f"{label} [{node.concept_qname}]"
        segments = wrap_label(label, col_widths[0] - len(indent))
        val_cells = [
            format_scaled(node.values.get(y), divisor).rjust(col_widths[i + 1])
            for i, y in enumerate(years)
        ]
        pct_cell = format_pct(node.yoy_pct).rjust(col_widths[-1])
        lines.append(
            "  ".join(
                [(indent + segments[0]).ljust(col_widths[0])] + val_cells + [pct_cell]
            )
        )
        for segment in segments[1:]:
            lines.append(
                "  ".join([(indent + segment).ljust(col_widths[0])] + blank_cells)
            )

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
                cell = format_cell(val).rjust(col_w_data)
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
            f"{indent}{sign} {display_label(node.label, node.concept_qname)} "
            f"[{node.concept_qname}]: {val_str}{yoy_info}"
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


def render_cash_rollforward_ascii(graph: CashRollforwardGraph) -> str:
    """Render ASCII summary of the cash rollforward and its two checks."""
    lines = [
        "[CASH ROLLFORWARD (ASU 2016-18)]",
        f"  Beginning ({graph.beginning_date or '-'}):  {f'${graph.beginning:,.0f}' if graph.beginning is not None else 'None'}",
        f"  Net Change:             {f'${graph.net_change:,.0f}' if graph.net_change is not None else 'None'}",
        f"  End ({graph.end_date or '-'}):        {f'${graph.end:,.0f}' if graph.end is not None else 'None'}",
        f"  Rollforward Verified:   {graph.rollforward_verified}",
        f"  Balance-Sheet Lines:    {f'${graph.balance_sheet_total:,.0f}' if graph.balance_sheet_total is not None else 'None'}",
        f"  Balance-Sheet Verified: {graph.balance_sheet_verified}",
    ]
    if graph.components:
        lines.append("  Components:")
        for node in graph.components:
            val = f"${node.value:,.0f}" if node.value is not None else "None"
            label = display_label(node.label, node.concept_qname)
            lines.append(f"    - {label}: {val}")
    return "\n".join(lines)


def cash_rollforward_to_dataframe(graph: CashRollforwardGraph) -> Any:
    """Export rollforward legs and components to a DataFrame or records."""
    records: list[dict[str, Any]] = [
        {"leg": "beginning", "concept": graph.total_concept, "value": graph.beginning},
        {
            "leg": "net_change",
            "concept": graph.total_concept,
            "value": graph.net_change,
        },
        {"leg": "end", "concept": graph.total_concept, "value": graph.end},
        {
            "leg": "balance_sheet_total",
            "concept": graph.total_concept,
            "value": graph.balance_sheet_total,
        },
    ]
    records.extend(
        {"leg": "component", "concept": node.concept_qname, "value": node.value}
        for node in graph.components
    )
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def render_segment_breakdown_ascii(graph: SegmentBreakdownGraph) -> str:
    """Render ASCII summary of a segment breakdown and its total check."""
    lines = [
        "[SEGMENT BREAKDOWN]",
        f"  Concept:  {graph.concept_qname or 'None'}",
        f"  Axis:     {graph.axis_qname or 'None'}",
        f"  Total:    {f'${graph.total:,.0f}' if graph.total is not None else 'None'}",
        f"  Member Sum: {f'${graph.member_sum:,.0f}' if graph.member_sum is not None else 'None'}",
        f"  Verified: {graph.verified}",
        f"  Discrepancy: {f'${graph.discrepancy:,.0f}' if graph.discrepancy is not None else 'None'}",
    ]
    if graph.members:
        lines.append("  Members:")
        for member in graph.members:
            lines.append(f"    - {member.label}: ${member.value:,.0f}")
    return "\n".join(lines)


def segment_breakdown_to_dataframe(graph: SegmentBreakdownGraph) -> Any:
    """Export segment members and the reported total to a DataFrame."""
    records: list[dict[str, Any]] = [
        {
            "member": member.member_qname,
            "label": member.label,
            "value": member.value,
            "concept": graph.concept_qname,
            "axis": graph.axis_qname,
        }
        for member in graph.members
    ]
    records.append(
        {
            "member": None,
            "label": "total",
            "value": graph.total,
            "concept": graph.concept_qname,
            "axis": graph.axis_qname,
        }
    )
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def statement_to_dataframe(graph: StatementGraph, include_yoy: bool = True) -> Any:
    """Export statement nodes and multi-year series to a DataFrame."""
    # Table order, not graph.nodes order: node insertion follows set
    # iteration in the graph builder, which varies across processes.
    ordered = ordered_statement_nodes(graph)
    seen = {node.concept_qname for node, _ in ordered}
    nodes = [node for node, _ in ordered]
    nodes.extend(
        graph.nodes[qname] for qname in sorted(graph.nodes) if qname not in seen
    )
    records: list[dict[str, Any]] = []
    for node in nodes:
        rec: dict[str, Any] = {
            "concept": node.concept_qname,
            "label": display_label(node.label, node.concept_qname),
            "weight": node.weight,
            "depth": node.depth,
            "value": node.value,
            "basis": node.basis,
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
            "label": display_label(pos.label, pos.concept_qname),
            "value": pos.value,
            "head": pos.atom.head,
            "modifiers": sorted(pos.atom.modifiers),
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
            "label": display_label(pos.label, pos.concept_qname),
            "value": pos.value,
            "head": pos.atom.head,
            "modifiers": sorted(pos.atom.modifiers),
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


def render_level3_rollforward_ascii(graph: Level3RollforwardGraph) -> str:
    """Render ASCII summary of a Level-3 rollforward and its checks."""
    lines = [
        "[LEVEL-3 ROLLFORWARD (ASC 820)]",
        f"  Class:    {class_display(graph.dimensions)}",
        f"  Opening ({graph.start_date or '-'}):  {f'${graph.opening:,.0f}' if graph.opening is not None else 'None'}",
        f"  Closing ({graph.end_date or '-'}):  {f'${graph.closing:,.0f}' if graph.closing is not None else 'None'}",
        f"  Total Gains: {f'${graph.total_gains:,.0f}' if graph.total_gains is not None else 'None'}",
        f"  Purchases:   {f'${graph.purchases:,.0f}' if graph.purchases is not None else 'None'}",
        f"  Sales:       {f'${graph.sales:,.0f}' if graph.sales is not None else 'None'}",
        f"  Issues:      {f'${graph.issues:,.0f}' if graph.issues is not None else 'None'}",
        f"  Settlements: {f'${graph.settlements:,.0f}' if graph.settlements is not None else 'None'}",
        f"  Verified: {graph.verified}",
        f"  Discrepancy: {f'${graph.discrepancy:,.0f}' if graph.discrepancy is not None else 'None'}",
    ]
    if graph.missing_components:
        lines.append(f"  Missing: {', '.join(graph.missing_components)}")
    return "\n".join(lines)


def level3_rollforward_to_dataframe(graph: Level3RollforwardGraph) -> Any:
    """Export rollforward legs to a DataFrame or records."""
    legs = (
        ("opening", graph.opening),
        ("gains_earnings", graph.gains_earnings),
        ("gains_oci", graph.gains_oci),
        ("purchases", graph.purchases),
        ("sales", graph.sales),
        ("issues", graph.issues),
        ("settlements", graph.settlements),
        ("transfers_in", graph.transfers_in),
        ("transfers_out", graph.transfers_out),
        ("transfers_net", graph.transfers_net),
        ("net_change", graph.net_change),
        ("closing", graph.closing),
    )
    records: list[dict[str, Any]] = [
        {
            "leg": leg,
            "value": value,
            "concept": graph.balance_concept,
            "dimensions": graph.dimensions,
        }
        for leg, value in legs
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


def render_pension_funded_status_ascii(graph: PensionFundedStatusGraph) -> str:
    """Render ASCII summary of a pension funded status and its checks."""
    assets, obligation = graph.plan_assets, graph.obligation
    lines = [
        "[PENSION FUNDED STATUS (ASC 715)]",
        f"  Class:    {class_display(graph.dimensions)}",
        f"  Plan Assets: {f'${assets.opening:,.0f}' if assets.opening is not None else 'None'}"
        f" -> {f'${assets.closing:,.0f}' if assets.closing is not None else 'None'}"
        f"  Verified: {assets.verified}",
        f"  Obligation:  {f'${obligation.opening:,.0f}' if obligation.opening is not None else 'None'}"
        f" -> {f'${obligation.closing:,.0f}' if obligation.closing is not None else 'None'}"
        f"  Verified: {obligation.verified}",
        f"  Funded Status: {f'${graph.funded_status:,.0f}' if graph.funded_status is not None else 'None'}"
        f"  Filed: {f'${graph.funded_status_filed:,.0f}' if graph.funded_status_filed is not None else 'None'}"
        f"  Verified: {graph.funded_verified}",
    ]
    if graph.missing_components:
        lines.append(f"  Missing: {', '.join(graph.missing_components)}")
    return "\n".join(lines)


def render_equity_rollforward_ascii(graph: EquityRollforwardGraph) -> str:
    """Render ASCII summary of the equity rollforward and its checks."""
    lines = [
        "[EQUITY ROLLFORWARD (STATEMENT OF CHANGES IN EQUITY)]",
        f"  Total: {f'${graph.opening:,.0f}' if graph.opening is not None else 'None'}"
        f" -> {f'${graph.closing:,.0f}' if graph.closing is not None else 'None'}"
        f"  Verified: {graph.verified}",
        f"  Components Sum: {f'${graph.components_sum:,.0f}' if graph.components_sum is not None else 'None'}"
        f"  Verified: {graph.components_verified}",
    ]
    for comp in graph.components:
        lines.append(
            f"  {member_display_name(comp.member_qname)}: "
            f"{f'${comp.opening:,.0f}' if comp.opening is not None else 'None'}"
            f" -> {f'${comp.closing:,.0f}' if comp.closing is not None else 'None'}"
            f"  Verified: {comp.verified}"
        )
    if graph.missing_components:
        lines.append(f"  Missing: {', '.join(graph.missing_components)}")
    return "\n".join(lines)


def equity_rollforward_to_dataframe(graph: EquityRollforwardGraph) -> Any:
    """Export each component's legs and the total rollforward to a DataFrame."""
    records: list[dict[str, Any]] = []
    for comp in graph.components:
        records.append(
            {"component": comp.member_qname, "leg": "opening", "value": comp.opening}
        )
        for role, value in comp.movements.items():
            records.append(
                {"component": comp.member_qname, "leg": role, "value": value}
            )
        records.append(
            {"component": comp.member_qname, "leg": "closing", "value": comp.closing}
        )
    records.append({"component": None, "leg": "opening_total", "value": graph.opening})
    records.append({"component": None, "leg": "closing_total", "value": graph.closing})
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def pension_funded_status_to_dataframe(graph: PensionFundedStatusGraph) -> Any:
    """Export both rollforwards' legs and the funded status to a DataFrame."""
    records: list[dict[str, Any]] = []
    for side_name, side in (
        ("plan_assets", graph.plan_assets),
        ("obligation", graph.obligation),
    ):
        records.append({"side": side_name, "leg": "opening", "value": side.opening})
        for role, value in side.movements.items():
            records.append({"side": side_name, "leg": role, "value": value})
        records.append({"side": side_name, "leg": "closing", "value": side.closing})
    records.append(
        {"side": "funded_status", "leg": "computed", "value": graph.funded_status}
    )
    records.append(
        {
            "side": "funded_status",
            "leg": "filed",
            "value": graph.funded_status_filed,
        }
    )
    try:
        import polars as pl

        return pl.DataFrame(records)
    except ImportError:
        try:
            import pandas as pd

            return pd.DataFrame(records)
        except ImportError:
            return records


def render_fair_value_hierarchy_ascii(graph: FairValueHierarchyGraph) -> str:
    """Render ASCII summary of the hierarchy rows and their checks."""
    lines = [
        "[FAIR VALUE HIERARCHY (ASC 820)]",
        f"  Axis:     {graph.axis_qname or 'None'}",
        f"  Rows:     {len(graph.rows)}",
        f"  Verified: {len(graph.verified_rows)}",
    ]
    for row in graph.rows:
        label = display_label(row.label, row.concept_qname)
        lines.append(f"  - {label} ({row.instant_date or '-'}):")
        for member, value in row.levels.items():
            lines.append(f"      {member_display_name(member)}: {format_cell(value)}")
        lines.append(
            f"      Sum: {format_cell(row.levels_sum)}  "
            f"Total: {format_cell(row.total)}  Verified: {row.verified}  "
            f"L3 Tied: {row.l3_tied}"
        )
    return "\n".join(lines)


def presentation_to_dataframe(view: PresentationView) -> Any:
    """Export presentation rows with period, dimension, and parent columns."""
    axes = sorted({axis for row in view.rows for axis, _ in row.dimensions})
    records: list[dict[str, Any]] = []
    for row in view.rows:
        rec: dict[str, Any] = {"label": row.label, "concept": row.concept}
        for period in view.periods:
            rec[period] = row.values.get(period)
        members = dict(row.dimensions)
        for axis in axes:
            member = members.get(axis)
            rec[axis] = (
                member_display_name(member, view.labels) if member is not None else None
            )
        rec["presentation_parent"] = row.presentation_parent
        rec["calculation_parent"] = row.calculation_parent
        records.append(rec)
    columns = [
        "label",
        "concept",
        *view.periods,
        *axes,
        "presentation_parent",
        "calculation_parent",
    ]
    if records:
        try:
            import polars as pl

            return pl.DataFrame(records)
        except ImportError:
            pass
    try:
        import pandas as pd

        return pd.DataFrame(records, columns=columns)
    except ImportError:
        return records


def render_presentation_ascii(view: PresentationView, *, scaled: bool = True) -> str:
    """Render presentation rows as an ASCII statement table."""
    if not view.rows:
        return f"[{view.title.upper()} ({view.mode.upper()}): (empty)]"
    periods = list(view.periods)
    divisor, scale_label = (
        choose_scale(
            value
            for row in view.rows
            for value in row.values.values()
            if isinstance(value, (int, float))
        )
        if scaled
        else (1.0, None)
    )
    col_widths = [42] + [18] * len(periods)
    sep = "=" * (sum(col_widths) + len(col_widths) * 2)
    sub_sep = "-" * (sum(col_widths) + len(col_widths) * 2)
    headers = ["Financial Concept"] + periods
    lines: list[str] = []
    if view.header:
        lines.append(view.header)
    lines.append(f"[{view.title.upper()} — {view.mode.upper()}]")
    if scale_label:
        lines.append(f"(in {scale_label})")
    lines.extend(
        [
            sep,
            "  ".join(
                h.ljust(col_widths[i]) if i == 0 else h.rjust(col_widths[i])
                for i, h in enumerate(headers)
            ),
            sub_sep,
        ]
    )
    blank_cells = [" " * w for w in col_widths[1:]]
    for row in view.rows:
        indent = "  " * row.depth
        segments = wrap_label(row.label, col_widths[0] - len(indent))
        cells = []
        for i, period in enumerate(periods):
            value = row.values.get(period)
            if isinstance(value, (int, float)):
                cell = format_scaled(value, divisor)
            else:
                cell = str(value) if value is not None else "-"
            cells.append(cell.rjust(col_widths[i + 1]))
        line = "  ".join([(indent + segments[0]).ljust(col_widths[0]), *cells])
        if row.dimensions:
            line = f"{line}  [{class_display(row.dimensions)}]"
        lines.append(line)
        for segment in segments[1:]:
            lines.append(
                "  ".join([(indent + segment).ljust(col_widths[0]), *blank_cells])
            )
    lines.append(sep)
    return "\n".join(lines)


def fair_value_hierarchy_to_dataframe(graph: FairValueHierarchyGraph) -> Any:
    """Export hierarchy rows and their checks to a DataFrame."""
    records: list[dict[str, Any]] = [
        {
            "concept": row.concept_qname,
            "label": display_label(row.label, row.concept_qname),
            "instant_date": row.instant_date,
            "unit": row.unit,
            "frequency_member": row.frequency_member,
            "dimensions": row.dimensions,
            "level1": row.level1,
            "level2": row.level2,
            "level3": row.level3,
            "nav": row.nav,
            "levels_sum": row.levels_sum,
            "total": row.total,
            "verified": row.verified,
            "l3_tied": row.l3_tied,
        }
        for row in graph.rows
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
