"""Tests proving grounded seed fixture relationships and verification traces."""

import json

import pyarrow.parquet as pq

from tests.support import fixture_path


def _verify_fixture(
    firm_folder: str, expected_firm: str, expected_accession: str
) -> None:
    fixture_dir = fixture_path(f"xbrl/seed/{firm_folder}")
    trace_file = fixture_dir / "verification_trace.json"
    assert trace_file.is_file()

    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    assert trace["firm"] == expected_firm
    assert trace["accession"] == expected_accession

    text_file = fixture_dir / "normalized_text.txt"
    lines = text_file.read_text(encoding="utf-8").splitlines()

    facts_table = pq.read_table(fixture_dir / "facts.parquet")
    assert len(facts_table) > 1000

    qnames = facts_table.column("concept_qname").to_pylist()
    num_vals = facts_table.column("numeric_value").to_pylist()
    facts_lookup: dict[str, set[float]] = {}
    for q, v in zip(qnames, num_vals, strict=False):
        if v is not None:
            facts_lookup.setdefault(q, set()).add(v)

    stmt = trace["statement_of_operations"]
    for concept in stmt["concepts"]:
        line_idx = concept["line_number"] - 1
        assert 0 <= line_idx < len(lines)
        actual_line = lines[line_idx].strip()
        assert f"{concept['table_value']:,}" in actual_line

        qname = concept["concept_qname"]
        assert qname in facts_lookup
        assert concept["reported_value"] in facts_lookup[qname]

    proof = stmt["anti_chain_proof"]
    calc_sum = sum(c["weight"] * c["value"] for c in proof["components"])
    assert calc_sum == proof["target_value"]
    assert proof["is_valid_antichain"] is True

    cal_table = pq.read_table(fixture_dir / "calculation_arcs.parquet")
    assert len(cal_table) > 100


def test_msft_grounded_seed_fixture_verification() -> None:
    """Prove MSFT 10-K reported facts match line citations and calculation arcs."""
    _verify_fixture("msft_2024_10k", "MSFT", "0000950170-24-087843")


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
    """Prove seed_cohort.json contains 15 companies across diverse industry sectors."""
    cohort_path = fixture_path("xbrl/seed_cohort.json")
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    assert len(cohort) == 15

    firms = {item["firm"] for item in cohort}
    assert "JPM" in firms
    assert "AMZN" in firms
    assert "DIS" in firms
    assert "APD" in firms
    assert "MSFT" in firms
    assert "AAPL" in firms
    assert "JNJ" in firms
    assert "F" in firms

    sics = {item["sic_code"] for item in cohort}
    assert len(sics) == 15


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
