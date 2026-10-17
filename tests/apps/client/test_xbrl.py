"""Tests proving ergonomic Layer 5 XBRL client facade, statements, and YoY math."""

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts


def _create_xbrl_facade(firm: str) -> Xbrl:
    facts = load_seed_facts(f"{firm}_2024_10k")
    arcs = load_seed_calculation_arcs(f"{firm}_2024_10k")
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_xbrl_facade_facts_query() -> None:
    """Verify fluent fact query filtering, atom resolution, and tabular exports."""
    xbrl = _create_xbrl_facade("msft")

    assert len(xbrl.facts) > 1000
    rev_facts = xbrl.facts.query().atom("H_REVENUE").execute()
    assert len(rev_facts) > 0
    assert any("RevenueFromContractWithCustomer" in f.concept_qname for f in rev_facts)

    concept_facts = (
        xbrl.facts.query()
        .concept("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
        .execute()
    )
    assert len(concept_facts) > 0

    df = rev_facts.to_dataframe()
    assert len(df) == len(rev_facts)
    arrow_tbl = rev_facts.to_arrow()
    assert arrow_tbl.num_rows == len(rev_facts)


def test_xbrl_facade_statements_and_yoy() -> None:
    """Verify multi-year statement views, YoY series, and year filtering."""
    xbrl = _create_xbrl_facade("msft")

    stmt = xbrl.statements.income_statement()
    assert stmt.root is not None
    assert stmt.root.value == 88136000000.0
    assert "2024" in stmt.years
    assert "2023" in stmt.years

    rendered = stmt.render_ascii()
    assert "[INCOME STATEMENT:" in rendered
    assert "$88,136,000,000" in rendered
    assert "YoY:" in rendered

    df = stmt.to_dataframe(include_yoy=True)
    assert len(df) > 0

    stmt_2023 = xbrl.statements.income_statement(year=2023)
    assert stmt_2023.years == ("2023",)
    assert stmt_2023.root is not None
    assert stmt_2023.root.value == 72361000000.0

    bs = xbrl.statements.balance_sheet()
    assert bs.root is not None
    assert bs.root.value == 512163000000.0


def test_xbrl_financials_across_all_8_fixtures() -> None:
    """Prove dynamic subatomic financial metrics across all 8 ground fixtures."""
    firms = ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis")

    for firm in firms:
        xbrl = _create_xbrl_facade(firm)
        fin = xbrl.financials

        assert fin.revenue is not None and fin.revenue > 0
        assert fin.total_assets is not None and fin.total_assets > 0
        assert fin.net_income is not None

        rev_series = fin.revenue_series
        assert len(rev_series) >= 2
        rev_yoy = fin.revenue_yoy
        assert rev_yoy is not None
        assert isinstance(rev_yoy[0], float)

        derivatives = fin.derivatives
        assert derivatives is not None
        d_df = derivatives.to_dataframe()
        assert d_df is not None
        d_ascii = derivatives.render_ascii()
        assert "[DERIVATIVE PORTFOLIO EXPOSURE]" in d_ascii

        debt = fin.debt
        assert debt is not None
        debt_df = debt.to_dataframe()
        assert debt_df is not None
        debt_ascii = debt.render_ascii()
        assert "[DEBT AND CAPITAL STRUCTURE]" in debt_ascii


def test_xbrl_chain_and_graph() -> None:
    """Verify topological rollup chains and arbitrary root graph builds."""
    xbrl = _create_xbrl_facade("msft")

    chain = xbrl.chain(
        child_concept="us-gaap:CostOfGoodsAndServicesSold",
        root_concept="us-gaap:GrossProfit",
    )
    assert len(chain) == 2
    assert chain[0].concept_qname == "us-gaap:CostOfGoodsAndServicesSold"
    assert chain[1].concept_qname == "us-gaap:GrossProfit"

    custom_graph = xbrl.graph("us-gaap:Assets")
    assert custom_graph.root is not None
    assert custom_graph.root.value == 512163000000.0


def test_xbrl_statement_table_and_comparison() -> None:
    """Verify clean accounting table formatting and multi-firm comparison."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")
    jpm = _create_xbrl_facade("jpm")

    inc = aapl.statements.income_statement()
    table_str = inc.render_table()
    assert "[INCOME STATEMENT]" in table_str
    assert "FY 2024" in table_str
    assert "FY 2023" in table_str
    assert "YoY (%)" in table_str
    assert "$391,035,000,000" in table_str
    assert "$93,736,000,000" in table_str
    assert "(+)" not in table_str
    assert str(inc) == table_str

    comp_view = msft.compare([aapl, jpm])
    c_table = comp_view.render_table()
    assert "Revenue" in c_table
    assert "Operating Margin" in c_table
    assert "Net Margin" in c_table
    assert "Return on Assets (ROA)" in c_table

    c_df = comp_view.to_dataframe()
    assert len(c_df) > 0


def test_xbrl_macro_commitments_and_cash_flow() -> None:
    """Verify ASC 606 RPO backlog, Capex, and Free Cash Flow derivation."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")

    assert msft.financials.rpo == 275_000_000_000.0
    assert msft.financials.capex == 44_477_000_000.0
    assert msft.financials.free_cash_flow == 74_071_000_000.0
    assert "2024" in msft.financials.capex_series

    assert aapl.financials.rpo is None
    assert aapl.financials.capex == 9_447_000_000.0
    assert aapl.financials.free_cash_flow == 108_807_000_000.0
