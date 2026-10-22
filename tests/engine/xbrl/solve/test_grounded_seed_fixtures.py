"""Tests proving grounded seed fixture relationships and verification traces."""

import json
from collections import Counter

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.verification import DoubleCountVerifier
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path
from .conftest import load_seed_calculation_arcs, load_seed_facts


def _verify_fixture(
    firm_folder: str, expected_firm: str, expected_accession: str
) -> None:
    fixture_dir = fixture_path(f"xbrl/seed/{firm_folder}")
    registry = json.loads(
        fixture_path("xbrl/seed/fixture_source_registry.json").read_text(
            encoding="utf-8"
        )
    )
    source = next(item for item in registry["bundles"] if item["folder"] == firm_folder)
    trace_file = fixture_dir / "verification_trace.json"
    assert trace_file.is_file()

    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    assert trace["firm"] == expected_firm
    assert trace["accession"] == expected_accession
    assert trace["accession"] == source["source_accession"]
    assert trace["fiscal_year"] == source["reported_fiscal_year"]
    assert trace["source_filing_fiscal_year"] == source["source_filing_fiscal_year"]

    cohort = json.loads(
        fixture_path("xbrl/seed_cohort.json").read_text(encoding="utf-8")
    )
    cohort_entry = next(item for item in cohort if item["firm"] == expected_firm)
    assert cohort_entry["accession"] == source["cohort_accession"]
    assert cohort_entry["fy"] == source["cohort_fiscal_year"]
    assert source["source_matches_cohort"] is (
        source["source_accession"] == source["cohort_accession"]
    )

    text_file = fixture_dir / "normalized_text.txt"
    rendered_text = text_file.read_text(encoding="utf-8")
    lines = rendered_text.splitlines()
    assert str(source["source_filing_fiscal_year"]) in "\n".join(lines[:40])

    raw_facts = pq.read_table(fixture_dir / "facts.parquet").to_pylist()
    assert len(raw_facts) > 1000
    assert {row["accession"] for row in raw_facts} == {source["source_accession"]}
    assert all(row["accession"] == trace["accession"] for row in raw_facts)
    assert source["source_cik_matches_registrant"] is (
        trace["cik"].lstrip("0") == cohort_entry["cik"].lstrip("0")
    )
    arcs = load_seed_calculation_arcs(firm_folder)
    assert len(arcs) > 100

    assert source["provenance_status"] in (
        "VERIFIED",
        "VERIFIED_COMPARATIVE_PERIOD",
    )

    facts = load_seed_facts(firm_folder)
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )

    stmt = trace["statement_of_operations"]
    scale = stmt["scale"]
    unit = stmt["unit"].split()[0]
    column_index = stmt.get("period_column_index", 0)
    line_range = tuple(stmt["line_range"])
    for concept in stmt["concepts"]:
        line_idx = concept["line_number"] - 1
        assert 0 <= line_idx < len(lines)
        actual_line = lines[line_idx].strip()
        assert actual_line == concept["snippet"]
        display_sign = concept.get("display_sign", 1)
        assert (
            abs(
                concept["table_value"] * scale * display_sign
                - concept["reported_value"]
            )
            < 1.0
        )

        rendered = DoubleCountVerifier.verify_cited_row(
            rendered_text,
            concept["label"],
            concept["reported_value"],
            line_number=concept["line_number"],
            line_range=line_range,
            scale=scale,
            column_index=column_index,
            expected_snippet=concept["snippet"],
            display_sign=display_sign,
        )
        assert rendered.is_valid, rendered.message
        assert rendered.citation.startswith(f"line {concept['line_number']}:")

        qname = concept["concept_qname"]
        dimensions = concept.get("dimensions", {})
        matching_facts = [
            row
            for row in raw_facts
            if row["concept_qname"] == qname
            and row["numeric_value"] == concept["reported_value"]
            and row["unit"] == unit
            and json.loads(row["dimensions_json"]) == dimensions
            and row["period_type"] == "duration"
            and row["end_date"][:4] == str(source["reported_fiscal_year"])
        ]
        contexts = {
            (
                row["start_date"],
                row["end_date"],
                row["unit"],
                row["dimensions_json"],
            )
            for row in matching_facts
        }
        assert len(contexts) == 1, (firm_folder, qname, contexts)
        matching = matching_facts[0]
        scope = FactScope(
            accession=source["source_accession"],
            start_date=matching["start_date"],
            end_date=matching["end_date"],
            unit=unit,
            dimensions=dimensions,
        )
        queried = engine.execute(FinancialQuery(qname, scope), facts, arcs)
        assert queried.status == QueryStatus.REPORTED, (firm_folder, qname, queried)
        assert queried.value == concept["reported_value"]

    proof = stmt["anti_chain_proof"]
    calc_sum = sum(c["weight"] * c["value"] for c in proof["components"])
    assert calc_sum == proof["target_value"]
    assert proof["is_valid_antichain"] is True
    for component in proof["components"]:
        assert any(
            row["concept_qname"] == component["concept"]
            and row["numeric_value"] == component["value"]
            and not json.loads(row["dimensions_json"])
            and row["end_date"][:4] == str(source["reported_fiscal_year"])
            for row in raw_facts
        )


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
    _verify_fixture("jpm_2024_10k", "JPM", "0001628280-26-008131")


