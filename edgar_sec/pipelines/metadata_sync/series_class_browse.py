"""Series/class reference relation: the browse-edgar layer.

Parsed series pages land here beside the tickered layer: names for every
series and class, un-tickered classes as a null symbol, and every row
carrying its source page's identity.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

from edgar_sec.engine.index_pages.parser_browse import ParsedBrowseSeriesPage
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.duckdb import connect

from .paths import MetadataPaths

__all__ = [
    "BROWSE_RELATION",
    "BROWSE_SERIES_RELATION",
    "FUND_SERIES_CLASS_BROWSE_SERIES_SPEC",
    "FUND_SERIES_CLASS_BROWSE_SPEC",
    "SERIES_CLASS_BROWSE_SCHEMA",
    "SERIES_CLASS_BROWSE_SERIES_SCHEMA",
    "BrowseRelationRow",
    "BrowseSeriesRelationRow",
    "SeriesClassBrowseIngestOutcome",
    "ingest_browse_page",
    "read_browse_rows",
    "read_browse_series_rows",
]

BROWSE_RELATION = "series_class_browse"
BROWSE_SERIES_RELATION = "series_class_browse_series"

SERIES_CLASS_BROWSE_SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("series_id", pa.string()),
        ("series_name", pa.string()),
        ("class_id", pa.string()),
        ("class_name", pa.string()),
        ("symbol", pa.string()),
        ("source_url", pa.string()),
        ("page_sha256", pa.string()),
    ]
)

FUND_SERIES_CLASS_BROWSE_SPEC = RelationSpec(
    name=BROWSE_RELATION,
    schema=SERIES_CLASS_BROWSE_SCHEMA,
    primary_key=("class_id",),
    merge_strategy="upsert",
    sort_order=("cik", "series_id", "class_id"),
    entity_key="cik",
)

SERIES_CLASS_BROWSE_SERIES_SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("series_id", pa.string()),
        ("series_name", pa.string()),
        ("source_url", pa.string()),
        ("page_sha256", pa.string()),
    ]
)

FUND_SERIES_CLASS_BROWSE_SERIES_SPEC = RelationSpec(
    name=BROWSE_SERIES_RELATION,
    schema=SERIES_CLASS_BROWSE_SERIES_SCHEMA,
    primary_key=("series_id",),
    merge_strategy="upsert",
    sort_order=("cik", "series_id"),
    entity_key="cik",
)


@dataclass(frozen=True, slots=True)
class BrowseRelationRow:
    """One browse-layer class row with its source page's identity."""

    cik: str
    series_id: str
    series_name: str
    class_id: str
    class_name: str
    symbol: str | None
    source_url: str
    page_sha256: str


@dataclass(frozen=True, slots=True)
class BrowseSeriesRelationRow:
    """One browse-layer series row; a series may carry no classes."""

    cik: str
    series_id: str
    series_name: str
    source_url: str
    page_sha256: str


@dataclass(frozen=True, slots=True)
class SeriesClassBrowseIngestOutcome:
    """One series page's browse ingest: its registrant and row counts."""

    cik: str
    page_sha256: str
    series_count: int
    class_count: int
    already_current: bool


def _browse_relation_rows(page: ParsedBrowseSeriesPage) -> list[BrowseRelationRow]:
    names = {row.series_id: row.series_name for row in page.series}
    rows: list[BrowseRelationRow] = []
    for row in page.classes:
        if row.series_id not in names:
            raise ValueError(
                f"browse class {row.class_id} names unknown series {row.series_id}"
            )
        rows.append(
            BrowseRelationRow(
                cik=page.cik,
                series_id=row.series_id,
                series_name=names[row.series_id],
                class_id=row.class_id,
                class_name=row.class_name,
                symbol=row.symbol,
                source_url=page.source_url,
                page_sha256=page.page_sha256,
            )
        )
    return rows


def _open_browse_store(paths: MetadataPaths):
    """Open the series/class store, creating the browse relations."""
    paths.series_class_store_file.parent.mkdir(parents=True, exist_ok=True)
    con = connect(database=paths.series_class_store_file)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {BROWSE_RELATION} ("
        "cik VARCHAR, series_id VARCHAR, series_name VARCHAR, "
        "class_id VARCHAR, class_name VARCHAR, symbol VARCHAR, "
        "source_url VARCHAR, page_sha256 VARCHAR)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {BROWSE_SERIES_RELATION} ("
        "cik VARCHAR, series_id VARCHAR, series_name VARCHAR, "
        "source_url VARCHAR, page_sha256 VARCHAR)"
    )
    return con


