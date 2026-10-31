"""Memoization and shared-state tests for the per-filing kernel."""

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)


def _facade(firm: str) -> Xbrl:
    folder = seed_folder(firm)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(calculation_arcs=load_seed_calculation_arcs(folder)),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_kernel_compositions_build_once_and_are_shared() -> None:
    """Both surfaces read the kernel's single composition per statement."""
    xbrl = _facade("msft")
    kernel = xbrl._kernel
    assert kernel.compose_income_statement() is kernel.compose_income_statement()
    assert xbrl.statements.income_statement().graph is kernel.compose_income_statement()
    assert xbrl.statements.balance_sheet().graph is kernel.compose_balance_sheet()
    assert xbrl.statements.cash_flow_statement().graph is kernel.compose_cash_flow()
    _ = (
        xbrl.financials.revenue,
        xbrl.financials.total_assets,
        xbrl.financials.operating_cash_flow,
    )
    assert xbrl.statements.income_statement().graph is kernel.compose_income_statement()


def test_kernel_view_graphs_build_once_and_are_shared() -> None:
    """Topic and rollforward graphs are shared across the two surfaces."""
    xbrl = _facade("msft")
    assert xbrl.financials.debt.graph is xbrl.statements.debt().graph
    assert xbrl.financials.derivatives.graph is xbrl.statements.derivatives().graph
    assert (
        xbrl.financials.cash_rollforward.graph
        is xbrl.statements.cash_rollforward().graph
    )
    assert (
        xbrl.financials.fair_value_hierarchy().graph
        is xbrl.statements.fair_value_hierarchy().graph
    )
    assert (
        xbrl.financials.equity_rollforward().graph
        is xbrl.statements.equity_rollforward().graph
    )


def test_fact_indexes_partition_the_kernel_facts() -> None:
    """Qname and head indexes group every kernel fact exactly once."""
    kernel = _facade("msft")._kernel
    by_qname = kernel.facts_by_qname()
    assert sum(len(facts) for facts in by_qname.values()) == len(kernel.facts)
    assert all(
        fact.concept_qname == qname
        for qname, facts in by_qname.items()
        for fact in facts
    )
    by_head = kernel.facts_by_head()
    assert sum(len(facts) for facts in by_head.values()) == len(kernel.facts)
    revenue = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert all(fact in by_head["H_REVENUE"] for fact in by_qname[revenue])


def test_series_results_are_memoized_and_caller_isolated() -> None:
    """A caller mutating a returned series cannot poison later reads."""
    fin = _facade("msft").financials
    first = fin.revenue_series
    assert first == fin.revenue_series
    first["1900"] = -1.0
    assert "1900" not in fin.revenue_series
    assert fin.revenue == 245_122_000_000.0


def test_second_sweep_recomputes_nothing_and_matches() -> None:
    """A repeated full Financials sweep returns identical values."""
    fin = _facade("msft").financials

    def sweep() -> dict:
        out: dict = {}
        for name in (
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "operating_cash_flow",
            "rpo",
            "capex",
            "free_cash_flow",
            "uncommenced_leases",
            "revenue_series",
            "net_income_series",
            "total_assets_series",
            "revenue_yoy",
            "net_income_yoy",
            "capex_series",
        ):
            out[name] = getattr(fin, name)
        out["derivatives"] = fin.derivatives.render_ascii()
        out["debt"] = fin.debt.render_ascii()
        out["cash_rollforward"] = fin.cash_rollforward.render_ascii()
        out["level3"] = fin.level3_rollforward().render_ascii()
        out["pension"] = fin.pension_funded_status().render_ascii()
        out["equity"] = fin.equity_rollforward().render_ascii()
        out["segment"] = fin.segment_breakdown().render_ascii()
        out["fair_value"] = fin.fair_value_hierarchy().render_ascii()
        return out

    assert sweep() == sweep()


def test_axes_are_memoized() -> None:
    """Xbrl.axes computes the fact-set dimensions once."""
    xbrl = _facade("msft")
    assert xbrl.axes is xbrl.axes
