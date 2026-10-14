"""Tests for sub-atomic accounting taxonomy and relational schemas."""

from pathlib import Path
import pytest

from edgar_sec.engine.xbrl.domain import (
    DomainTaxonomy,
    PrimeHead,
    SemanticConceptFrame,
    SubatomicModifier,
    TypedRelation,
    load_domain_taxonomy,
    load_prime_heads,
    load_subatomic_modifiers,
    load_typed_relations,
)
from tests.support import fixture_path


def test_load_taxonomy_from_fixtures() -> None:
    """Verify loading taxonomy heads, modifiers, and relations from JSON files."""
    tax_dir = fixture_path("xbrl/taxonomy")
    taxonomy = load_domain_taxonomy(tax_dir)

    assert len(taxonomy.prime_heads) == 15
    assert len(taxonomy.subatomic_modifiers) == 32
    assert len(taxonomy.typed_relations) == 55

    rev = taxonomy.prime_head("H_REVENUE")
    assert rev is not None
    assert rev.head_symbol == "REVENUE"
    assert rev.statement_type == "IncomeStatement"
    assert rev.normal_balance == "CREDIT"
    assert rev.is_dual_role_primitive == 0

    sales = taxonomy.modifier("M_SALES_GOODS")
    assert sales is not None
    assert sales.category == "REVENUE_TYPE"
    assert "Goods" in sales.keywords

    assert taxonomy.prime_head("NON_EXISTENT") is None
    assert taxonomy.modifier("NON_EXISTENT") is None


def test_tuple_conversion_and_concept_frame() -> None:
    """Verify tuple serialisation and semantic frame construction."""
    head = PrimeHead(
        head_id="H_CASH",
        head_symbol="CASH",
        economic_class="FLOW_OR_STOCK_LIQUIDITY",
        statement_type="CashFlow_Or_BalanceSheet",
        normal_balance="DEBIT",
        is_dual_role_primitive=0,
        description="Cash anchor",
    )
    t = head.to_tuple()
    assert t[0] == "H_CASH"
    assert t[1] == "CASH"

    mod = SubatomicModifier(
        modifier_id="M_RD",
        category="EXPENSE_NATURE",
        keywords=("Research", "Development"),
        description="R&D",
    )
    assert mod.to_tuple()[0] == "M_RD"

    rel = TypedRelation(
        edge_id="E01",
        source_node="Sales",
        target_node="Revenues",
        relation_type="IS_A",
        algebraic_weight=1.0,
        sic_scope="ALL",
        description="Sales is part of revenues",
    )
    assert rel.to_tuple()[0] == "E01"

    frame = SemanticConceptFrame(
        qname="us-gaap:ResearchAndDevelopmentExpense",
        prime_head="H_EXPENSE",
        modifiers=("M_RD",),
    )
    assert frame.qname == "us-gaap:ResearchAndDevelopmentExpense"
    assert frame.expected_weight == 1


def test_load_from_csv(tmp_path: Path) -> None:
    """Verify loading prime heads and modifiers from CSV format."""
    csv_heads = tmp_path / "prime_heads.csv"
    csv_heads.write_text(
        "head_id,head_symbol,economic_class,statement_type,normal_balance,is_dual_role_primitive,description\n"
        "H_REVENUE,REVENUE,FLOW_INFLOW,IncomeStatement,CREDIT,0,Top line\n",
        encoding="utf-8",
    )
    heads = load_prime_heads(csv_heads)
    assert len(heads) == 1
    assert heads[0].head_id == "H_REVENUE"

    csv_mods = tmp_path / "subatomic_modifiers.csv"
    csv_mods.write_text(
        "modifier_id,category,keywords,description\n"
        "M_RD,EXPENSE_NATURE,Research;Development,R and D\n",
        encoding="utf-8",
    )
    mods = load_subatomic_modifiers(csv_mods)
    assert len(mods) == 1
    assert mods[0].keywords == ("Research", "Development")


def test_missing_taxonomy_file_raises(tmp_path: Path) -> None:
    """Verify FileNotFoundError when taxonomy files are absent."""
    with pytest.raises(FileNotFoundError):
        load_domain_taxonomy(tmp_path)
