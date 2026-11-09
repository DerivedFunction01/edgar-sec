"""Series/class reference relation: the tickered layer and publication.

The MF file's full rows publish here as DAG reference data beside the
browse layer in `series_class_browse`; the cohort publication and its
schema are untouched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

import pyarrow as pa

from edgar_sec.domain.sec_urls import normalize_cik
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node, read_pointer
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_literal

from .paths import MetadataPaths
from .series_class_browse import (
    BROWSE_RELATION,
    BROWSE_SERIES_RELATION,
    read_browse_rows,
    read_browse_series_rows,
)

__all__ = [
    "FUND_SERIES_CLASS_SPEC",
    "MF_TICKER_SOURCE_NAME",
    "SERIES_CLASS_TICKERED_SCHEMA",
    "SOURCES_RELATION",
    "TICKERED_RELATION",
    "SeriesClassIngestOutcome",
    "SeriesClassPublishOutcome",
    "SeriesClassReconciliation",
    "TickerCounts",
    "TickeredRow",
    "ingest_mf_ticker_payload",
    "parse_mf_ticker_payload",
    "publish_series_class",
    "read_tickered_rows",
    "reconcile_series_class",
    "series_class_tip",
]

MF_TICKER_SOURCE_NAME = "company_tickers_mf"
_SOURCE_SCHEMA_VERSION = "1.0.0"
SCHEMA_VERSION = "1"
FIELDS = ("cik", "seriesId", "classId", "symbol")

TICKERED_RELATION = "series_class_tickered"
SOURCES_RELATION = "series_class_sources"
PUBLISH_RELATIONS = (TICKERED_RELATION, SOURCES_RELATION)

SERIES_CLASS_TICKERED_SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("series_id", pa.string()),
        ("class_id", pa.string()),
        ("symbol", pa.string()),
    ]
)

FUND_SERIES_CLASS_SPEC = RelationSpec(
    name=TICKERED_RELATION,
    schema=SERIES_CLASS_TICKERED_SCHEMA,
    primary_key=("class_id",),
    merge_strategy="upsert",
    sort_order=("cik", "series_id", "class_id"),
    entity_key="cik",
)


@dataclass(frozen=True, slots=True)
class TickeredRow:
    """One raw mutual-fund ticker row, field-for-field."""

    cik: str
    series_id: str
    class_id: str
    symbol: str


@dataclass(frozen=True, slots=True)
class TickerCounts:
    """Reconciliation counts over one MF ticker payload."""

    listing_row_count: int
    distinct_series_count: int
    distinct_class_count: int
    distinct_cik_count: int


@dataclass(frozen=True, slots=True)
class SeriesClassIngestOutcome:
    """One MF ticker ingest: the source identity and its counts."""

    source_snapshot_id: str
    raw_sha256: str
    counts: TickerCounts
    already_current: bool


@dataclass(frozen=True, slots=True)
class SeriesClassPublishOutcome:
    """The publication outcome for one series/class snapshot."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None


@dataclass(frozen=True, slots=True)
class SeriesClassReconciliation:
    """The two relation layers counted against each other."""

    series_in_both: int
    series_browse_only: int
    series_file_only: int
    classes_in_both: int
    classes_browse_only: int
    classes_file_only: int
    symbol_agreements: int
    symbol_disagreements: int
    shared_classes_browse_untickered: int


def _table_cik(value: object) -> str:
    """Validate one ticker-table CIK cell and return it zero-padded."""
    if isinstance(value, bool) or value is None:
        raise ValueError("ticker table CIK must be an integer or digit string")
    text = str(value).strip()
    if not text or not text.isascii() or not text.isdigit():
        raise ValueError(f"ticker table CIK is not numeric: {value!r}")
    number = int(text)
    if number <= 0 or number > 9_999_999_999:
        raise ValueError(f"ticker table CIK out of range: {value!r}")
    return normalize_cik(number)


