"""DuckDB company-facts store: bulk ingest with CRC carry-forward, local reads.

One live slice per CIK: a re-ingest replaces only members whose CRC
fingerprint changed, so unchanged members carry forward untouched.
"""

from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.bulk_archive import ArchiveReference, BulkArchiveStore
from edgar_sec.infra.storage.duckdb import connect, sql_quoted_identifier
from edgar_sec.infra.storage.member_index import MemberIndex, ensure_member_index

from .companyfacts import MemberPlan, normalize_member, plan_members
from .paths import MetadataPaths

__all__ = [
    "ARCHIVES_RELATION",
    "FACTS_RELATION",
    "MEMBERS_RELATION",
    "FactsIngestOutcome",
    "StoredFact",
    "facts_for_concept",
    "ingest_facts_archive",
    "open_facts_store",
    "read_facts_for_cik",
]

FACTS_RELATION = "company_facts"
MEMBERS_RELATION = "fact_members"
ARCHIVES_RELATION = "fact_archives"

_FACT_COLUMNS = (
    "cik",
    "taxonomy",
    "tag",
    "unit",
    "start",
    "end",
    "accession",
    "form",
    "filed",
    "fiscal_year",
    "fiscal_period",
    "frame",
    "value",
    "archive_sha",
    "member_crc",
)
_FLUSH_MEMBERS = 32


@dataclass(frozen=True, slots=True)
class FactsIngestOutcome:
    """One archive ingest: what was normalized, carried, and removed."""

    archive_sha: str
    member_count: int
    normalized_members: int
    carried_members: int
    removed_members: int
    fact_rows: int


@dataclass(frozen=True, slots=True)
class StoredFact:
    """One stored fact row, with the archive that produced it."""

    cik: int
    taxonomy: str
    tag: str
    unit: str
    value: float
    start: str
    end: str
    accession: str
    form: str
    filed: str
    fiscal_year: int | None
    fiscal_period: str
    frame: str
    archive_sha: str


def open_facts_store(store_file: Path):
    """Open the facts store, creating its directory and relations."""
    store_file.parent.mkdir(parents=True, exist_ok=True)
    con = connect(database=store_file)
    facts_ddl = ", ".join(
        f"{sql_quoted_identifier(name)} {kind}"
        for name, kind in (
            ("cik", "BIGINT"),
            ("taxonomy", "VARCHAR"),
            ("tag", "VARCHAR"),
            ("unit", "VARCHAR"),
            ("start", "VARCHAR"),
            ("end", "VARCHAR"),
            ("accession", "VARCHAR"),
            ("form", "VARCHAR"),
            ("filed", "VARCHAR"),
            ("fiscal_year", "BIGINT"),
            ("fiscal_period", "VARCHAR"),
            ("frame", "VARCHAR"),
            ("value", "DOUBLE"),
            ("archive_sha", "VARCHAR"),
            ("member_crc", "BIGINT"),
        )
    )
    create_facts_sql = f"CREATE TABLE IF NOT EXISTS {FACTS_RELATION} ({facts_ddl})"
    con.execute(create_facts_sql)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {MEMBERS_RELATION} ("
        "cik BIGINT, member_name VARCHAR, member_crc BIGINT, "
        "fingerprint VARCHAR, archive_sha VARCHAR, entity_name VARCHAR, "
        "fact_rows BIGINT)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {ARCHIVES_RELATION} ("
        "archive_sha VARCHAR, source_url VARCHAR, loaded_at VARCHAR, "
        "member_count BIGINT, fact_rows BIGINT, normalized_members BIGINT, "
        "carried_members BIGINT)"
    )
    return con


_MEMBER_INDEX: MemberIndex | None = None
_ZIP_FD: int | None = None


def _init_member_reader(zip_path: str, archive_sha256: str) -> None:
    """Pool initializer: map the shared member index in this child."""
    global _MEMBER_INDEX, _ZIP_FD
    index_path = ensure_member_index(zip_path, archive_sha256)
    _MEMBER_INDEX = MemberIndex(index_path)
    _ZIP_FD = os.open(zip_path, os.O_RDONLY)


