"""Cross-company and multi-year comparison over subatomic coordinate subspaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.apps.client.rendering import render_comparison_table


@dataclass(frozen=True, slots=True)
class SubspaceMetric:
    """Canonical metric definition over subatomic coordinate subspaces."""

    key: str
    label: str
    head: str
    modifiers: frozenset[str] = frozenset()
    is_instant: bool = False


DEFAULT_METRICS: tuple[SubspaceMetric, ...] = (
    SubspaceMetric("revenue", "Revenue", "H_REVENUE"),
    SubspaceMetric("gross_profit", "Gross Profit", "H_INCOME", frozenset({"M_GROSS"})),
    SubspaceMetric(
        "operating_income", "Operating Income", "H_INCOME", frozenset({"M_OPERATING"})
    ),
    SubspaceMetric(
        "net_income", "Net Income", "H_INCOME", frozenset({"M_NET_BOTTOMLINE"})
    ),
    SubspaceMetric(
        "operating_cash_flow",
        "Operating Cash Flow",
        "H_CASH",
        frozenset({"M_OPERATING"}),
    ),
    SubspaceMetric("total_assets", "Total Assets", "H_ASSET", is_instant=True),
    SubspaceMetric(
        "total_debt",
        "Total Debt",
        "H_LIABILITY",
        frozenset({"M_DEBT"}),
        is_instant=True,
    ),
    SubspaceMetric("total_equity", "Total Equity", "H_EQUITY", is_instant=True),
)


class ComparisonView:
    """Tabular and visual comparison presentation across a firm cohort."""

    def __init__(
        self,
        cohort_data: Mapping[str, Mapping[str, float | None]],
        metric_labels: Sequence[tuple[str, str]],
    ) -> None:
        self.cohort_data = dict(cohort_data)
        self.metric_labels = tuple(metric_labels)

    def render_table(self) -> str:
        """Render cross-company comparison table with side-by-side entities and margins."""
        return render_comparison_table(self.cohort_data, self.metric_labels)

    def to_dataframe(self) -> Any:
        """Export comparison matrix to a DataFrame or records."""
        records: list[dict[str, Any]] = []
        for key, label in self.metric_labels:
            rec: dict[str, Any] = {"metric": key, "label": label}
            for comp, data in self.cohort_data.items():
                rec[comp] = data.get(key)
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

    def __str__(self) -> str:
        return self.render_table()

    def __repr__(self) -> str:
        return f"<ComparisonView entities={list(self.cohort_data.keys())} metrics={len(self.metric_labels)}>"


def compare_companies(
    companies: Sequence[Any],
    metrics: Sequence[str | SubspaceMetric] | None = None,
    year: int | str | None = None,
) -> ComparisonView:
    """Compare multiple XBRL filings across canonical coordinate subspaces and margins."""
    specs: list[SubspaceMetric] = []
    if metrics is None:
        specs = list(DEFAULT_METRICS)
    else:
        metric_map = {m.key: m for m in DEFAULT_METRICS}
        for m in metrics:
            if isinstance(m, SubspaceMetric):
                specs.append(m)
            elif m in metric_map:
                specs.append(metric_map[m])
            else:
                specs.append(SubspaceMetric(m, m.replace("_", " ").title(), "H_INCOME"))

    cohort_data: dict[str, dict[str, float | None]] = {}
    for comp in companies:
        entity_name = getattr(comp, "ticker", None) or getattr(
            comp, "company_name", None
        )
        if not entity_name:
            acc = str(getattr(comp, "accession", ""))
            entity_name = acc[:10] if acc else f"Firm_{len(cohort_data) + 1}"

        c_data: dict[str, float | None] = {}
        fin = comp.financials
        c_data["revenue"] = fin.revenue
        c_data["gross_profit"] = fin.gross_profit
        c_data["operating_income"] = fin.operating_income
        c_data["net_income"] = fin.net_income
        c_data["operating_cash_flow"] = fin.operating_cash_flow
        c_data["total_assets"] = fin.total_assets
        c_data["total_debt"] = fin.debt.total_debt
        c_data["total_equity"] = fin.total_equity

        for s in specs:
            if s.key not in c_data:
                c_data[s.key] = fin._scalar(
                    s.head, set(s.modifiers), is_instant=s.is_instant, year=year
                )

        rev = c_data.get("revenue")
        op_inc = c_data.get("operating_income")
        net_inc = c_data.get("net_income")
        assets = c_data.get("total_assets")

        if rev and rev != 0:
            if op_inc is not None:
                c_data["operating_margin"] = op_inc / rev
            if net_inc is not None:
                c_data["net_margin"] = net_inc / rev
        if assets and assets != 0 and net_inc is not None:
            c_data["return_on_assets"] = net_inc / assets

        cohort_data[entity_name] = c_data

    display_labels = [(s.key, s.label) for s in specs]
    display_labels.extend(
        [
            ("operating_margin", "Operating Margin"),
            ("net_margin", "Net Margin"),
            ("return_on_assets", "Return on Assets (ROA)"),
        ]
    )

    return ComparisonView(cohort_data, display_labels)
