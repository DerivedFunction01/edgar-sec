"""Oracle verification pass over the datasets store.

Checks, all store-side: loaded rows equal source lines minus header; BDC
populations compare against the BDC Report relation; FSDS num/sub/tag
closure is reconciled (orphan accessions and tag-pair divergence fail).
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
class FsdsCheck:
    """One FSDS vintage slice's num/sub/tag closure reconciliation."""

    vintage: str
    archive_sha: str
    sub_rows: int
    num_accessions: int
    num_orphan_accessions: int
    sub_without_num: int
    num_tag_pairs: int
    tag_pairs: int
    tag_pair_divergence: int

    @property
    def ok(self) -> bool:
        """Whether num closes exactly over sub and tag for this slice."""
        return self.num_orphan_accessions == 0 and self.tag_pair_divergence == 0


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """The full verification outcome for the store."""

    tables: tuple[TableCheck, ...]
    population: tuple[PopulationCheck, ...]
    fsds: tuple[FsdsCheck, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every table and every FSDS slice reconciled."""
        return all(table.ok for table in self.tables) and all(
            check.ok for check in self.fsds
        )


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
        fsds = _fsds_checks(con)
    finally:
        con.close()
    return VerifyResult(tables=tables, population=population, fsds=fsds)


def _fsds_checks(con) -> tuple[FsdsCheck, ...]:
    """Per-slice FSDS closure, when the FSDS relations are loaded."""
    relations = {
        str(row[0])
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    if not {"fsds_sub", "fsds_num", "fsds_tag"} <= relations:
        return ()
    slices = con.execute(
        f"SELECT DISTINCT vintage, archive_sha FROM {sql_identifier(VINTAGES_RELATION)} "
        "WHERE set_id = 'fsds' ORDER BY vintage, archive_sha"
    ).fetchall()
    checks = []
    for vintage, archive_sha in slices:
        row = con.execute(
            "WITH sub AS (SELECT DISTINCT adsh FROM fsds_sub "
            "WHERE set_id = 'fsds' AND vintage = ? AND archive_sha = ?), "
            "num AS (SELECT DISTINCT adsh FROM fsds_num "
            "WHERE set_id = 'fsds' AND vintage = ? AND archive_sha = ?), "
            "num_pairs AS (SELECT DISTINCT tag, version FROM fsds_num "
            "WHERE set_id = 'fsds' AND vintage = ? AND archive_sha = ?), "
            "tag_pairs AS (SELECT DISTINCT tag, version FROM fsds_tag "
            "WHERE set_id = 'fsds' AND vintage = ? AND archive_sha = ?) "
            "SELECT (SELECT count(*) FROM fsds_sub "
            "WHERE set_id = 'fsds' AND vintage = ? AND archive_sha = ?), "
            "(SELECT count(*) FROM num), "
            "(SELECT count(*) FROM num n WHERE NOT EXISTS "
            "(SELECT 1 FROM sub s WHERE s.adsh = n.adsh)), "
            "(SELECT count(*) FROM sub s WHERE NOT EXISTS "
            "(SELECT 1 FROM num n WHERE n.adsh = s.adsh)), "
            "(SELECT count(*) FROM num_pairs), (SELECT count(*) FROM tag_pairs), "
            "(SELECT count(*) FROM ("
            "(SELECT * FROM num_pairs EXCEPT SELECT * FROM tag_pairs) "
            "UNION ALL "
            "(SELECT * FROM tag_pairs EXCEPT SELECT * FROM num_pairs)))",
            [str(vintage), str(archive_sha)] * 5,
        ).fetchone()
        checks.append(
            FsdsCheck(
                vintage=str(vintage),
                archive_sha=str(archive_sha),
                sub_rows=int(row[0]),
                num_accessions=int(row[1]),
                num_orphan_accessions=int(row[2]),
                sub_without_num=int(row[3]),
                num_tag_pairs=int(row[4]),
                tag_pairs=int(row[5]),
                tag_pair_divergence=int(row[6]),
            )
        )
    return tuple(checks)


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
    "FsdsCheck",
    "PopulationCheck",
    "TableCheck",
    "VerifyResult",
    "verify_store",
]