def _normalize_planned_member(
    plan: MemberPlan,
) -> tuple[MemberPlan, str, pa.Table]:
    """Pool child work: read one member and normalize it to fact rows."""
    if _MEMBER_INDEX is None or _ZIP_FD is None:  # pragma: no cover
        raise RuntimeError("facts pool child was not initialized")
    raw = _MEMBER_INDEX.read_member(_ZIP_FD, plan.member_name)
    if raw is None:  # pragma: no cover - the plan came from this index
        raise RuntimeError(f"planned member {plan.member_name} is unreadable")
    entity_name, table = normalize_member(plan.cik_padded, raw)
    return plan, entity_name, table


def ingest_facts_archive(
    paths: MetadataPaths,
    reference: ArchiveReference,
    *,
    workers: int | None = None,
    loaded_at: str | None = None,
) -> FactsIngestOutcome:
    """Ingest one stored companyfacts archive into the facts store."""
    bulk_store = BulkArchiveStore(paths.bulk_archives_root)
    plans = plan_members(bulk_store.member_index(reference))
    con = open_facts_store(paths.facts_store_file)
    try:
        existing = {
            int(cik): str(fingerprint)
            for cik, fingerprint in con.execute(
                f"SELECT cik, fingerprint FROM {MEMBERS_RELATION}"
            ).fetchall()
        }
        planned_ciks = {plan.cik for plan in plans}
        removed = sorted(set(existing) - planned_ciks)
        changed = [plan for plan in plans if existing.get(plan.cik) != plan.fingerprint]
        carried = len(plans) - len(changed)
        if removed:
            _delete_ciks(con, removed)
        if changed:
            _normalize_changed(con, paths, reference, changed, workers=workers)
        stamp = loaded_at or datetime.now(UTC).isoformat(timespec="seconds")
        if carried:
            # Carried members are present in this archive too: their member
            # record names it, while their fact rows keep the producing SHA.
            con.register(
                "_facts_planned",
                pa.table({"cik": pa.array(sorted(planned_ciks), pa.int64())}),
            )
            try:
                con.execute(
                    f"UPDATE {MEMBERS_RELATION} SET archive_sha = ? "
                    "WHERE cik IN (SELECT cik FROM _facts_planned)",
                    [reference.sha256],
                )
            finally:
                con.unregister("_facts_planned")
        fact_rows = int(
            con.execute(f"SELECT count(*) FROM {FACTS_RELATION}").fetchone()[0]
        )
        con.execute(
            f"DELETE FROM {ARCHIVES_RELATION} WHERE archive_sha = ?",
            [reference.sha256],
        )
        con.execute(
            f"INSERT INTO {ARCHIVES_RELATION} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                reference.sha256,
                reference.manifest.source_url,
                stamp,
                len(plans),
                fact_rows,
                len(changed),
                carried,
            ],
        )
    finally:
        con.close()
    return FactsIngestOutcome(
        archive_sha=reference.sha256,
        member_count=len(plans),
        normalized_members=len(changed),
        carried_members=carried,
        removed_members=len(removed),
        fact_rows=fact_rows,
    )


def _delete_ciks(con, ciks: list[int]) -> None:
    """Delete every stored row and member record for the given CIKs."""
    con.register("_facts_delete", pa.table({"cik": pa.array(ciks, pa.int64())}))
    try:
        con.execute(
            f"DELETE FROM {FACTS_RELATION} WHERE cik IN (SELECT cik FROM _facts_delete)"
        )
        con.execute(
            f"DELETE FROM {MEMBERS_RELATION} "
            "WHERE cik IN (SELECT cik FROM _facts_delete)"
        )
    finally:
        con.unregister("_facts_delete")


