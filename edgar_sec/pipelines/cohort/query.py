"""Bounded and stably ordered cohort member queries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.infra.storage.duckdb import connect

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import CohortRecord


@dataclass(frozen=True, slots=True)
class CohortMember:
    ordinal: int
    cik_padded: str
    name: str


@dataclass(frozen=True, slots=True)
class CohortMatch(CohortMember):
    cohort_id: str
    cohort_name: str | None


def _page(limit: int, offset: int) -> None:
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset non-negative")


def _member(row: tuple[object, ...]) -> CohortMember:
    return CohortMember(int(row[0]), str(row[1]), str(row[2] or ""))


def query_cohort_members(
    dataset_path: Path,
    *,
    cik: str | None = None,
    name_substr: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[int, list[CohortMember]]:
    _page(limit, offset)
    source = Path(dataset_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    conditions: list[str] = []
    params: list[object] = [str(source)]
    if cik is not None:
        conditions.append("cik_padded = ?")
        params.append(cik.zfill(10))
    if name_substr is not None:
        conditions.append("contains(lower(name), lower(?))")
        params.append(name_substr)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    count_sql = f"SELECT count(*) FROM read_parquet(?) {where}"
    rows_sql = f"""
        SELECT ordinal, cik_padded, name FROM read_parquet(?) {where}
        ORDER BY ordinal ASC LIMIT ? OFFSET ?
    """
    with connect() as con:
        count = int(con.execute(count_sql, params).fetchone()[0])
        rows = con.execute(rows_sql, [*params, limit, offset]).fetchall()
    return count, [_member(row) for row in rows]


def _catalog_records(catalog: CohortCatalog) -> list[CohortRecord]:
    records: list[CohortRecord] = []
    offset = 0
    while True:
        page = catalog.list_cohorts(limit=500, offset=offset)
        records.extend(page)
        if len(page) < 500:
            return records
        offset += len(page)


def find_across_cohorts(
    catalog: CohortCatalog,
    *,
    cik: str | None = None,
    name_substr: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[int, list[CohortMatch]]:
    _page(limit, offset)
    records = _catalog_records(catalog)
    if not records:
        return 0, []
    selects: list[str] = []
    params: list[object] = []
    for record in records:
        dataset = catalog.paths.resolve_relative_path(record.dataset_path)
        if not dataset.is_file():
            raise FileNotFoundError(dataset)
        conditions: list[str] = []
        conditions_params: list[object] = []
        if cik is not None:
            conditions.append("cik_padded = ?")
            conditions_params.append(cik.zfill(10))
        if name_substr is not None:
            conditions.append("contains(lower(name), lower(?))")
            conditions_params.append(name_substr)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        selects.append(
            "SELECT ? AS cohort_id, ? AS cohort_name, ordinal, cik_padded, name "
            f"FROM read_parquet(?) {where}"
        )
        params.extend(
            [record.cohort_id, record.name or "", str(dataset), *conditions_params]
        )
    combined = " UNION ALL ".join(selects)
    sql = f"SELECT count(*) FROM ({combined}) results"
    page_sql = f"""
        SELECT cohort_id, cohort_name, ordinal, cik_padded, name
        FROM ({combined}) results
        ORDER BY cohort_id ASC, ordinal ASC LIMIT ? OFFSET ?
    """
    with connect() as con:
        count = int(con.execute(sql, params).fetchone()[0])
        rows = con.execute(page_sql, [*params, limit, offset]).fetchall()
    return count, [
        CohortMatch(
            cohort_id=str(row[0]),
            cohort_name=str(row[1]) or None,
            ordinal=int(row[2]),
            cik_padded=str(row[3]),
            name=str(row[4] or ""),
        )
        for row in rows
    ]


__all__ = [
    "CohortMatch",
    "CohortMember",
    "find_across_cohorts",
    "query_cohort_members",
]
