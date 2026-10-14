"""Unit tests for DuckDB and Parquet database layer."""

from pathlib import Path

from edgar_sec.engine.xbrl.storage.database import (
    QuarantineRecord,
    SolvedNodeRecord,
    UnificationRuleRecord,
    export_table_to_parquet,
    init_xbrl_database,
    insert_quarantined_facts,
    insert_solved_nodes,
    query_unification_rules,
    upsert_unification_rule,
)
from edgar_sec.infra.storage.duckdb import connect, count_parquet_rows


def test_init_and_insert_solved_nodes(tmp_path: Path) -> None:
    """Verify table creation and batch insertion of solved node records."""
    con = connect(database=":memory:")
    init_xbrl_database(con)

    record = SolvedNodeRecord(
        accession="0000950170-24-087843",
        firm="MSFT",
        cik=789019,
        period="2024-FY",
        concept_qname="us-gaap:GrossProfit",
        prime_head="H_INCOME",
        modifiers_json='["M_GROSS_MARGIN"]',
        resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
        reported_value=169295000000.0,
        derived_value=169295000000.0,
        derivation_path="Revenues - CostOfGoodsAndServicesSold",
        latency_ms=0.12,
    )
    insert_solved_nodes(con, [record])

    cursor = con.execute("SELECT count(*) FROM xbrl_solved_nodes")
    assert cursor.fetchone()[0] == 1

    out_parquet = tmp_path / "solved.parquet"
    rows = export_table_to_parquet(con, "xbrl_solved_nodes", out_parquet)
    assert rows == 1
    assert out_parquet.exists()
    assert count_parquet_rows(out_parquet) == 1


def test_quarantine_and_rules_queries() -> None:
    """Verify quarantined fact insertions and scoped rule queries."""
    con = connect(database=":memory:")
    init_xbrl_database(con)

    q_record = QuarantineRecord(
        accession="0000950170-24-087843",
        firm="MSFT",
        period="2024-FY",
        concept_qname="msft:RestructuringCharge",
        numeric_value=500.0,
        target_residual=500.0,
        candidate_parent="us-gaap:OperatingExpenses",
        correlation_score=0.99,
        audit_status="SHADOW_LEAF",
    )
    insert_quarantined_facts(con, [q_record])

    r1 = UnificationRuleRecord(
        rule_id="R_MSFT_1",
        target_concept="us-gaap:Revenues",
        source_concept="msft:CloudRevenue",
        algebraic_weight=1.0,
        scope_firm="MSFT",
        scope_sector="Technology",
        laplace_confidence=0.85,
    )
    r2 = UnificationRuleRecord(
        rule_id="R_UNIV_1",
        target_concept="us-gaap:GrossProfit",
        source_concept="us-gaap:Revenues",
        algebraic_weight=1.0,
        scope_firm="*",
        scope_sector="*",
        laplace_confidence=0.95,
    )
    upsert_unification_rule(con, r1)
    upsert_unification_rule(con, r2)

    msft_rules = query_unification_rules(con, firm="MSFT", sector="Technology")
    assert len(msft_rules) == 2

    energy_rules = query_unification_rules(con, firm="XOM", sector="Energy")
    assert len(energy_rules) == 1
    assert energy_rules[0].rule_id == "R_UNIV_1"