def parse_mf_ticker_payload(
    payload: bytes,
) -> tuple[list[TickeredRow], TickerCounts]:
    """Parse and validate one raw MF ticker payload, field-for-field."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("MF ticker payload is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("MF ticker payload must be a JSON object")
    fields = document.get("fields")
    if fields != list(FIELDS):
        raise ValueError(f"MF ticker fields changed: {fields!r}")
    data = document.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("MF ticker payload carries no data rows")
    rows: list[TickeredRow] = []
    for entry in data:
        if not isinstance(entry, list) or len(entry) != len(FIELDS):
            raise ValueError(f"MF ticker row is not a {len(FIELDS)}-field list")
        cik = _table_cik(entry[0])
        series_id, class_id, symbol = entry[1], entry[2], entry[3]
        if not isinstance(series_id, str) or not series_id:
            raise ValueError(f"MF ticker series id is not text: {series_id!r}")
        if not isinstance(class_id, str) or not class_id:
            raise ValueError(f"MF ticker class id is not text: {class_id!r}")
        if not isinstance(symbol, str):
            raise ValueError(f"MF ticker symbol is not text: {symbol!r}")
        rows.append(
            TickeredRow(cik=cik, series_id=series_id, class_id=class_id, symbol=symbol)
        )
    counts = TickerCounts(
        listing_row_count=len(rows),
        distinct_series_count=len({row.series_id for row in rows}),
        distinct_class_count=len({row.class_id for row in rows}),
        distinct_cik_count=len({row.cik for row in rows}),
    )
    return rows, counts


def _source_snapshot_id(raw_sha256: str) -> str:
    """The cohort's content-derived snapshot id for the same payload."""
    payload = canonical_json(
        [MF_TICKER_SOURCE_NAME, _SOURCE_SCHEMA_VERSION, raw_sha256]
    )
    return sha256_bytes(payload.encode("utf-8"))


def _open_store(paths: MetadataPaths):
    """Open the series/class store, creating its directory and relations."""
    paths.series_class_store_file.parent.mkdir(parents=True, exist_ok=True)
    con = connect(database=paths.series_class_store_file)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TICKERED_RELATION} ("
        "cik VARCHAR, series_id VARCHAR, class_id VARCHAR, symbol VARCHAR, "
        "source_snapshot_id VARCHAR)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {SOURCES_RELATION} ("
        "source_snapshot_id VARCHAR, raw_sha256 VARCHAR, "
        "listing_row_count BIGINT, distinct_series_count BIGINT, "
        "distinct_class_count BIGINT, distinct_cik_count BIGINT, "
        "ingested_at VARCHAR)"
    )
    return con


def ingest_mf_ticker_payload(
    payload: bytes,
    paths: MetadataPaths,
    *,
    ingested_at: str | None = None,
) -> SeriesClassIngestOutcome:
    """Ingest one raw MF ticker payload as the current tickered layer."""
    rows, counts = parse_mf_ticker_payload(payload)
    raw_sha256 = hashlib.sha256(payload).hexdigest()
    source_snapshot_id = _source_snapshot_id(raw_sha256)
    stamp = ingested_at or datetime.now(UTC).isoformat(timespec="seconds")
    con = _open_store(paths)
    try:
        current = con.execute(
            f"SELECT source_snapshot_id FROM {SOURCES_RELATION} "
            "ORDER BY ingested_at DESC, source_snapshot_id DESC LIMIT 1"
        ).fetchone()
        already_current = current is not None and current[0] == source_snapshot_id
        if not already_current:
            table = pa.table(
                {
                    "cik": [row.cik for row in rows],
                    "series_id": [row.series_id for row in rows],
                    "class_id": [row.class_id for row in rows],
                    "symbol": [row.symbol for row in rows],
                    "source_snapshot_id": [source_snapshot_id] * len(rows),
                }
            )
            con.register("mf_ticker_stage", table)
            try:
                con.execute(f"DELETE FROM {TICKERED_RELATION}")
                con.execute(
                    f"INSERT INTO {TICKERED_RELATION} "
                    "SELECT cik, series_id, class_id, symbol, "
                    "source_snapshot_id FROM mf_ticker_stage"
                )
            finally:
                con.unregister("mf_ticker_stage")
            con.execute(
                f"INSERT INTO {SOURCES_RELATION} VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    source_snapshot_id,
                    raw_sha256,
                    counts.listing_row_count,
                    counts.distinct_series_count,
                    counts.distinct_class_count,
                    counts.distinct_cik_count,
                    stamp,
                ],
            )
    finally:
        con.close()
    return SeriesClassIngestOutcome(
        source_snapshot_id=source_snapshot_id,
        raw_sha256=raw_sha256,
        counts=counts,
        already_current=already_current,
    )


