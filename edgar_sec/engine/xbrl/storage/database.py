"""DuckDB and Parquet persistence for solved nodes, quarantine, and rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from edgar_sec.infra.storage.duckdb import copy_query_to_parquet


@dataclass(frozen=True, slots=True)
class SolvedNodeRecord:
    """Record representing a successfully solved XBRL coordinate node."""

    accession: str
    firm: str
    cik: int
    period: str
    concept_qname: str
    prime_head: str
    modifiers_json: str
    resolution_tier: str
    reported_value: float | None
    derived_value: float | None
    derivation_path: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Record representing an unconsumed fact captured in quarantine."""

    accession: str
    firm: str
    period: str
    concept_qname: str
    numeric_value: float | None
    target_residual: float | None
    candidate_parent: str | None
    correlation_score: float | None
    audit_status: str


@dataclass(frozen=True, slots=True)
class UnificationRuleRecord:
    """Record representing an empirical unification rule in the knowledge base."""

    rule_id: str
    target_concept: str
    source_concept: str
    algebraic_weight: float
    scope_firm: str = "*"
    scope_sector: str = "*"
    scope_year: str = "*"
    n_support: int = 1
    n_eligible: int = 1
    laplace_confidence: float = 0.5
    is_frozen: bool = False


def init_xbrl_database(con: duckdb.DuckDBPyConnection) -> None:
    """Create schema tables for solved nodes, quarantine, and rules if absent."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS xbrl_solved_nodes (
            accession VARCHAR NOT NULL,
            firm VARCHAR NOT NULL,
            cik BIGINT NOT NULL,
            period VARCHAR NOT NULL,
            concept_qname VARCHAR NOT NULL,
            prime_head VARCHAR NOT NULL,
            modifiers_json VARCHAR NOT NULL,
            resolution_tier VARCHAR NOT NULL,
            reported_value DOUBLE,
            derived_value DOUBLE,
            derivation_path VARCHAR,
            latency_ms DOUBLE NOT NULL,
            PRIMARY KEY (accession, concept_qname, period)
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS xbrl_epistemic_quarantine (
            accession VARCHAR NOT NULL,
            firm VARCHAR NOT NULL,
            period VARCHAR NOT NULL,
            concept_qname VARCHAR NOT NULL,
            numeric_value DOUBLE,
            target_residual DOUBLE,
            candidate_parent VARCHAR,
            correlation_score DOUBLE,
            audit_status VARCHAR NOT NULL,
            PRIMARY KEY (accession, concept_qname, period)
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS xbrl_unification_rules (
            rule_id VARCHAR PRIMARY KEY,
            target_concept VARCHAR NOT NULL,
            source_concept VARCHAR NOT NULL,
            algebraic_weight DOUBLE NOT NULL,
            scope_firm VARCHAR NOT NULL,
            scope_sector VARCHAR NOT NULL,
            scope_year VARCHAR NOT NULL,
            n_support INTEGER NOT NULL,
            n_eligible INTEGER NOT NULL,
            laplace_confidence DOUBLE NOT NULL,
            is_frozen BOOLEAN NOT NULL
        );
        """
    )


def insert_solved_nodes(
    con: duckdb.DuckDBPyConnection,
    records: Sequence[SolvedNodeRecord],
) -> None:
    """Insert batch of solved node records using parameterized insert."""
    if not records:
        return
    rows = [
        (
            r.accession,
            r.firm,
            r.cik,
            r.period,
            r.concept_qname,
            r.prime_head,
            r.modifiers_json,
            r.resolution_tier,
            r.reported_value,
            r.derived_value,
            r.derivation_path,
            r.latency_ms,
        )
        for r in records
    ]
    con.executemany(
        """
        INSERT OR REPLACE INTO xbrl_solved_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_quarantined_facts(
    con: duckdb.DuckDBPyConnection,
    records: Sequence[QuarantineRecord],
) -> None:
    """Insert batch of quarantined fact records using parameterized insert."""
    if not records:
        return
    rows = [
        (
            r.accession,
            r.firm,
            r.period,
            r.concept_qname,
            r.numeric_value,
            r.target_residual,
            r.candidate_parent,
            r.correlation_score,
            r.audit_status,
        )
        for r in records
    ]
    con.executemany(
        """
        INSERT OR REPLACE INTO xbrl_epistemic_quarantine VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def upsert_unification_rule(
    con: duckdb.DuckDBPyConnection,
    rule: UnificationRuleRecord,
) -> None:
    """Upsert a single unification rule into the database."""
    con.execute(
        """
        INSERT OR REPLACE INTO xbrl_unification_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            rule.rule_id,
            rule.target_concept,
            rule.source_concept,
            rule.algebraic_weight,
            rule.scope_firm,
            rule.scope_sector,
            rule.scope_year,
            rule.n_support,
            rule.n_eligible,
            rule.laplace_confidence,
            rule.is_frozen,
        ],
    )


def query_unification_rules(
    con: duckdb.DuckDBPyConnection,
    firm: str = "*",
    sector: str = "*",
) -> list[UnificationRuleRecord]:
    """Query unification rules filtering by firm and sector scope."""
    cursor = con.execute(
        """
        SELECT rule_id, target_concept, source_concept, algebraic_weight,
               scope_firm, scope_sector, scope_year, n_support, n_eligible,
               laplace_confidence, is_frozen
        FROM xbrl_unification_rules
        WHERE (scope_firm = '?' OR scope_firm = '*' OR scope_firm = ?)
          AND (scope_sector = '?' OR scope_sector = '*' OR scope_sector = ?)
        ORDER BY laplace_confidence DESC
        """,
        [firm, sector],
    )
    return [
        UnificationRuleRecord(
            rule_id=str(row[0]),
            target_concept=str(row[1]),
            source_concept=str(row[2]),
            algebraic_weight=float(row[3]),
            scope_firm=str(row[4]),
            scope_sector=str(row[5]),
            scope_year=str(row[6]),
            n_support=int(row[7]),
            n_eligible=int(row[8]),
            laplace_confidence=float(row[9]),
            is_frozen=bool(row[10]),
        )
        for row in cursor.fetchall()
    ]


def export_table_to_parquet(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    destination: Path,
) -> int:
    """Export an internal database table out-of-core to Parquet."""
    if table_name not in (
        "xbrl_solved_nodes",
        "xbrl_epistemic_quarantine",
        "xbrl_unification_rules",
    ):
        raise ValueError(f"Invalid table name for export: {table_name}")
    query = f"SELECT * FROM {table_name}"
    return copy_query_to_parquet(con, query, destination)
