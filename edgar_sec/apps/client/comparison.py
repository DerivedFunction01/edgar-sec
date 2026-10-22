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

# Metrics produced by statement-graph roots, computed rollups, or the
# debt topic accumulation keep their accessor path as a documented
# delegate (measured per metric over the cohort, Phase 4 Step 4).
METRIC_DELEGATES: dict[str, str] = {
    "gross_profit": "accessor",
    "operating_income": "accessor",
    "net_income": "accessor",
    "total_assets": "accessor",
    "total_equity": "accessor",
    "total_debt": "debt_view",
}

# Derived presets: (key, label, numerator key, denominator key).
DERIVED_MARGINS: tuple[tuple[str, str, str, str], ...] = (
    ("operating_margin", "Operating Margin", "operating_income", "revenue"),
    ("net_margin", "Net Margin", "net_income", "revenue"),
    ("return_on_assets", "Return on Assets (ROA)", "net_income", "total_assets"),
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


def _entity_name(comp: Any, taken: int) -> str:
    """Cohort key for a company: ticker, name, accession prefix, ordinal."""
    entity_name = getattr(comp, "ticker", None) or getattr(comp, "company_name", None)
    if not entity_name:
        acc = str(getattr(comp, "accession", ""))
        entity_name = acc[:10] if acc else f"Firm_{taken + 1}"
    return entity_name


def _resolve_metric(
    fin: Any, spec: SubspaceMetric, year: int | str | None
) -> float | None:
    """Resolve one metric for one company through its adjudicated path."""
    delegate = METRIC_DELEGATES.get(spec.key)
    if delegate == "accessor":
        return getattr(fin, spec.key)
    if delegate == "debt_view":
        return fin.debt.total_debt
    return fin._scalar(
        spec.head, set(spec.modifiers), is_instant=spec.is_instant, year=year
    )


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

    standard = {m.key: m for m in DEFAULT_METRICS}
    cohort_data: dict[str, dict[str, float | None]] = {}
    for comp in companies:
        entity_name = _entity_name(comp, len(cohort_data))

        fin = comp.financials
        c_data: dict[str, float | None] = {}
        for key, spec in standard.items():
            c_data[key] = _resolve_metric(fin, spec, year)
        for s in specs:
            if s.key not in c_data:
                c_data[s.key] = _resolve_metric(fin, s, year)

        for key, _label, numerator, denominator in DERIVED_MARGINS:
            num = c_data.get(numerator)
            den = c_data.get(denominator)
            if num is not None and den and den != 0:
                c_data[key] = num / den

        cohort_data[entity_name] = c_data

    display_labels = [(s.key, s.label) for s in specs]
    display_labels.extend((key, label) for key, label, _n, _d in DERIVED_MARGINS)

    return ComparisonView(cohort_data, display_labels)


def compare_compositions(
    companies: Sequence[Any],
    terms: Sequence[tuple[str, str]],
    *,
    fiscal_year: int | None = None,
    label: str = "Composition",
) -> ComparisonView:
    """Cohort form of Xbrl.compose: one composed value per company."""
    cohort_data: dict[str, dict[str, float | None]] = {}
    for comp in companies:
        entity_name = _entity_name(comp, len(cohort_data))
        result = comp.compose(terms, fiscal_year=fiscal_year)
        cohort_data[entity_name] = {"composition": result.value}
    return ComparisonView(cohort_data, [("composition", label)])
