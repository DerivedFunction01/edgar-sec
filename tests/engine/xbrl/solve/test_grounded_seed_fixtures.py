"""Tests proving grounded seed fixture relationships and verification traces."""

from __future__ import annotations

from tests.engine.xbrl.solve.grounded_seed_support import _verify_fixture


def test_msft_grounded_seed_fixture_verification() -> None:
    """Prove MSFT 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("msft_2024_10k", "MSFT", "0000950170-24-087843")


def test_ko_grounded_seed_fixture_verification() -> None:
    """Prove KO 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("ko_2024_10k", "KO", "0000021344-25-000011")


def test_cat_grounded_seed_fixture_verification() -> None:
    """Prove CAT 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("cat_2024_10k", "CAT", "0000018230-25-000008")


def test_xom_grounded_seed_fixture_verification() -> None:
    """Prove XOM 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("xom_2024_10k", "XOM", "0000034088-25-000010")


def test_dal_grounded_seed_fixture_verification() -> None:
    """Prove DAL 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("dal_2024_10k", "DAL", "0000027904-25-000004")


def test_ba_grounded_seed_fixture_verification() -> None:
    """Prove BA 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("ba_2024_10k", "BA", "0000012927-25-000015")


def test_nem_grounded_seed_fixture_verification() -> None:
    """Prove NEM 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("nem_2024_10k", "NEM", "0001164727-25-000011")


def test_pld_grounded_seed_fixture_verification() -> None:
    """Prove PLD 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("pld_2024_10k", "PLD", "0000950170-25-021272")


def test_aapl_grounded_seed_fixture_verification() -> None:
    """Prove AAPL 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("aapl_2024_10k", "AAPL", "0000320193-24-000123")


def test_jnj_grounded_seed_fixture_verification() -> None:
    """Prove JNJ 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("jnj_2024_10k", "JNJ", "0000200406-25-000038")


def test_ford_grounded_seed_fixture_verification() -> None:
    """Prove Ford 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("f_2024_10k", "F", "0000037996-25-000013")


def test_jpm_grounded_seed_fixture_verification() -> None:
    """Prove JPM 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("jpm_2024_10k", "JPM", "0000019617-25-000270")


def test_apd_grounded_seed_fixture_verification() -> None:
    """Prove APD 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("apd_2024_10k", "APD", "0000002969-24-000056")


def test_amzn_grounded_seed_fixture_verification() -> None:
    """Prove AMZN 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("amzn_2023_10k", "AMZN", "0001018724-24-000008")


def test_dis_grounded_seed_fixture_verification() -> None:
    """Prove DIS 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("dis_2024_10k", "DIS", "0001744489-24-000276")
