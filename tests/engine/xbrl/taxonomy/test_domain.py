"""Tests for sub-atomic accounting taxonomy and relational schemas."""

from pathlib import Path
import pytest

from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    PrimeHead,
    SemanticConceptFrame,
    SubatomicModifier,
    load_domain_taxonomy,
    load_prime_heads,
    load_subatomic_modifiers,
)
from tests.support import fixture_path


def test_load_taxonomy_from_fixtures() -> None:
    """Verify loading taxonomy heads, modifiers, and relations from JSON files."""
    tax_dir = fixture_path("xbrl/taxonomy")
    taxonomy = load_domain_taxonomy(tax_dir)

    assert len(taxonomy.prime_heads) == 12
    assert len(taxonomy.subatomic_modifiers) == 43
    assert taxonomy.atom_relations is not None
    assert len(taxonomy.atom_relations.relations) >= 16
    assert taxonomy.token_lexicon is not None
    assert len(taxonomy.geography_edges) == 81
    assert len(taxonomy.industry_profiles) == 273

    swap = taxonomy.modifier("M_SWAP")
    assert swap is not None
    assert swap.category == "INSTRUMENT_DERIVATIVE"
    assert "InterestRateSwap" in swap.keywords

    cf_hedge = taxonomy.modifier("M_CASH_FLOW_HEDGE")
    assert cf_hedge is not None
    assert cf_hedge.category == "HEDGE_DESIGNATION"

    deriv_formula = [
        r
        for r in taxonomy.atom_relations.relations
        if r.formula_id == "FORMULA_DERIVATIVE_NET_ASSET"
    ]
    assert len(deriv_formula) == 3

    rev = taxonomy.prime_head("H_REVENUE")
    assert rev is not None
    assert rev.head_symbol == "REVENUE"
    assert rev.canonical_concept == "Revenues"
    assert rev.statement_type == "IncomeStatement"
    assert rev.normal_balance == "CREDIT"
    assert rev.recognition_book == "B_INCOME_STATEMENT"
    assert rev.flow_stock == "FLOW"
    assert rev.timing_horizon == "DURATION_PERIOD"
    assert rev.is_dual_role_primitive == 0

    sales = taxonomy.modifier("M_SALES_GOODS")
    assert sales is not None
    assert sales.category == "REVENUE_TYPE"
    assert "Goods" in sales.keywords

    aapl = taxonomy.industry_profile("AAPL")
    assert aapl is not None
    assert aapl.company_name == "Apple Inc."
    assert aapl.sic_code == 3571

    assert taxonomy.prime_head("NON_EXISTENT") is None
    assert taxonomy.modifier("NON_EXISTENT") is None
    assert taxonomy.industry_profile("NON_EXISTENT") is None


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
        canonical_concept="CashAndCashEquivalents",
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


def test_resolve_geography_multi_scheme_and_domicile() -> None:
    """Verify dynamic geography resolution across overlapping regional schemes and firm domicile."""
    taxonomy = load_domain_taxonomy()

    # 1. Domestic vs Foreign relative to domicile
    us_res = taxonomy.resolve_geography("country:US", firm_domicile="US")
    assert us_res is not None
    assert us_res.is_domestic is True
    assert us_res.is_foreign is False

    uk_firm_us_res = taxonomy.resolve_geography("country:US", firm_domicile="GB")
    assert uk_firm_us_res is not None
    assert uk_firm_us_res.is_domestic is False
    assert uk_firm_us_res.is_foreign is True

    # 2. Multi-parent meronymy: Mexico in both USMCA and LATAM
    mx_res = taxonomy.resolve_geography("country:MX", firm_domicile="US")
    assert mx_res is not None
    assert "srt:NorthAmericaMember" in mx_res.ancestor_regions
    assert "srt:LatinAmericaMember" in mx_res.ancestor_regions
    assert "D_GEO_USMCA" in mx_res.decomposition_schemes
    assert "D_GEO_CORP_LATAM" in mx_res.decomposition_schemes

    # 3. Greater China rollup into APAC
    cn_res = taxonomy.resolve_geography("country:CN", firm_domicile="US")
    assert cn_res is not None
    assert "corp:GreaterChinaMember" in cn_res.ancestor_regions
    assert "srt:AsiaPacificMember" in cn_res.ancestor_regions

    # 4. EMEA components
    eu_res = taxonomy.resolve_geography("srt:EuropeMember", firm_domicile="US")
    assert eu_res is not None
    assert "srt:EMEAMember" in eu_res.ancestor_regions


def test_multidimensional_instrument_and_subspace_invariants() -> None:
    """Verify instrument DAG hierarchy, fair value rules, and subspace routing invariants."""
    taxonomy = load_domain_taxonomy()

    # 1. Instrument transitive hierarchy: IRSwap -> Swap -> Derivative -> FinancialInstrument
    assert (
        taxonomy.is_instrument_subtype("InterestRateSwapMember", "SwapMember") is True
    )
    assert (
        taxonomy.is_instrument_subtype("InterestRateSwapMember", "DerivativeMember")
        is True
    )
    assert (
        taxonomy.is_instrument_subtype(
            "InterestRateSwapMember", "FinancialInstrumentMember"
        )
        is True
    )
    assert (
        taxonomy.is_instrument_subtype(
            "DebtSecurityAFSMember", "FinancialInstrumentMember"
        )
        is True
    )
    assert (
        taxonomy.is_instrument_subtype("DebtSecurityAFSMember", "DerivativeMember")
        is False
    )

    # 2. Fair value hierarchy rules
    lvl1_level, lvl1_basis = taxonomy.resolve_valuation_basis(
        "us-gaap:FairValueInputsLevel1Member"
    )
    assert lvl1_level == "LEVEL_1"
    assert lvl1_basis == "FAIR_VALUE"

    amort_level, amort_basis = taxonomy.resolve_valuation_basis(
        "us-gaap:AmortizedCostMember"
    )
    assert amort_level == "AMORTIZED_COST"
    assert amort_basis == "AMORTIZED_COST"

    # 3. Subspace routing: Derivative Gain/Loss in P&L -> NonoperatingIncomeExpense
    rule_pnl = taxonomy.match_subspace_invariant(
        "GainLoss", "P_L", "InterestRateSwapMember"
    )
    assert rule_pnl is not None
    assert rule_pnl.target_node == "NonoperatingIncomeExpense"
    assert rule_pnl.algebraic_weight == 1.0

    # 4. Subspace routing: AFS Debt Gain/Loss in OCI -> OtherComprehensiveIncomeNet
    rule_oci = taxonomy.match_subspace_invariant(
        "GainLoss", "OCI", "DebtSecurityAFSMember"
    )
    assert rule_oci is not None
    assert rule_oci.target_node == "OtherComprehensiveIncomeNet"
    assert rule_oci.algebraic_weight == 1.0
