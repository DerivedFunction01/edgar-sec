"""Grounded seed cohort composition and the second firm fixture batch."""

from __future__ import annotations

import json
from collections import Counter

from tests.support.corpus import bundle_dir, corpus_cohort_rows, corpus_source_bundles

from tests.engine.xbrl.solve.grounded_seed_support import _verify_fixture


def test_seed_cohort_composition() -> None:
    """Prove the corpus registries hold 125 filings across diverse sectors."""
    cohort = corpus_cohort_rows()
    assert len(cohort) == 125
    bac = [item for item in cohort if item["firm"] == "BAC"]
    assert [(item["fy"], item["accession"]) for item in bac] == [
        (2024, "0000070858-25-000139"),
        (2011, "0000070858-12-000155"),
        (2013, "0000070858-14-000012"),
        (2015, "0000070858-16-000137"),
        (2017, "0000070858-18-000009"),
        (2019, "0000070858-20-000011"),
        (2021, "0000070858-22-000062"),
        (2023, "0000070858-24-000122"),
    ]
    assert len({item["firm"] for item in cohort}) == 112

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
    assert "GOOGL" in firms
    assert "DUK" in firms
    assert "MET" in firms
    assert "EOG" in firms

    sic_counts = Counter(item["sic_code"] for item in cohort)
    duplicated = {sic for sic, count in sic_counts.items() if count > 1}
    assert duplicated == {
        1311,
        2040,
        2080,
        2810,
        2834,
        2836,
        2911,
        3559,
        3571,
        3674,
        3711,
        3841,
        4512,
        4813,
        4911,
        5211,
        5331,
        5812,
        6021,
        6141,
        6199,
        6211,
        6324,
        6331,
        6411,
        6798,
        7372,
        7389,
    }
    assert len(sic_counts) == 60


def test_render_ascii_inspection(capsys) -> None:
    """Print inspectable ASCII tree diagrams for multi-SIC seed decompositions."""
    folders = {item["firm"].lower(): item["folder"] for item in corpus_source_bundles()}
    for firm in ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis"):
        fixture_dir = bundle_dir(folders[firm])
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
