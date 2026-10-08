"""Validated SEC source snapshots registered as immutable system cohorts."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.duckdb import connect

from .catalog import CohortCatalog
from .ingestion import _ingest_file, _publish_query
from .models import CohortRecord
from .paths import CohortPaths

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


def _persist_raw_snapshot(
    raw_path: Path, *, source_name: str, paths: CohortPaths, raw_sha256: str
) -> tuple[str, str]:
    snapshot_id = _snapshot_id(source_name, raw_sha256)
    relative = (
        Path("source_snapshots")
        / source_name
        / f"{snapshot_id}{_SOURCE_SUFFIXES[source_name]}"
    )
    target = paths.cohorts_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_sha256(target) != raw_sha256:
            raise ValueError("immutable source snapshot digest conflict")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{snapshot_id}-", suffix=".tmp", dir=target.parent
        )
        try:
            with (
                os.fdopen(descriptor, "wb") as destination,
                raw_path.open("rb") as source,
            ):
                shutil.copyfileobj(source, destination, length=65_536)
                destination.flush()
                os.fsync(destination.fileno())
            if file_sha256(temporary_name) != raw_sha256:
                raise ValueError("source payload changed while taking its snapshot")
            os.replace(temporary_name, target)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
    return snapshot_id, paths.relative_path(target)


def _ticker_csv(raw_path: Path, paths: CohortPaths) -> tuple[Path, dict[str, int]]:
    try:
        with raw_path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"company_tickers source is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("company_tickers source must be a non-empty JSON object")

    paths.cohorts_root.mkdir(parents=True, exist_ok=True)
    descriptor, csv_name = tempfile.mkstemp(
        prefix=".ticker-rows-", suffix=".csv", dir=paths.cohorts_root
    )
    os.close(descriptor)
    csv_path = Path(csv_name)
    count = 0
    try:
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("cik", "name"))
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
                writer.writerow((cik_text, title.strip()))
                count += 1
        return csv_path, {"listing_row_count": count}
    except BaseException:
        csv_path.unlink(missing_ok=True)
        raise


def _origin_details(
    *,
    source_name: str,
    raw_sha256: str,
    snapshot_id: str,
    raw_relative_path: str,
    observed_at: str,
    source_metrics: dict[str, int],
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "source_url": SOURCE_URLS[source_name],
        "source_snapshot_id": snapshot_id,
        "raw_sha256": raw_sha256,
        "raw_path": raw_relative_path,
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
    generated, metrics = _ticker_csv(raw, paths)
    try:
        snapshot_id, raw_relative_path = _persist_raw_snapshot(
            raw, source_name=source, paths=paths, raw_sha256=raw_sha256
        )
        return _ingest_file(
            generated,
            catalog=catalog,
            paths=paths,
            description="Official SEC company ticker listings",
            tags=("system", "official-source", f"source:{source}"),
            origin_kind="official_source",
            origin_details=_origin_details(
                source_name=source,
                raw_sha256=raw_sha256,
                snapshot_id=snapshot_id,
                raw_relative_path=raw_relative_path,
                observed_at=datetime.now(UTC).isoformat(),
                source_metrics=metrics,
            ),
            pinned=True,
        ).cohort
    finally:
        generated.unlink(missing_ok=True)


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
        snapshot_id, raw_relative_path = _persist_raw_snapshot(
            raw, source_name=source, paths=paths, raw_sha256=raw_sha256
        )
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
            raw_relative_path=raw_relative_path,
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
