"""Memoization and shared-state tests for the per-filing kernel."""

from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.solve.scoping import FilingRef, build_lineages
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


def test_kernel_filed_metadata_reads_the_dei_block() -> None:
    """The kernel exposes the seed filing's filed dei period/fiscal block."""
    kernel = _facade("msft")._kernel
    meta = kernel.filed_metadata
    assert meta.period_end == "2024-06-30"
    assert meta.fiscal_year == 2024
    assert meta.period_focus == "FY"
    assert meta.document_type == "10-K"
    assert meta.fiscal_year_end == (6, 30)
    assert meta.annual_report is True
    assert kernel.filed_metadata is meta


_ORIGINAL = "0000000001-24-000001"
_AMENDMENT = "0000000001-24-000002"


def _pooled_fact(accession: str, qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(accession),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )


def _pooled_kernel() -> FilingKernel:
    pool = (
        _pooled_fact(_ORIGINAL, "us-gaap:Revenues", 100.0),
        _pooled_fact(_ORIGINAL, "us-gaap:IncomeLoss", 40.0),
        _pooled_fact(_AMENDMENT, "us-gaap:Revenues", 120.0),
    )
    refs = (
        FilingRef(
            accession=_ORIGINAL,
            cik="0000000001",
            form="10-K",
            report_period="2024-12-31",
        ),
        FilingRef(
            accession=_AMENDMENT,
            cik="0000000001",
            form="10-K/A",
            report_period="2024-12-31",
        ),
    )
    return FilingKernel(
        pool,
        (),
        load_domain_taxonomy(),
        accession=_AMENDMENT,
        lineages=build_lineages(refs),
        fact_pool=pool,
    )


def test_kernel_serves_superseded_pool_by_default() -> None:
    """Restated keys answer from the amendment; untouched originals stand."""
    kernel = _pooled_kernel()
    served = {
        fact.concept_qname: (fact.value, str(fact.accession)) for fact in kernel.facts
    }
    assert served == {
        "us-gaap:Revenues": (120.0, _AMENDMENT),
        "us-gaap:IncomeLoss": (40.0, _ORIGINAL),
    }
    assert len(kernel.fact_pool) == 3
    lineage = kernel.lineage
    assert lineage is not None
    assert (lineage.original, lineage.latest) == (_ORIGINAL, _AMENDMENT)


def test_kernel_explicit_accession_scope_reaches_the_original() -> None:
    """Explicit accession scope returns the filing as filed, unrestated."""
    kernel = _pooled_kernel()
    original = kernel.facts_for_accession(_ORIGINAL)
    assert {fact.concept_qname: fact.value for fact in original} == {
        "us-gaap:Revenues": 100.0,
        "us-gaap:IncomeLoss": 40.0,
    }
    amendment = kernel.facts_for_accession(_AMENDMENT)
    assert [fact.value for fact in amendment] == [120.0]


def test_kernel_without_lineages_serves_facts_unchanged() -> None:
    """A kernel with no lineage supplied is the identity over its facts."""
    facts = (_pooled_fact(_ORIGINAL, "us-gaap:Revenues", 100.0),)
    kernel = FilingKernel(facts, (), load_domain_taxonomy(), accession=_ORIGINAL)
    assert kernel.facts == facts
    assert kernel.fact_pool == facts
    assert kernel.lineage is None
