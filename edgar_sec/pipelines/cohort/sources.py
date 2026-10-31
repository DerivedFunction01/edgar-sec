"""Validated SEC source snapshots registered as immutable system cohorts."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.settings.sql import resolve_sql_insert_batch_size
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.duckdb import connect, sql_literal

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import _canonical_query, _publish_query
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths

SOURCE_URLS = {
    "cik_lookup": "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt",
    "company_tickers": "https://www.sec.gov/files/company_tickers.json",
}
_SOURCE_SCHEMA_VERSION = "1.0.0"
_SOURCE_SUFFIXES = {"cik_lookup": ".txt", "company_tickers": ".json"}


def _source_name(source_name: str) -> str:
    if source_name not in SOURCE_URLS:
        raise ValueError(f"unsupported official source: {source_name!r}")
    return source_name


def _snapshot_id(source_name: str, raw_sha256: str) -> str:
    payload = canonical_json([source_name, _SOURCE_SCHEMA_VERSION, raw_sha256])
    return sha256_bytes(payload.encode("utf-8"))


def _matching_source_record(
    source_name: str, raw_sha256: str, *, paths: CohortPaths, catalog: CohortCatalog
) -> CohortRecord | None:
    snapshot_id = _snapshot_id(source_name, raw_sha256)
    record = catalog.get_cohort(f"c-{snapshot_id[:16]}")
    if record is None:
        return None
    details = json.loads(record.origin_json)
    if (
        record.origin_kind != "official_source"
        or details.get("source_name") != source_name
        or details.get("source_snapshot_id") != snapshot_id
        or details.get("raw_sha256") != raw_sha256
    ):
        raise ValueError("official source identity conflicts with its catalog record")
    expected_path = paths.relative_path(paths.cohort_dataset_file(record.cohort_id))
    if record.dataset_path != expected_path:
        raise ValueError(
            "official source dataset path conflicts with its catalog record"
        )
    dataset = paths.resolve_relative_path(record.dataset_path)
    if not dataset.is_file() or file_sha256(dataset) != record.dataset_sha256:
        return None
    return record


def _insert_ticker_rows(
    connection: Any,
    rows: list[tuple[str, str]],
    batch_size: int | None = None,
) -> None:
    batch_size = resolve_sql_insert_batch_size(batch_size)
    connection.execute(
        "CREATE TEMP TABLE ticker_rows (entry_key VARCHAR, cik_str VARCHAR, title VARCHAR)"
    )
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        values = ", ".join(
            f"({n},{sql_literal(cik_str)},{sql_literal(title)})"
            for n, (cik_str, title) in enumerate(batch)
        )
        connection.execute(f"INSERT INTO ticker_rows VALUES {values}")


def _ticker_rows_canonical_query() -> str:
    source_cte = """
        WITH source AS (
            SELECT
                row_number() OVER () AS source_order,
                entry_key,
                cik_str AS raw_cik,
                title AS raw_name
            FROM ticker_rows
        ),
        typed AS (
            SELECT
                source_order,
                try_cast(raw_cik AS BIGINT) AS cik_value,
                raw_name,
                TRUE AS valid_cik
            FROM source
        )
    """
    return _canonical_query(source_cte)


def _origin_details(
    *,
    source_name: str,
    raw_sha256: str,
    snapshot_id: str,
    observed_at: str,
    source_metrics: dict[str, int],
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "source_url": SOURCE_URLS[source_name],
        "source_snapshot_id": snapshot_id,
        "raw_sha256": raw_sha256,
        "retrieved_at": observed_at,
        "source_parser_version": _SOURCE_SCHEMA_VERSION,
        **source_metrics,
    }


def publish_tickers_source(
    raw_path: Path, *, paths: CohortPaths, catalog: CohortCatalog
) -> CohortRecord:
    source = _source_name("company_tickers")
    raw = Path(raw_path)
    if not raw.is_file():
        raise FileNotFoundError(raw)
    raw_sha256 = file_sha256(raw)
    existing = _matching_source_record(source, raw_sha256, paths=paths, catalog=catalog)
    if existing is not None:
        return existing
    try:
        with raw.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"company_tickers source is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("company_tickers source must be a non-empty JSON object")
    rows: list[tuple[str, str]] = []
    for key in sorted(payload, key=str):
        row = payload[key]
        if not isinstance(row, dict):
            raise ValueError(f"company_tickers entry {key!r} must be an object")
        raw_cik = row.get("cik_str")
        if isinstance(raw_cik, bool) or raw_cik is None:
            raise ValueError(f"company_tickers entry {key!r} has no CIK")
        cik_text = str(raw_cik).strip()
        if (
            not cik_text.isascii()
            or not cik_text.isdigit()
            or not 1 <= int(cik_text) <= 9_999_999_999
        ):
            raise ValueError(f"company_tickers entry {key!r} has invalid CIK")
        ticker = row.get("ticker", "")
        title = row.get("title", "")
        if not isinstance(ticker, str) or not isinstance(title, str):
            raise ValueError(
                f"company_tickers entry {key!r} has invalid listing fields"
            )
        rows.append((cik_text, title.strip()))
    if not rows:
        raise ValueError("company_tickers source has no usable entries")
    connection = connect()
    try:
        _insert_ticker_rows(connection, rows)
        snapshot_id = _snapshot_id(source, raw_sha256)
        return _publish_query(
            connection,
            _ticker_rows_canonical_query(),
            [],
            paths=paths,
            catalog=catalog,
            name=None,
            description="Official SEC company ticker listings",
            tags=("system", "official-source", f"source:{source}"),
            origin_kind="official_source",
            origin_details=_origin_details(
                source_name=source,
                raw_sha256=raw_sha256,
                snapshot_id=snapshot_id,
                observed_at=datetime.now(UTC).isoformat(),
                source_metrics={"listing_row_count": len(rows)},
            ),
            pinned=True,
        )
    finally:
        connection.close()


_UNIVERSE_CTE = """
    WITH raw AS (
        SELECT row_number() OVER () AS source_order, line
        FROM read_csv(?, auto_detect=false, header=false,
                      columns={'line':'VARCHAR'}, delim='\\x01', quote='',
                      escape='', strict_mode=false)
    ), parsed AS (
        SELECT source_order, line,
               regexp_full_match(line, '.*:[0-9]{1,10}:') AS shape_valid,
               regexp_extract(line, ':([0-9]{1,10}):$', 1) AS raw_cik,
               rtrim(regexp_replace(line, ':[0-9]{1,10}:$', ''), ':') AS name
        FROM raw
    ), typed AS (
        SELECT source_order, line, name,
               try_cast(raw_cik AS BIGINT) AS cik_value,
               coalesce(shape_valid AND try_cast(raw_cik AS BIGINT)
                        BETWEEN 1 AND 9999999999, false) AS valid_cik
        FROM parsed
    )