def read_tickered_rows(paths: MetadataPaths) -> list[TickeredRow]:
    """The stored tickered layer, in relation sort order."""
    if not paths.series_class_store_file.is_file():
        return []
    con = connect(database=paths.series_class_store_file)
    try:
        fetched = con.execute(
            f"SELECT cik, series_id, class_id, symbol FROM {TICKERED_RELATION} "
            "ORDER BY cik, series_id, class_id"
        ).fetchall()
    finally:
        con.close()
    return [
        TickeredRow(
            cik=str(r[0]), series_id=str(r[1]), class_id=str(r[2]), symbol=str(r[3])
        )
        for r in fetched
    ]


def reconcile_series_class(paths: MetadataPaths) -> SeriesClassReconciliation:
    """Count the browse layer against the tickered layer, class by class."""
    tickered = read_tickered_rows(paths)
    browse = read_browse_rows(paths)
    browse_series_rows = read_browse_series_rows(paths)
    file_series = {row.series_id for row in tickered}
    browse_series = {row.series_id for row in browse_series_rows}
    file_classes = {row.class_id: row.symbol for row in tickered}
    browse_classes = {row.class_id: row.symbol for row in browse}
    shared = file_classes.keys() & browse_classes.keys()
    agreements = 0
    disagreements = 0
    untickered = 0
    for class_id in shared:
        browse_symbol = browse_classes[class_id]
        if browse_symbol is None:
            untickered += 1
        elif browse_symbol == file_classes[class_id]:
            agreements += 1
        else:
            disagreements += 1
    return SeriesClassReconciliation(
        series_in_both=len(file_series & browse_series),
        series_browse_only=len(browse_series - file_series),
        series_file_only=len(file_series - browse_series),
        classes_in_both=len(shared),
        classes_browse_only=len(browse_classes.keys() - file_classes.keys()),
        classes_file_only=len(file_classes.keys() - browse_classes.keys()),
        symbol_agreements=agreements,
        symbol_disagreements=disagreements,
        shared_classes_browse_untickered=untickered,
    )