def ingest_browse_page(
    page: ParsedBrowseSeriesPage,
    paths: MetadataPaths,
) -> SeriesClassBrowseIngestOutcome:
    """Ingest one parsed series page as its registrant's browse layer."""
    rows = sorted(
        _browse_relation_rows(page),
        key=lambda row: (row.cik, row.series_id, row.class_id),
    )
    series_rows = [
        BrowseSeriesRelationRow(
            cik=page.cik,
            series_id=row.series_id,
            series_name=row.series_name,
            source_url=page.source_url,
            page_sha256=page.page_sha256,
        )
        for row in sorted(page.series, key=lambda row: row.series_id)
    ]
    con = _open_browse_store(paths)
    try:
        already_current = _stored_browse_rows(con, cik=page.cik) == rows and (
            _stored_browse_series_rows(con, cik=page.cik) == series_rows
        )
        if not already_current:
            con.execute(f"DELETE FROM {BROWSE_RELATION} WHERE cik = ?", [page.cik])
            con.execute(
                f"DELETE FROM {BROWSE_SERIES_RELATION} WHERE cik = ?", [page.cik]
            )
            table = pa.table(
                {
                    "cik": [row.cik for row in rows],
                    "series_id": [row.series_id for row in rows],
                    "series_name": [row.series_name for row in rows],
                    "class_id": [row.class_id for row in rows],
                    "class_name": [row.class_name for row in rows],
                    "symbol": pa.array([row.symbol for row in rows], type=pa.string()),
                    "source_url": [row.source_url for row in rows],
                    "page_sha256": [row.page_sha256 for row in rows],
                }
            )
            con.register("browse_stage", table)
            try:
                con.execute(
                    f"INSERT INTO {BROWSE_RELATION} "
                    "SELECT cik, series_id, series_name, class_id, class_name, "
                    "symbol, source_url, page_sha256 FROM browse_stage"
                )
            finally:
                con.unregister("browse_stage")
            series_table = pa.table(
                {
                    "cik": [row.cik for row in series_rows],
                    "series_id": [row.series_id for row in series_rows],
                    "series_name": [row.series_name for row in series_rows],
                    "source_url": [row.source_url for row in series_rows],
                    "page_sha256": [row.page_sha256 for row in series_rows],
                }
            )
            con.register("browse_series_stage", series_table)
            try:
                con.execute(
                    f"INSERT INTO {BROWSE_SERIES_RELATION} "
                    "SELECT cik, series_id, series_name, source_url, "
                    "page_sha256 FROM browse_series_stage"
                )
            finally:
                con.unregister("browse_series_stage")
    finally:
        con.close()
    return SeriesClassBrowseIngestOutcome(
        cik=page.cik,
        page_sha256=page.page_sha256,
        series_count=len(page.series),
        class_count=len(rows),
        already_current=already_current,
    )


def _stored_browse_rows(con, *, cik: str | None = None) -> list[BrowseRelationRow]:
    if cik is None:
        fetched = con.execute(
            f"SELECT cik, series_id, series_name, class_id, class_name, symbol, "
            f"source_url, page_sha256 FROM {BROWSE_RELATION} "
            "ORDER BY cik, series_id, class_id"
        ).fetchall()
    else:
        fetched = con.execute(
            f"SELECT cik, series_id, series_name, class_id, class_name, symbol, "
            f"source_url, page_sha256 FROM {BROWSE_RELATION} "
            "WHERE cik = ? ORDER BY cik, series_id, class_id",
            [cik],
        ).fetchall()
    return [
        BrowseRelationRow(
            cik=str(r[0]),
            series_id=str(r[1]),
            series_name=str(r[2]),
            class_id=str(r[3]),
            class_name=str(r[4]),
            symbol=None if r[5] is None else str(r[5]),
            source_url=str(r[6]),
            page_sha256=str(r[7]),
        )
        for r in fetched
    ]


def read_browse_rows(paths: MetadataPaths) -> list[BrowseRelationRow]:
    """The stored browse class layer, in relation sort order."""
    if not paths.series_class_store_file.is_file():
        return []
    con = connect(database=paths.series_class_store_file)
    try:
        existing = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if BROWSE_RELATION not in existing:
            return []
        return _stored_browse_rows(con)
    finally:
        con.close()


def _stored_browse_series_rows(
    con, *, cik: str | None = None
) -> list[BrowseSeriesRelationRow]:
    if cik is None:
        fetched = con.execute(
            f"SELECT cik, series_id, series_name, source_url, page_sha256 "
            f"FROM {BROWSE_SERIES_RELATION} "
            "ORDER BY cik, series_id"
        ).fetchall()
    else:
        fetched = con.execute(
            f"SELECT cik, series_id, series_name, source_url, page_sha256 "
            f"FROM {BROWSE_SERIES_RELATION} "
            "WHERE cik = ? ORDER BY cik, series_id",
            [cik],
        ).fetchall()
    return [
        BrowseSeriesRelationRow(
            cik=str(r[0]),
            series_id=str(r[1]),
            series_name=str(r[2]),
            source_url=str(r[3]),
            page_sha256=str(r[4]),
        )
        for r in fetched
    ]


def read_browse_series_rows(
    paths: MetadataPaths,
) -> list[BrowseSeriesRelationRow]:
    """The stored browse series layer, in relation sort order."""
    if not paths.series_class_store_file.is_file():
        return []
    con = connect(database=paths.series_class_store_file)
    try:
        existing = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if BROWSE_SERIES_RELATION not in existing:
            return []
        return _stored_browse_series_rows(con)
    finally:
        con.close()
