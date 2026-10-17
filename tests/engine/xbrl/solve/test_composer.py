"""Tests proving subatomic coordinate and topological statement composition."""

from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts


def test_composer_cash_flow_tripartite_resolution() -> None:
    """Verify tripartite cash flow statement composition and partition linking."""
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    taxonomy = load_domain_taxonomy()

    composer = StatementComposer(facts, arcs, taxonomy)
    cf_graph = composer.compose_cash_flow()

    assert cf_graph.root is not None
    assert cf_graph.operating is not None
    assert cf_graph.operating.root is not None
    assert cf_graph.investing is not None
    assert cf_graph.financing is not None

    assert cf_graph.cfo == 118548000000.0
    assert cf_graph.cfi == -96970000000.0
    assert cf_graph.cff == -37757000000.0
    assert cf_graph.net_core_cash_flow == -16179000000.0


def test_composer_balance_sheet_and_income_statement() -> None:
    """Verify balance sheet equation and income statement dynamic composition."""
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    taxonomy = load_domain_taxonomy()

    composer = StatementComposer(facts, arcs, taxonomy)
    bs = composer.compose_balance_sheet()

    assert bs.root is not None
    assert bs.assets_graph is not None
    assert bs.liabilities_graph is not None
    assert bs.equity_graph is not None
    assert bs.total_assets == 512163000000.0
    assert bs.is_balanced

    inc = composer.compose_income_statement()
    assert inc.root is not None
    assert inc.root.value == 88136000000.0
    assert inc.gross_profit_graph is not None
    assert inc.gross_profit_graph.root is not None
    assert inc.gross_profit_graph.root.value == 171008000000.0
    assert inc.operating_income_graph is not None
    assert inc.operating_income_graph.root is not None
    assert inc.operating_income_graph.root.value == 109433000000.0


def test_composer_across_all_8_fixtures() -> None:
    """Prove dynamic root resolution and composition across all 8 ground fixtures."""
    firms = ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis")
    taxonomy = load_domain_taxonomy()

    for firm in firms:
        facts = load_seed_facts(f"{firm}_2024_10k")
        arcs = load_seed_calculation_arcs(f"{firm}_2024_10k")
        composer = StatementComposer(facts, arcs, taxonomy)

        bs = composer.compose_balance_sheet()
        assert bs.root is not None
        assert bs.total_assets is not None and bs.total_assets > 0

        inc = composer.compose_income_statement()
        assert inc.root is not None
        assert inc.root.value is not None

        cf = composer.compose_cash_flow()
        assert cf.root is not None
        assert cf.cfo is not None and abs(cf.cfo) > 0
