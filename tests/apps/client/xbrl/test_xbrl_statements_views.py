"""Tests proving statement topic views, fair-value hierarchy, and composer parity."""

from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.xbrl.xbrl_support import _create_xbrl_facade, _sub_root
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)


def test_statements_topic_views_match_financials() -> None:
    """Verify the statements surface serves the topic views identically."""
    xbrl = _create_xbrl_facade("msft")

    derivatives = xbrl.statements.derivatives()
    assert derivatives.gross_assets == xbrl.financials.derivatives.gross_assets
    assert derivatives.gross_assets is not None
    debt = xbrl.statements.debt()
    assert debt.total_debt == xbrl.financials.debt.total_debt
    assert debt.total_debt is not None
    cash = xbrl.statements.cash_rollforward()
    assert cash.end == xbrl.financials.cash_rollforward.end
    assert cash.end is not None


def test_statements_comprehensive_income_and_cover() -> None:
    """Verify the comprehensive-income root and the dei cover facts."""
    xbrl = _create_xbrl_facade("msft")

    comp = xbrl.statements.comprehensive_income_statement()
    assert comp.root is not None
    assert comp.root.concept_qname == "us-gaap:ComprehensiveIncomeNetOfTax"
    assert comp.root.value is not None

    cover = xbrl.statements.cover()
    assert len(cover) > 30
    assert all(fact.concept_qname.split(":")[0] == "dei" for fact in cover)
    assert [fact.concept_qname for fact in cover] == sorted(
        fact.concept_qname for fact in cover
    )


def test_fair_value_hierarchy_verifies_alb_levels() -> None:
    """Verify ALB's AFS split reproduces its filed total on both surfaces."""
    xbrl = _create_xbrl_facade("alb")

    view = xbrl.financials.fair_value_hierarchy(year=2024)
    row = view.row("us-gaap:AvailableForSaleSecuritiesDebtSecurities")
    assert row is not None
    assert row.level1 == 0.0
    assert row.level3 == 313_991_000.0
    assert row.levels_sum == row.total == 313_991_000.0
    assert row.verified is True
    assert xbrl.statements.fair_value_hierarchy(year=2024).rows == view.rows


def test_fair_value_hierarchy_asml_splits_by_frequency() -> None:
    """Verify ASML's recurring derivative split reproduces its filed total."""
    xbrl = _create_xbrl_facade("asml")

    view = xbrl.statements.fair_value_hierarchy(year=2024)
    row = view.row("us-gaap:DerivativeAssets")
    assert row is not None
    assert row.frequency_member == "us-gaap:FairValueMeasurementsRecurringMember"
    assert row.level2 == 96_500_000.0
    assert row.total == 96_500_000.0
    assert row.verified is True


def test_fair_value_hierarchy_aapl_files_no_level3() -> None:
    """Verify AAPL's hierarchy rows carry Levels 1/2 only, as filed."""
    xbrl = _create_xbrl_facade("aapl")

    view = xbrl.financials.fair_value_hierarchy(year=2024)
    assert view.rows
    assert all(row.level3 is None for row in view.rows)
    assert any(row.level2 for row in view.rows)


def test_fair_value_hierarchy_keeps_combined_member_whole() -> None:
    """Verify ALB's combined Level 1/2/3 member stays its own column."""
    xbrl = _create_xbrl_facade("alb")

    view = xbrl.financials.fair_value_hierarchy(year=2024)
    combined = "us-gaap:FairValueInputsLevel12And3Member"
    rows = [row for row in view.rows if combined in row.levels]
    assert rows
    assert any(row.levels[combined] == 78_124_000.0 for row in rows)


def test_fair_value_hierarchy_jpm_level3_ties_to_rollforward() -> None:
    """Verify JPM's Other Assets Level-3 column ties to its rollforward."""
    xbrl = _create_xbrl_facade("jpm")

    view = xbrl.financials.fair_value_hierarchy(year=2024)
    tied = [row for row in view.rows if row.l3_tied is True]
    assert tied
    assert any(row.level3 == 1_344_000_000.0 for row in tied)


def test_facade_surfaces_share_one_kernel_and_composer() -> None:
    """Verify statements and financials share the kernel and its composer."""
    xbrl = _create_xbrl_facade("msft")

    assert xbrl.statements._kernel is xbrl.financials._kernel
    assert xbrl.financials._composer is xbrl.statements._kernel.composer


def test_statements_roots_match_composer_across_seed_fixtures() -> None:
    """Verify statements view roots equal the composer compose roots."""
    taxonomy = load_domain_taxonomy()
    firms = (
        "msft",
        "aapl",
        "jnj",
        "f",
        "jpm",
        "apd",
        "amzn",
        "dis",
        "bmy",
        "xom",
        "nem",
        "all_2022",
    )
    for firm in firms:
        xbrl = _create_xbrl_facade(firm)
        folder = seed_folder(firm)
        composer = StatementComposer(
            load_seed_facts(folder), load_seed_calculation_arcs(folder), taxonomy
        )

        inc = xbrl.statements.income_statement().graph
        comp_inc = composer.compose_income_statement()
        assert inc.root_qname == comp_inc.root_qname
        assert _sub_root(inc.gross_profit_graph) == _sub_root(
            comp_inc.gross_profit_graph
        )
        assert _sub_root(inc.operating_income_graph) == _sub_root(
            comp_inc.operating_income_graph
        )

        bs = xbrl.statements.balance_sheet().graph
        comp_bs = composer.compose_balance_sheet()
        assert bs.root_qname == comp_bs.root_qname
        assert _sub_root(bs.assets_graph) == _sub_root(comp_bs.assets_graph)
        assert _sub_root(bs.liabilities_graph) == _sub_root(comp_bs.liabilities_graph)
        assert _sub_root(bs.equity_graph) == _sub_root(comp_bs.equity_graph)

        cf = xbrl.statements.cash_flow_statement().graph
        comp_cf = composer.compose_cash_flow()
        assert cf.root_qname == comp_cf.root_qname
        assert _sub_root(cf.operating) == _sub_root(comp_cf.operating)
        assert _sub_root(cf.investing) == _sub_root(comp_cf.investing)
        assert _sub_root(cf.financing) == _sub_root(comp_cf.financing)


def test_statements_all_income_abstains_on_gross_and_operating() -> None:
    """Verify ALL's income view carries no discontinued-ops/tax sub-graphs."""
    xbrl = _create_xbrl_facade("all_2022")

    graph = xbrl.statements.income_statement().graph
    assert graph.gross_profit_graph is None
    assert graph.operating_income_graph is None
    assert xbrl.financials.gross_profit is None


def test_statements_bmy_operating_pick_abstains() -> None:
    """Verify BMY's income view carries no operating sub-graph."""
    xbrl = _create_xbrl_facade("bmy")

    graph = xbrl.statements.income_statement().graph
    assert graph.operating_income_graph is None
