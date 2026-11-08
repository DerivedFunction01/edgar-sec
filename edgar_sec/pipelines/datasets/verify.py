"""Oracle verification pass over the datasets store.

Two checks, both store-side: loaded rows must equal source lines minus
header, and each BDC vintage's population is compared against the
published BDC Report population relation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.infra.storage.duckdb import sql_identifier

from .store import (
    POPULATION_RELATION,
    VINTAGES_RELATION,
    VINTAGE_TABLES_RELATION,
    open_store,
)


@dataclass(frozen=True, slots=True)
class TableCheck:
    """One loaded table's reconciliation outcome."""

    set_id: str
    vintage: str
    relation: str
    source_rows: int
    loaded_rows: int

    @property
    def ok(self) -> bool:
        """Whether the loaded rows reconcile with the source lines."""
        return self.source_rows == self.loaded_rows


@dataclass(frozen=True, slots=True)
class PopulationCheck:
    """One BDC vintage's population against the report-union register."""

    vintage: str
    dataset_ciks: int
    report_ciks: int
    both: int
    dataset_only: int
    report_only: int


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """The full verification outcome for the store."""

    tables: tuple[TableCheck, ...]
    population: tuple[PopulationCheck, ...]

    @property
    def ok(self) -> bool:
        """Whether every table reconciled."""
        return all(table.ok for table in self.tables)


def verify_store(store_file: Path) -> VerifyResult:
    """Run the verification pass over the datasets store."""
    con = open_store(store_file)
    try:
        tables = tuple(
            TableCheck(
                set_id=str(row[0]),
                vintage=str(row[1]),
                relation=str(row[2]),
                source_rows=int(row[3]),
                loaded_rows=int(row[4]),
            )
            for row in con.execute(
                f"SELECT set_id, vintage, relation, source_rows, loaded_rows "
                f"FROM {sql_identifier(VINTAGE_TABLES_RELATION)} ORDER BY set_id, vintage, relation"
            ).fetchall()
        )
        population = _population_checks(con)
    finally:
        con.close()
    return VerifyResult(tables=tables, population=population)


def _population_checks(con) -> tuple[PopulationCheck, ...]:
    """Per-vintage BDC population comparison, when both sides exist."""
    relations = {
        str(row[0])
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    if POPULATION_RELATION not in relations or "bdc_sub" not in relations:
        return ()
    checks = []
    vintages = con.execute(
        f"SELECT DISTINCT vintage FROM {sql_identifier(VINTAGES_RELATION)} WHERE set_id = 'bdc'"
    ).fetchall()
    for (vintage,) in vintages:
        row = con.execute(
            "WITH dataset AS (SELECT DISTINCT lpad(cik, 10, '0') AS cik FROM bdc_sub "
            "WHERE set_id = 'bdc' AND vintage = ?), "
            "report AS (SELECT DISTINCT cik FROM "
            f"{sql_identifier(POPULATION_RELATION)}) "
            "SELECT (SELECT count(*) FROM dataset), (SELECT count(*) FROM report), "
            "(SELECT count(*) FROM dataset d WHERE EXISTS "
            "(SELECT 1 FROM report r WHERE r.cik = d.cik)), "
            "(SELECT count(*) FROM dataset d WHERE NOT EXISTS "
            "(SELECT 1 FROM report r WHERE r.cik = d.cik)), "
            "(SELECT count(*) FROM report r WHERE NOT EXISTS "
            "(SELECT 1 FROM dataset d WHERE d.cik = r.cik))",
            [str(vintage)],
        ).fetchone()
        checks.append(
            PopulationCheck(
                vintage=str(vintage),
                dataset_ciks=int(row[0]),
                report_ciks=int(row[1]),
                both=int(row[2]),
                dataset_only=int(row[3]),
                report_only=int(row[4]),
            )
        )
    return tuple(checks)


__all__ = [
    "PopulationCheck",
    "TableCheck",
    "VerifyResult",
    "verify_store",
]
