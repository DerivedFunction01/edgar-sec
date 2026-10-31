"""Tests proving subatomic coordinate and topological statement composition."""

from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)


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
        facts = load_seed_facts(seed_folder(firm))
        arcs = load_seed_calculation_arcs(seed_folder(firm))
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


def test_composer_operating_income_requires_a_duration_fact() -> None:
    """Verify an instant-only operating-atom candidate composes nothing."""
    taxonomy = load_domain_taxonomy()
    for firm in ("jnj", "nem"):
        facts = load_seed_facts(seed_folder(firm))
        arcs = load_seed_calculation_arcs(seed_folder(firm))
        composer = StatementComposer(facts, arcs, taxonomy)
        assert composer.compose_income_statement().operating_income is None


def test_composer_gross_profit_parent_guards_abstain_on_all() -> None:
    """Verify the rev/cost-parent heuristic rejects non-face parents."""
    facts = load_seed_facts("all_2022_2022_10k")
    arcs = load_seed_calculation_arcs("all_2022_2022_10k")
    taxonomy = load_domain_taxonomy()

    composer = StatementComposer(facts, arcs, taxonomy)
    assert composer._find_gross_profit_concept() is None
    assert composer.compose_income_statement().gross_profit_graph is None


def test_composer_atom_resolver_supplies_the_atoms() -> None:
    """Verify an injected atom resolver replaces lexicon decomposition."""
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    taxonomy = load_domain_taxonomy()

    composer = StatementComposer(
        facts, arcs, taxonomy, atom_resolver=lambda qname: None
    )
    assert composer.find_income_statement_root() == ""
    assert composer.find_concept_by_atom("H_ASSET") is None