def _normalize_changed(
    con,
    paths: MetadataPaths,
    reference: ArchiveReference,
    changed: list[MemberPlan],
    *,
    workers: int | None,
) -> None:
    """Normalize changed members on a warm spawn pool, batching into DuckDB."""
    worker_count = workers if workers and workers > 0 else derive_resources().workers
    batch: list[tuple[MemberPlan, str, pa.Table]] = []
    with ProcessPoolExecutor(
        max_workers=max(1, worker_count),
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_member_reader,
        initargs=(str(reference.path), reference.sha256),
    ) as pool:
        for result in pool.map(_normalize_planned_member, changed):
            batch.append(result)
            if len(batch) >= _FLUSH_MEMBERS:
                _flush_batch(con, batch, reference.sha256)
                batch = []
    if batch:
        _flush_batch(con, batch, reference.sha256)
    reclaim()


def _flush_batch(
    con, batch: list[tuple[MemberPlan, str, pa.Table]], archive_sha: str
) -> None:
    """Replace the batch CIKs' rows and member records in one DuckDB pass."""
    _delete_ciks(con, [plan.cik for plan, _name, _table in batch])
    tables = []
    for plan, _entity, table in batch:
        if len(table) == 0:
            continue
        tables.append(
            table.append_column(
                "archive_sha", pa.array([archive_sha] * len(table))
            ).append_column("member_crc", pa.array([plan.crc32] * len(table)))
        )
    if tables:
        combined = pa.concat_tables(tables)
        con.register("_facts_batch", combined)
        try:
            columns_sql = ", ".join(
                sql_quoted_identifier(column) for column in _FACT_COLUMNS
            )
            con.execute(
                f"INSERT INTO {FACTS_RELATION} ({columns_sql}) "
                f"SELECT {columns_sql} FROM _facts_batch"
            )
        finally:
            con.unregister("_facts_batch")
    con.executemany(
        f"INSERT INTO {MEMBERS_RELATION} VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                plan.cik,
                plan.member_name,
                plan.crc32,
                plan.fingerprint,
                archive_sha,
                entity_name,
                len(table),
            )
            for plan, entity_name, table in batch
        ],
    )


def _stored_fact(row: tuple) -> StoredFact:
    return StoredFact(
        cik=int(row[0]),
        taxonomy=str(row[1]),
        tag=str(row[2]),
        unit=str(row[3]),
        value=float(row[4]),
        start=str(row[5]),
        end=str(row[6]),
        accession=str(row[7]),
        form=str(row[8]),
        filed=str(row[9]),
        fiscal_year=int(row[10]) if row[10] is not None else None,
        fiscal_period=str(row[11]),
        frame=str(row[12]),
        archive_sha=str(row[13]),
    )


_FACT_SELECT = "cik, taxonomy, tag, unit, value, " + ", ".join(
    sql_quoted_identifier(name)
    for name in (
        "start",
        "end",
        "accession",
        "form",
        "filed",
        "fiscal_year",
        "fiscal_period",
        "frame",
        "archive_sha",
    )
)


def read_facts_for_cik(store_file: Path, cik: int | str) -> tuple[StoredFact, ...]:
    """All stored facts for one CIK, served locally from the facts store."""
    con = connect(database=store_file)
    try:
        rows = con.execute(
            f"SELECT {_FACT_SELECT} FROM {FACTS_RELATION} WHERE cik = ? "
            "ORDER BY taxonomy, tag, unit, "
            f"{sql_quoted_identifier('end')}, accession, "
            f"{sql_quoted_identifier('start')}",
            [int(cik)],
        ).fetchall()
    finally:
        con.close()
    return tuple(_stored_fact(row) for row in rows)


def facts_for_concept(
    store_file: Path,
    cik: int | str,
    taxonomy: str,
    tag: str,
    *,
    unit: str | None = None,
) -> tuple[StoredFact, ...]:
    """One CIK's stored facts for one concept, optionally one unit."""
    return tuple(
        fact
        for fact in read_facts_for_cik(store_file, cik)
        if fact.taxonomy == taxonomy
        and fact.tag == tag
        and (unit is None or fact.unit == unit)
    )
