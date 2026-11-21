"""Placement slices: statement roots derived from coordinate patterns."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.engine.xbrl.discovery.placement_slices import placement_slices
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _arcs(*edges: tuple[str, str]) -> pa.Table:
    """Build a minimal presentation-arcs table from parent/child pairs."""
    return pa.table(
        {
            "parent_qname": [parent for parent, _ in edges],
            "child_qname": [child for _, child in edges],
        }
    )


def _role_arcs(*edges: tuple[str, str, str]) -> pa.Table:
    """Build a presentation-arcs table with a role per edge."""
    return pa.table(
        {
            "parent_qname": [parent for _, parent, _ in edges],
            "child_qname": [child for _, _, child in edges],
            "role_uri": [role for role, _, _ in edges],
        }
    )


def test_statement_roots_are_derived_not_named() -> None:
    """Roots classify by pattern; slices propagate and roots are excluded."""
    lexicon = load_domain_taxonomy().token_lexicon
    assert lexicon is not None
    arcs = _arcs(
        ("us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:Assets"),
        ("us-gaap:Assets", "us-gaap:AssetsCurrent"),
        ("dei:CoverAbstract", "dei:EntityCommonStockSharesOutstanding"),
        ("us-gaap:SomeScheduleAbstract", "us-gaap:SomeDetail"),
    )

    slices = placement_slices(arcs, lexicon)

    assert slices["us-gaap:Assets"] == {"BalanceSheet"}
    assert slices["us-gaap:AssetsCurrent"] == {"BalanceSheet"}
    assert slices["dei:EntityCommonStockSharesOutstanding"] == {"Cover"}
    assert "us-gaap:SomeDetail" not in slices
    assert "us-gaap:StatementOfFinancialPositionAbstract" not in slices


def test_roles_seed_roots_suppressed_in_the_merged_graph() -> None:
    """A root that is a child in another role still seeds its own role."""
    lexicon = load_domain_taxonomy().token_lexicon
    assert lexicon is not None
    arcs = _role_arcs(
        (
            "role:schedule",
            "us-gaap:SomeScheduleAbstract",
            "us-gaap:StatementOfFinancialPositionAbstract",
        ),
        ("role:face", "us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:Assets"),
    )

    slices = placement_slices(arcs, lexicon)

    assert slices["us-gaap:Assets"] == {"BalanceSheet"}


def test_slices_never_cross_roles_through_shared_concepts() -> None:
    """A concept placed in two roles keeps only its own roles' slices."""
    lexicon = load_domain_taxonomy().token_lexicon
    assert lexicon is not None
    arcs = _role_arcs(
        ("role:income", "us-gaap:IncomeStatementAbstract", "us-gaap:NetIncomeLoss"),
        ("role:detail", "us-gaap:NetIncomeLoss", "us-gaap:SomeDetail"),
    )

    slices = placement_slices(arcs, lexicon)

    assert slices["us-gaap:NetIncomeLoss"] == {"IncomeStatement"}
    assert "us-gaap:SomeDetail" not in slices


def test_missing_or_malformed_arcs_yield_no_slices() -> None:
    """No arcs (or no parent column) means no placement evidence."""
    lexicon = load_domain_taxonomy().token_lexicon
    assert lexicon is not None

    assert placement_slices(None, lexicon) == {}
    assert placement_slices(pa.table({"child_qname": []}), lexicon) == {}