def series_class_tip(paths: MetadataPaths, branch: str = "main") -> str | None:
    """The current series/class snapshot id on a branch, or None."""
    if not paths.series_class_catalog_file.is_file():
        return None
    pointer = read_pointer(paths.series_class_snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def publish_series_class(
    paths: MetadataPaths, *, branch: str = "main", now: datetime | None = None
) -> SeriesClassPublishOutcome:
    """Publish the series/class store's relations as the next DAG snapshot."""
    tip = series_class_tip(paths, branch)
    if not paths.series_class_store_file.is_file():
        return SeriesClassPublishOutcome(
            published=False, snapshot_id=None, tip_before=tip
        )
    fetched_at = now or datetime.now(UTC)
    con = connect(database=paths.series_class_store_file)
    try:
        existing = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if SOURCES_RELATION not in existing:
            return SeriesClassPublishOutcome(
                published=False, snapshot_id=None, tip_before=tip
            )
        source_rows = con.execute(
            f"SELECT source_snapshot_id, raw_sha256, listing_row_count, "
            f"distinct_series_count, distinct_class_count, distinct_cik_count "
            f"FROM {SOURCES_RELATION} "
            "ORDER BY ingested_at DESC, source_snapshot_id DESC LIMIT 1"
        ).fetchall()
        if not source_rows:
            return SeriesClassPublishOutcome(
                published=False, snapshot_id=None, tip_before=tip
            )
        tickered_rows = con.execute(
            f"SELECT cik, series_id, class_id, symbol FROM {TICKERED_RELATION} "
            "ORDER BY cik, series_id, class_id"
        ).fetchall()
        browse_rows = (
            con.execute(
                f"SELECT cik, series_id, series_name, class_id, class_name, "
                f"symbol, source_url, page_sha256 FROM {BROWSE_RELATION} "
                "ORDER BY cik, series_id, class_id"
            ).fetchall()
            if BROWSE_RELATION in existing
            else []
        )
        browse_series_rows = (
            con.execute(
                f"SELECT cik, series_id, series_name, source_url, "
                f"page_sha256 FROM {BROWSE_SERIES_RELATION} "
                "ORDER BY cik, series_id"
            ).fetchall()
            if BROWSE_SERIES_RELATION in existing
            else []
        )
    finally:
        con.close()
    source_snapshot_id = str(source_rows[0][0])
    raw_sha256 = str(source_rows[0][1])
    counts = TickerCounts(
        listing_row_count=int(source_rows[0][2]),
        distinct_series_count=int(source_rows[0][3]),
        distinct_class_count=int(source_rows[0][4]),
        distinct_cik_count=int(source_rows[0][5]),
    )
    snapshot_id = _snapshot_id(
        source_snapshot_id,
        raw_sha256,
        counts,
        tickered_rows,
        browse_rows,
        browse_series_rows,
    )
    if snapshot_id == tip:
        return SeriesClassPublishOutcome(
            published=False, snapshot_id=None, tip_before=tip
        )
    publish_relations = PUBLISH_RELATIONS + tuple(
        relation
        for relation in (BROWSE_SERIES_RELATION, BROWSE_RELATION)
        if relation in existing
    )
    staging = paths.series_class_transient_dir(snapshot_id) / "snapshot"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, PartDescriptor] = {}
    writer = connect()
    try:
        writer.execute(
            f"ATTACH {sql_literal(str(paths.series_class_store_file))} "
            "AS store (READ_ONLY)"
        )
        for relation in publish_relations:
            part = staging / f"{relation}.parquet"
            writer.execute(
                f"COPY {sql_identifier('store.' + relation)} "
                f"TO {sql_literal(str(part))} (FORMAT PARQUET)"
            )
            count = int(
                writer.execute(
                    f"SELECT count(*) FROM {sql_identifier('store.' + relation)}"
                ).fetchone()[0]
            )
            descriptors[relation] = PartDescriptor(
                path=f"{snapshot_id}/{relation}.parquet",
                sha256=file_sha256(part),
                row_count=count,
                byte_size=part.stat().st_size,
            )
    finally:
        writer.close()
    manifest = _manifest(
        paths,
        snapshot_id,
        tip,
        descriptors,
        fetched_at,
        source_snapshot_id,
        raw_sha256,
    )
    publish_node(
        paths.series_class_snapshots_root,
        manifest,
        staged_dir=staging,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return SeriesClassPublishOutcome(
        published=True, snapshot_id=snapshot_id, tip_before=tip
    )


def _snapshot_id(
    source_snapshot_id,
    raw_sha256,
    counts,
    tickered_rows,
    browse_rows,
    browse_series_rows,
) -> str:
    """Content identity for a series/class publish."""
    fingerprint = sha256_text(
        canonical_json(
            {
                "source_snapshot_id": source_snapshot_id,
                "raw_sha256": raw_sha256,
                "listing_row_count": counts.listing_row_count,
                "distinct_series_count": counts.distinct_series_count,
                "distinct_class_count": counts.distinct_class_count,
                "rows": [list(row) for row in tickered_rows],
                "browse_rows": [list(row) for row in browse_rows],
                "browse_series_rows": [list(row) for row in browse_series_rows],
            }
        )
    )
    return f"series-class-{fingerprint[:24]}"


def _manifest(
    paths: MetadataPaths,
    snapshot_id: str,
    tip: str | None,
    descriptors: dict[str, PartDescriptor],
    fetched_at: datetime,
    source_snapshot_id: str,
    raw_sha256: str,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    anchor = snapshot_id
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.series_class_snapshots_root, read_only=True)
        parent = catalog.get_manifest(tip)
        parents = (
            ParentRef(
                snapshot_id=tip,
                manifest_sha256=catalog.get_manifest_sha256(tip) or "",
            ),
        )
        if parent is not None:
            anchor = parent.checkpoint_anchor_id or tip
            depth = parent.lineage_depth + 1
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="delta" if tip is not None else "checkpoint",
        parents=parents,
        checkpoint_anchor_id=anchor,
        lineage_depth=depth,
        created_at=fetched_at.isoformat(),
        relations={name: (desc,) for name, desc in sorted(descriptors.items())},
        logical_fingerprint=ordered_parts_fingerprint(
            [desc.sha256 for desc in descriptors.values()]
        ),
        schema_versions={name: SCHEMA_VERSION for name in descriptors},
        metadata={
            "command": "series-class-ingest",
            "source_name": MF_TICKER_SOURCE_NAME,
            "source_snapshot_id": source_snapshot_id,
            "raw_sha256": raw_sha256,
            "fetched_at": fetched_at.isoformat(),
        },
    )
