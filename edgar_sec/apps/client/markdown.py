"""Markdown export for statement, presentation, and comparison views.

Pipe tables carry the same scaled values, units notes, and filing
headers as the ASCII renders; formatting is display-only throughout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.apps.client.display import (
    choose_scale,
    display_label,
    format_cell,
    format_pct,
    format_scaled,
)
from edgar_sec.apps.client.facts import member_display_name
from edgar_sec.apps.client.presentation import PresentationView
from edgar_sec.apps.client.rendering import (
    ordered_statement_nodes,
    statement_year_headers,
)
from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case
from edgar_sec.engine.xbrl.schema.models import qname_local
from edgar_sec.engine.xbrl.solve.statement import StatementGraph


def _md(text: str) -> str:
    """Escape a cell's pipe characters for a markdown pipe table."""
    return text.replace("|", "\\|")


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(_md(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_md(c) for c in row) + " |" for row in rows)
    return lines


def statement_to_markdown(
    graph: StatementGraph,
    view: str = "standard",
    *,
    scaled: bool = True,
    header: str | None = None,
) -> str:
    """Render a calc statement graph as a markdown pipe table."""
    if not graph.root:
        return f"[{graph.statement_type.upper()}: (empty)]"
    years = sorted(graph.years)
    ordered = ordered_statement_nodes(graph, view)
    divisor, scale_label = (
        choose_scale(node.values.get(y) for node, _ in ordered for y in years)
        if scaled
        else (1.0, None)
    )
    lines: list[str] = []
    if header:
        lines.append(header)
    lines.append(f"[{graph.statement_type.upper()}]")
    if scale_label:
        lines.append(f"(in {scale_label})")
    lines.append("")
    rows: list[list[str]] = []
    for node, depth in ordered:
        label = display_label(node.label, node.concept_qname)
        if view == "detailed":
            label = f"{label} [{node.concept_qname}]"
        rows.append(
            ["  " * depth + label]
            + [format_scaled(node.values.get(y), divisor) for y in years]
            + [format_pct(node.yoy_pct)]
        )
    lines.extend(
        _table(
            ["Financial Concept"] + statement_year_headers(graph, years) + ["YoY (%)"],
            rows,
        )
    )
    return "\n".join(lines)


def _axis_header(axis: str) -> str:
    tokens = list(split_camel_case(qname_local(axis)))
    if tokens and tokens[-1] == "Axis":
        tokens.pop()
    return " ".join(tokens)


def presentation_to_markdown(view: PresentationView, *, scaled: bool = True) -> str:
    """Render a presentation view as a markdown pipe table."""
    if not view.rows:
        return f"[{view.title.upper()} ({view.mode.upper()}): (empty)]"
    periods = list(view.periods)
    axes = sorted({axis for row in view.rows for axis, _ in row.dimensions})
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
    lines: list[str] = []
    if view.header:
        lines.append(view.header)
    lines.append(f"[{view.title.upper()} — {view.mode.upper()}]")
    if scale_label:
        lines.append(f"(in {scale_label})")
    lines.append("")
    rows: list[list[str]] = []
    for row in view.rows:
        cells = ["  " * row.depth + row.label, row.concept]
        for period in periods:
            value = row.values.get(period)
            if isinstance(value, (int, float)):
                cells.append(format_scaled(value, divisor))
            else:
                cells.append(str(value) if value is not None else "-")
        members = dict(row.dimensions)
        for axis in axes:
            member = members.get(axis)
            cells.append(
                member_display_name(member, view.labels) if member is not None else ""
            )
        cells.append(row.presentation_parent or "")
        cells.append(row.calculation_parent or "")
        rows.append(cells)
    headers = (
        ["Financial Concept", "Concept"]
        + periods
        + [_axis_header(axis) for axis in axes]
        + ["Presentation Parent", "Calculation Parent"]
    )
    lines.extend(_table(headers, rows))
    return "\n".join(lines)


def comparison_to_markdown(
    cohort_data: Mapping[str, Mapping[str, float | None]],
    metric_labels: Sequence[tuple[str, str]],
) -> str:
    """Render a comparison matrix as a markdown pipe table."""
    companies = list(cohort_data.keys())
    rows: list[list[str]] = []
    for key, label in metric_labels:
        cells = [label]
        for company in companies:
            val = cohort_data[company].get(key)
            if (
                key.endswith("_pct")
                or key.endswith("_margin")
                or key.endswith("_ratio")
            ):
                cells.append(f"{val * 100:.1f}%" if val is not None else "-")
            else:
                cells.append(format_cell(val))
        rows.append(cells)
    return "\n".join(_table(["Metric"] + companies, rows))
