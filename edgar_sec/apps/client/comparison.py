"""Cross-company and multi-year comparison over subatomic coordinate subspaces."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from edgar_sec.apps.client.markdown import comparison_to_markdown
from edgar_sec.apps.client.rendering import render_comparison_table
from edgar_sec.engine.xbrl.solve.query import QueryStatus

if TYPE_CHECKING:
    from edgar_sec.infra.storage.corpus_index import CorpusIndex


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

    def to_markdown(self) -> str:
        """Render the comparison matrix as a markdown pipe table."""
        return comparison_to_markdown(self.cohort_data, self.metric_labels)

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


@dataclass(frozen=True, slots=True)
class PanelRow:
    """One filer's panel answer: its status and value, kept even when unanswered."""

    filer: str
    status: QueryStatus
    value: float | None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PanelResult:
    """A term answered across a filer panel, with completeness accounting."""

    term: str
    rows: tuple[PanelRow, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        """Filers whose row carries no value."""
        return tuple(row.filer for row in self.rows if row.value is None)

    @property
    def total(self) -> float:
        """Sum of the answered rows' values."""
        return sum(row.value for row in self.rows if row.value is not None)


def _filing_year(facade: Any) -> int | None:
    counts = Counter(
        fact.instant_date
        for fact in facade.facts
        if not fact.dimensions and fact.instant_date
    )
    if not counts:
        return None
    return int(counts.most_common(1)[0][0][:4])


def panel_query(
    facades: Mapping[str, Any],
    term: str,
    *,
    fiscal_year: int | None = None,
    dimension_policy: str | None = None,
) -> PanelResult:
    """Answer one term for every facade: one row per filer, none dropped.

    fiscal_year applies to all filers; when omitted, each filer's own balance-sheet year is used.
    """
    rows = []
    for filer, facade in facades.items():
        year = fiscal_year if fiscal_year is not None else _filing_year(facade)
        result = facade.query(term, fiscal_year=year, dimension_policy=dimension_policy)
        rows.append(
            PanelRow(
                filer=filer,
                status=result.status,
                value=result.value,
                candidates=result.candidate_qnames,
            )
        )
    return PanelResult(term=term, rows=tuple(rows))


def _metric_specs(
    metrics: Sequence[str | SubspaceMetric] | None,
) -> list[SubspaceMetric]:
    """Resolve metric keys and specs to the canonical metric definitions."""
    if metrics is None:
        return list(DEFAULT_METRICS)
    specs: list[SubspaceMetric] = []
    metric_map = {m.key: m for m in DEFAULT_METRICS}
    for m in metrics:
        if isinstance(m, SubspaceMetric):
            specs.append(m)
        elif m in metric_map:
            specs.append(metric_map[m])
        else:
            specs.append(SubspaceMetric(m, m.replace("_", " ").title(), "H_INCOME"))
    return specs


def screen_filings(
    index: CorpusIndex,
    metrics: Sequence[str | SubspaceMetric] | None = None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Candidate filings per metric, screened against the corpus index.

    A filing is listed when an index row sits at the metric's head with
    modifiers covering the metric's; materializing it decides the value.
    """
    screened: dict[str, tuple[tuple[str, str], ...]] = {}
    for spec in _metric_specs(metrics):
        rows = index.rows_at_coordinate(spec.head, tuple(sorted(spec.modifiers)))
        screened[spec.key] = tuple(sorted({(row.cik, row.accession) for row in rows}))
    return screened


def screen_peers(
    index: CorpusIndex, cik: str, accession: str
) -> tuple[tuple[str, str], ...]:
    """Filings sharing at least one exact coordinate with one filing."""
    return index.peer_filings(cik, accession)


def compare_companies(
    companies: Sequence[Any],
    metrics: Sequence[str | SubspaceMetric] | None = None,
    year: int | str | None = None,
) -> ComparisonView:
    """Compare multiple XBRL filings across canonical coordinate subspaces and margins."""
    specs = _metric_specs(metrics)

    standard = {m.key: m for m in DEFAULT_METRICS}
    needed: dict[str, SubspaceMetric] = {}
    for s in specs:
        needed.setdefault(s.key, standard.get(s.key, s))
    for _key, _label, numerator, denominator in DERIVED_MARGINS:
        for dep in (numerator, denominator):
            needed.setdefault(dep, standard[dep])

    cohort_data: dict[str, dict[str, float | None]] = {}
    for comp in companies:
        entity_name = _entity_name(comp, len(cohort_data))

        fin = comp.financials
        c_data: dict[str, float | None] = {}
        for key, spec in needed.items():
            c_data[key] = _resolve_metric(fin, spec, year)

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
