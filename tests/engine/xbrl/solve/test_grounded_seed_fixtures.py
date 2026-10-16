"""Tests proving grounded seed fixture relationships and verification traces."""

import json

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
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