def test_apd_grounded_seed_fixture_verification() -> None:
    """Prove APD 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("apd_2024_10k", "APD", "0000002969-25-000055")


def test_amzn_grounded_seed_fixture_verification() -> None:
    """Prove AMZN 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("amzn_2024_10k", "AMZN", "0001018724-26-000004")


def test_dis_grounded_seed_fixture_verification() -> None:
    """Prove DIS 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("dis_2024_10k", "DIS", "0001744489-25-000155")


def test_seed_cohort_composition() -> None:
    """Prove seed_cohort.json contains 41 companies across diverse industry sectors."""
    cohort_path = fixture_path("xbrl/seed_cohort.json")
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    assert len(cohort) == 41

    firms = {item["firm"] for item in cohort}
    assert "JPM" in firms
    assert "AMZN" in firms
    assert "DIS" in firms
    assert "APD" in firms
    assert "MSFT" in firms
    assert "AAPL" in firms
    assert "JNJ" in firms
    assert "F" in firms
    assert "COIN" in firms
    assert "NVDA" in firms
    assert "ALL_2022" in firms
    assert "BAC" in firms
    assert "ADM" in firms

    sic_counts = Counter(item["sic_code"] for item in cohort)
    duplicated = {sic for sic, count in sic_counts.items() if count > 1}
    assert duplicated == {2040, 2080, 2834, 3711, 4512, 6021}
    assert len(sic_counts) == 35


def test_render_ascii_inspection(capsys) -> None:
    """Print inspectable ASCII tree diagrams for multi-SIC seed decompositions."""
    for firm in ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis"):
        fixture_dir = fixture_path(f"xbrl/seed/{firm}_2024_10k")
        trace = json.loads(
            (fixture_dir / "verification_trace.json").read_text(encoding="utf-8")
        )
        stmt = trace["statement_of_operations"]
        proof = stmt["anti_chain_proof"]

        print(
            f"\n[{trace['firm']} (SIC {trace['sic_code']}, {trace['sector']}) Decomposition Graph]"
        )
        print(f"  Target Root: {proof['left_concept']} = ${proof['target_value']:,.0f}")
        for comp in proof["components"]:
            sign = "+" if comp["weight"] > 0 else "-"
            print(f"    └── [{sign}] {comp['concept']}: ${comp['value']:,.0f}")
        print(
            f"  Result Sum: ${proof['computed_sum']:,.0f} (discrepancy: {proof['discrepancy']})"
        )
        print(
            f"  Anti-Chain Invariant: {'VERIFIED' if proof['is_valid_antichain'] else 'VIOLATED'}"
        )


def test_coin_grounded_seed_fixture_verification() -> None:
    """Prove Coinbase FY2024 seed fixture relationships and traces."""
    _verify_fixture("coin_2024_10k", "COIN", "0001679788-25-000022")


def test_nvda_grounded_seed_fixture_verification() -> None:
    """Prove NVIDIA FY2024 seed fixture relationships and traces."""
    _verify_fixture("nvda_2024_10k", "NVDA", "0001045810-24-000029")


def test_nee_grounded_seed_fixture_verification() -> None:
    """Prove NextEra Energy FY2024 seed fixture relationships and traces."""
    _verify_fixture("nee_2024_10k", "NEE", "0000753308-25-000011")


def test_v_grounded_seed_fixture_verification() -> None:
    """Prove Visa FY2024 seed fixture relationships and traces."""
    _verify_fixture("v_2024_10k", "V", "0001403161-24-000058")


def test_unh_grounded_seed_fixture_verification() -> None:
    """Prove UnitedHealth FY2024 seed fixture relationships and traces."""
    _verify_fixture("unh_2024_10k", "UNH", "0000731766-25-000063")


def test_unp_grounded_seed_fixture_verification() -> None:
    """Prove Union Pacific FY2024 seed fixture relationships and traces."""
    _verify_fixture("unp_2024_10k", "UNP", "0000100885-25-000042")


def test_lmt_grounded_seed_fixture_verification() -> None:
    """Prove Lockheed Martin FY2024 seed fixture relationships and traces."""
    _verify_fixture("lmt_2024_10k", "LMT", "0000936468-25-000009")


def test_wmt_grounded_seed_fixture_verification() -> None:
    """Prove Walmart FY2024 seed fixture relationships and traces."""
    _verify_fixture("wmt_2024_10k", "WMT", "0000104169-24-000056")


def test_all_2022_grounded_seed_fixture_verification() -> None:
    """Prove Allstate FY2022 seed fixture relationships and traces."""
    _verify_fixture("all_2022_2022_10k", "ALL_2022", "0000899051-23-000020")


def test_mstr_grounded_seed_fixture_verification() -> None:
    """Prove MicroStrategy FY2024 seed fixture relationships and traces."""
    _verify_fixture("mstr_2024_10k", "MSTR", "0000950170-25-021814")


def test_fcx_grounded_seed_fixture_verification() -> None:
    """Prove Freeport-McMoRan FY2024 seed fixture relationships and traces."""
    _verify_fixture("fcx_2024_10k", "FCX", "0000831259-25-000006")


def test_cme_grounded_seed_fixture_verification() -> None:
    """Prove CME Group FY2024 seed fixture relationships and traces."""
    _verify_fixture("cme_2024_10k", "CME", "0001156375-25-000021")


def test_t_grounded_seed_fixture_verification() -> None:
    """Prove AT&T FY2024 seed fixture relationships and traces."""
    _verify_fixture("t_2024_10k", "T", "0000732717-25-000013")


def test_bmy_grounded_seed_fixture_verification() -> None:
    """Prove Bristol-Myers Squibb FY2024 seed fixture relationships and traces."""
    _verify_fixture("bmy_2024_10k", "BMY", "0000014272-25-000039")


def test_tsla_grounded_seed_fixture_verification() -> None:
    """Prove Tesla FY2024 seed fixture relationships and traces."""
    _verify_fixture("tsla_2024_10k", "TSLA", "0001628280-25-003063")


def test_alk_grounded_seed_fixture_verification() -> None:
    """Prove Alaska Air FY2024 seed fixture relationships and traces."""
    _verify_fixture("alk_2024_10k", "ALK", "0000766421-25-000009")


def test_bac_grounded_seed_fixture_verification() -> None:
    """Prove Bank of America FY2024 seed fixture relationships and traces."""
    _verify_fixture("bac_2024_10k", "BAC", "0000070858-25-000139")


def test_adm_grounded_seed_fixture_verification() -> None:
    """Prove ADM FY2024 seed fixture relationships and traces."""
    _verify_fixture("adm_2024_10k", "ADM", "0000007084-25-000011")


def test_tsn_grounded_seed_fixture_verification() -> None:
    """Prove Tyson Foods FY2024 seed fixture relationships and traces."""
    _verify_fixture("tsn_2024_10k", "TSN", "0000100493-24-000119")


def test_cf_grounded_seed_fixture_verification() -> None:
    """Prove CF Industries FY2024 seed fixture relationships and traces."""
    _verify_fixture("cf_2024_10k", "CF", "0001324404-25-000006")


def test_de_grounded_seed_fixture_verification() -> None:
    """Prove Deere FY2024 seed fixture relationships and traces."""
    _verify_fixture("de_2024_10k", "DE", "0001558370-24-016169")


def test_pep_grounded_seed_fixture_verification() -> None:
    """Prove PepsiCo FY2024 seed fixture relationships and traces."""
    _verify_fixture("pep_2024_10k", "PEP", "0000077476-25-000007")


def test_afrm_grounded_seed_fixture_verification() -> None:
    """Prove Affirm FY2024 seed fixture relationships and traces."""
    _verify_fixture("afrm_2024_10k", "AFRM", "0001820953-24-000035")


def test_alb_grounded_seed_fixture_verification() -> None:
    """Prove Albemarle FY2024 seed fixture relationships and traces."""
    _verify_fixture("alb_2024_10k", "ALB", "0000915913-25-000026")


def test_asml_grounded_seed_fixture_verification() -> None:
    """Prove ASML FY2024 seed fixture relationships and traces."""
    _verify_fixture("asml_2024_10k", "ASML", "0000937966-25-000009")


def test_gis_grounded_seed_fixture_verification() -> None:
    """Prove GIS FY2024 seed fixture relationships and traces."""
    _verify_fixture("gis_2024_10k", "GIS", "0001193125-24-168943")


def _grounded_engine() -> FinancialQueryEngine:
    return FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )


def test_bac_derivative_assets_precision_duplicate_reports_presented_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:DerivativeAssets",
            FactScope(
                accession="0000070858-25-000139",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 40_948_000_000.0
    lines = (
        fixture_path("xbrl/seed/bac_2024_10k/normalized_text.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert "Derivative assets" in lines[4571]
    assert "40,948" in lines[4571]


def test_bac_net_income_pure_unit_scope_refuses_derivation() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
                unit="pure",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_bac_net_income_canonical_scope_conflict_is_reported_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.CONFLICT
    assert result.reported_fact is not None
    assert result.reported_fact.value == 27_132_000_000.0
    lines = (
        fixture_path("xbrl/seed/bac_2024_10k/normalized_text.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert "Net income" in lines[942]
    assert "27,132" in lines[942]


def test_msft_cash_duration_scope_refuses_derivation() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-24-087843",
                start_date="2024-04-01",
                end_date="2024-06-30",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_msft_cash_canonical_instant_conflict_is_reported_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-24-087843",
                instant_date="2024-06-30",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.CONFLICT
    assert result.reported_fact is not None
    assert result.reported_fact.value == 18_315_000_000.0
    lines = (
        fixture_path("xbrl/seed/msft_2024_10k/normalized_text.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert "Cash and cash equivalents" in lines[1660]
    assert "18,315" in lines[1660]


def test_pld_cash_precision_duplicate_reports_presented_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-25-021272",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        load_seed_facts("pld_2024_10k"),
        load_seed_calculation_arcs("pld_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 1_318_591_000.0
    lines = (
        fixture_path("xbrl/seed/pld_2024_10k/normalized_text.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert "Cash and cash equivalents" in lines[2259]
    assert "1,318,591" in lines[2259]


def test_aapl_loose_revenue_candidate_set_excludes_textblocks() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000320193-24-000123",
                start_date="2023-10-01",
                end_date="2024-09-28",
            ),
        ),
        load_seed_facts("aapl_2024_10k"),
        load_seed_calculation_arcs("aapl_2024_10k"),
    )

    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == (
        "us-gaap:ContractWithCustomerLiabilityRevenueRecognized",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.value is None
    assert result.tier == "near"
    assert not any("TextBlock" in qname for qname in result.candidate_qnames)


def test_msft_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000950170-24-087843",
                start_date="2023-07-01",
                end_date="2024-06-30",
            ),
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == (
        "msft:ContractWithCustomerLiabilityRevenueDeferred",
        "msft:ContractWithCustomerLiabilityRevenueRecognizedIncludingAdditions",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )


def test_bac_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
            ),
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == (
        "us-gaap:Revenues",
        "bac:FeesAndCommissions1",
    )


def test_pld_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000950170-25-021272",
                start_date="2024-01-01",
                end_date="2024-12-31",
            ),
        ),
        load_seed_facts("pld_2024_10k"),
        load_seed_calculation_arcs("pld_2024_10k"),
    )

    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == (
        "us-gaap:Revenues",
        "pld:ManagementFeesRevenue1",
    )


def test_bac_loose_derivative_liabilities_exclude_textblock() -> None:
    engine = _grounded_engine()
    facts = load_seed_facts("bac_2024_10k")
    arcs = load_seed_calculation_arcs("bac_2024_10k")

    unscoped = engine.execute(
        FinancialQuery(
            "DerivativeLiabilities",
            FactScope(accession="0000070858-25-000139"),
        ),
        facts,
        arcs,
    )
    assert unscoped.candidate_qnames == ("us-gaap:DerivativeLiabilities",)

    result = engine.execute(
        FinancialQuery(
            "DerivativeLiabilities",
            FactScope(
                accession="0000070858-25-000139",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        facts,
        arcs,
    )
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:DerivativeLiabilities",)
    assert result.value == 39_353_000_000.0
    lines = (
        fixture_path("xbrl/seed/bac_2024_10k/normalized_text.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert "Derivative liabilities" in lines[4611]
    assert "39,353" in lines[4611]