"""


def publish_universe_source(
    raw_path: Path, *, paths: CohortPaths, catalog: CohortCatalog
) -> CohortRecord:
    source = _source_name("cik_lookup")
    raw = Path(raw_path)
    if not raw.is_file():
        raise FileNotFoundError(raw)
    raw_sha256 = file_sha256(raw)
    existing = _matching_source_record(source, raw_sha256, paths=paths, catalog=catalog)
    if existing is not None:
        return existing
    connection = connect()
    try:
        line_count, rejected, usable = connection.execute(
            _UNIVERSE_CTE + "SELECT count(*), count(*) FILTER (WHERE NOT valid_cik), "
            "count(DISTINCT cik_value) FILTER (WHERE valid_cik) FROM typed",
            [str(raw.resolve())],
        ).fetchone()
        line_count, rejected, usable = int(line_count), int(rejected), int(usable)
        if rejected:
            raise ValueError(
                f"cik_lookup source has {rejected} malformed or out-of-range row(s)"
            )
        if not usable:
            raise ValueError("cik_lookup source contains no usable registrants")
        duplicate_rows = int(line_count) - rejected - usable
        snapshot_id = _snapshot_id(source, raw_sha256)
        query = (
            _UNIVERSE_CTE
            + """
            , chosen AS (
                SELECT cik_value,
                       coalesce(
                           first(nullif(trim(name), '') ORDER BY source_order)
                               FILTER (WHERE nullif(trim(name), '') IS NOT NULL),
                           ''
                       ) AS name
                FROM typed WHERE valid_cik GROUP BY cik_value
            )
            SELECT row_number() OVER (ORDER BY cik_value) - 1 AS ordinal,
                   printf('%010d', cik_value) AS cik_padded, name
            FROM chosen ORDER BY cik_value
        """
        )
        details = _origin_details(
            source_name=source,
            raw_sha256=raw_sha256,
            snapshot_id=snapshot_id,
            observed_at=datetime.now(UTC).isoformat(),
            source_metrics={
                "line_count": line_count,
                "distinct_cik_count": usable,
                "collapsed_name_count": duplicate_rows,
            },
        )
        return _publish_query(
            connection,
            query,
            [str(raw.resolve())],
            paths=paths,
            catalog=catalog,
            name=None,
            description="Official SEC registrant lookup universe",
            tags=("system", "official-source", f"source:{source}"),
            origin_kind="official_source",
            origin_details=details,
            pinned=True,
        )
    finally:
        connection.close()


def refresh_official_source(
    source_name: str,
    *,
    client: SecHttpClient,
    paths: CohortPaths,
    catalog: CohortCatalog,
) -> CohortRecord:
    source = _source_name(source_name)
    payload = client.get_bytes(SOURCE_URLS[source], mutable=True)
    raw_sha256 = sha256_bytes(payload)
    existing = _matching_source_record(source, raw_sha256, paths=paths, catalog=catalog)
    if existing is not None:
        swap_active_source_pointer(source, existing.cohort_id, catalog=catalog)
        return existing
    paths.cohorts_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{source}-", suffix=_SOURCE_SUFFIXES[source], dir=paths.cohorts_root
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = Path(temporary_name)
        record = (
            publish_universe_source(temporary, paths=paths, catalog=catalog)
            if source == "cik_lookup"
            else publish_tickers_source(temporary, paths=paths, catalog=catalog)
        )
        swap_active_source_pointer(source, record.cohort_id, catalog=catalog)
        return record
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def swap_active_source_pointer(
    source_name: str, snapshot_id: str, *, catalog: CohortCatalog
) -> None:
    source = _source_name(source_name)
    record = catalog.get_cohort(snapshot_id)
    if record is None or record.origin_kind != "official_source":
        raise ValueError("active source target must be a registered official cohort")
    details = json.loads(record.origin_json)
    if details.get("source_name") != source:
        raise ValueError("active source target belongs to a different source")
    catalog.set_active_source_pointer(source, record.cohort_id)


def resolve_active_source(
    source_name: str, *, catalog: CohortCatalog
) -> CohortRecord | None:
    source = _source_name(source_name)
    snapshot_id = catalog.get_active_source_pointer(source)
    return catalog.get_cohort(snapshot_id) if snapshot_id is not None else None


__all__ = [
    "SOURCE_URLS",
    "publish_tickers_source",
    "publish_universe_source",
    "refresh_official_source",
    "resolve_active_source",
    "swap_active_source_pointer",
]
