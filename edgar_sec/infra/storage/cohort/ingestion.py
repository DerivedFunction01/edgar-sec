"""Streaming intake and canonical publication of CIK cohorts."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_literal
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE

from .catalog import CohortCatalog
from .models import CohortRecord
from .paths import DATASET_FILE_NAME, CohortPaths

_DELIMITERS = {",", "\t", "|"}
_CIK_COLUMNS = {"cik", "cik_padded", "central_index_key"}
_NAME_COLUMNS = {
    "name",
    "_name",
    "title",
    "entity_name",
    "company",
    "company_name",
}
_INGEST_SCHEMA_VERSION = "1.0.0"
_CANONICAL_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64()),
        pa.field("cik_padded", pa.string()),
        pa.field("name", pa.string()),
    ]
)


@dataclass(frozen=True, slots=True)
class IngestionQuality:
    total_raw_rows: int
    usable_rows: int
    rejected_rows: int
    duplicate_rows: int


@dataclass(frozen=True, slots=True)
class IngestResult:
    cohort: CohortRecord
    quality: IngestionQuality


def _source_expression(
    connection: Any, source: Path, file_format: str, delimiter: str | None
) -> tuple[str, str, str | None]:
    path = str(source.resolve())
    if file_format == "parquet":
        expression = "read_parquet(?)"
        columns = connection.execute(
            f"DESCRIBE SELECT * FROM {expression}", [path]
        ).fetchall()
        names = [str(row[0]) for row in columns]
        cik_name = next(
            (name for name in names if name.casefold() in _CIK_COLUMNS), None
        )
        if cik_name is None:
            raise ValueError("Parquet input must contain a CIK column")
        name_name = next(
            (name for name in names if name.casefold() in _NAME_COLUMNS), None
        )
        return expression, cik_name, name_name

    if file_format == "txt":
        return (
            "read_csv(?, auto_detect=false, header=false, "
            "columns={'line':'VARCHAR'}, delim='\\x01', quote='', escape='', "
            "strict_mode=false)",
            "line",
            None,
        )

    delimiter_sql = f", delim={sql_literal(delimiter)}" if delimiter else ""
    detected = f"read_csv(?, auto_detect=true, normalize_names=true{delimiter_sql})"
    detected_names = [
        str(row[0])
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM {detected}", [path]
        ).fetchall()
    ]
    cik_name = next(
        (name for name in detected_names if name.casefold() in _CIK_COLUMNS), None
    )
    if cik_name is not None:
        name_name = next(
            (name for name in detected_names if name.casefold() in _NAME_COLUMNS), None
        )
        return detected, cik_name, name_name

    headerless = f"read_csv(?, auto_detect=true, header=false, normalize_names=true{delimiter_sql})"
    names = [
        str(row[0])
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM {headerless}", [path]
        ).fetchall()
    ]
    if not names:
        raise ValueError("delimited input has no columns")
    return headerless, names[0], names[1] if len(names) > 1 else None


def _cte(
    expression: str,
    cik_column: str,
    name_column: str | None,
    limit: int | None,
) -> tuple[str, list[str | int | None]]:
    cik = sql_identifier(cik_column)
    name = f"CAST({sql_identifier(name_column)} AS VARCHAR)" if name_column else "''"
    query = f"""
        WITH raw AS (
            SELECT row_number() OVER () AS source_order,
                   CAST({cik} AS VARCHAR) AS raw_cik,
                   coalesce({name}, '') AS raw_name
            FROM SOURCE
        ), limited AS (
            SELECT * FROM raw WHERE ? IS NULL OR source_order <= ?
        ), typed AS (
            SELECT source_order, raw_cik, raw_name,
                   try_cast(trim(raw_cik) AS BIGINT) AS cik_value,
                   coalesce(
                       regexp_full_match(trim(raw_cik), '[0-9]{{1,10}}')
                           AND try_cast(trim(raw_cik) AS BIGINT)
                               BETWEEN 1 AND 9999999999,
                       false
                   ) AS valid_cik
            FROM limited
        )
    """.replace("FROM SOURCE", f"FROM {expression}")
    return query, [limit, limit]


def _quality(
    connection: Any, cte: str, source_path: str, params: Sequence[object]
) -> IngestionQuality:
    rows = connection.execute(
        cte
        + """
        SELECT count(*),
               count(*) FILTER (WHERE valid_cik),
               count(*) FILTER (WHERE NOT valid_cik),
               count(DISTINCT cik_value) FILTER (WHERE valid_cik)
        FROM typed
        """,
        [source_path, *params],
    ).fetchone()
    total, valid_rows, rejected, usable = (int(value) for value in rows)
    result = IngestionQuality(
        total_raw_rows=total,
        usable_rows=usable,
        rejected_rows=rejected,
        duplicate_rows=valid_rows - usable,
    )
    if result.total_raw_rows != (
        result.usable_rows + result.rejected_rows + result.duplicate_rows
    ):
        raise RuntimeError("ingestion quality counts are inconsistent")
    return result


def _canonical_query(cte: str) -> str:
    return (
        cte
        + """
        , chosen AS (
            SELECT cik_value,
                   coalesce(
                       first(nullif(trim(raw_name), '') ORDER BY source_order)
                           FILTER (WHERE nullif(trim(raw_name), '') IS NOT NULL),
                       ''
                   ) AS name
            FROM typed WHERE valid_cik
            GROUP BY cik_value
        )
        SELECT row_number() OVER (ORDER BY cik_value) - 1 AS ordinal,
               printf('%010d', cik_value) AS cik_padded,
               name
        FROM chosen ORDER BY cik_value
    """
    )


def _write_canonical_parquet(
    connection: Any,
    query: str,
    destination: Path,
    params: Sequence[object],
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with pq.ParquetWriter(
        destination,
        _CANONICAL_SCHEMA,
        compression="zstd",
        compression_level=3,
        use_dictionary=False,
    ) as writer:
        reader = connection.execute(query, list(params)).to_arrow_reader(
            batch_size=DEFAULT_ROW_GROUP_SIZE
        )
        for batch in reader:
            writer.write_batch(batch, row_group_size=DEFAULT_ROW_GROUP_SIZE)
            row_count += batch.num_rows
    return row_count


def _roster_identity(dataset: Path) -> tuple[str, int]:
    import hashlib

    digest = hashlib.sha256()
    count = 0
    for batch in pq.ParquetFile(dataset).iter_batches(
        batch_size=DEFAULT_ROW_GROUP_SIZE, columns=["cik_padded"]
    ):
        for cik in batch.column(0).to_pylist():
            if count:
                digest.update(b"\n")
            digest.update(cik.encode("ascii"))
            count += 1
    return digest.hexdigest(), count


def _cohort_id(roster_id: str, origin_kind: str, origin_details: dict[str, Any]) -> str:
    identity = roster_id
    if origin_kind == "official_source":
        snapshot_id = origin_details.get("source_snapshot_id")
        if (
            not isinstance(snapshot_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_id) is None
        ):
            raise ValueError(
                "official source requires a lowercase SHA-256 source_snapshot_id"
            )
        identity = snapshot_id
    return f"c-{identity[:16]}"


def _publish_query(
    connection: Any,
    query: str,
    params: Sequence[object],
    *,
    paths: CohortPaths,
    catalog: CohortCatalog,
    name: str | None,
    description: str,
    tags: Sequence[str],
    origin_kind: str,
    origin_details: dict[str, Any],
    pinned: bool = False,
) -> CohortRecord:
    paths.cohorts_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".cohort-build-", suffix=".parquet", dir=paths.cohorts_root
    )
    os.close(descriptor)
    temporary: Path | None = Path(temporary_name)
    stage: Path | None = None
    try:
        _write_canonical_parquet(connection, query, temporary, params)
        roster_id, row_count = _roster_identity(temporary)
        cohort_id = _cohort_id(roster_id, origin_kind, origin_details)
        dataset_sha256 = file_sha256(temporary)
        final_dir = paths.cohort_dir(cohort_id)
        if final_dir.exists():
            existing = catalog.get_cohort(cohort_id)
            if existing is None:
                raise FileExistsError(
                    f"unregistered cohort directory exists: {cohort_id}"
                )
            if existing.dataset_sha256 != dataset_sha256:
                raise ValueError(f"cohort {cohort_id!r} is immutable")
            return catalog.register_cohort(
                cohort_id=cohort_id,
                name=name,
                description=description,
                origin_kind=origin_kind,
                origin_details=origin_details,
                roster_id=roster_id,
                row_count=row_count,
                distinct_cik_count=row_count,
                dataset_sha256=dataset_sha256,
                dataset_path=existing.dataset_path,
                pinned=pinned,
                tags=tags,
            )

        stage = paths.create_staging_dir(cohort_id)
        os.replace(temporary, stage / DATASET_FILE_NAME)
        temporary = None
        paths.publish_staging_dir(cohort_id, stage)
        stage = None
        dataset_path = paths.relative_path(paths.cohort_dataset_file(cohort_id))
        try:
            return catalog.register_cohort(
                cohort_id=cohort_id,
                name=name,
                description=description,
                origin_kind=origin_kind,
                origin_details=origin_details,
                roster_id=roster_id,
                row_count=row_count,
                distinct_cik_count=row_count,
                dataset_sha256=dataset_sha256,
                dataset_path=dataset_path,
                pinned=pinned,
                tags=tags,
            )
        except BaseException:
            try:
                registered = catalog.get_cohort(cohort_id) is not None
            except Exception:
                registered = True
            if not registered and final_dir.exists():
                shutil.rmtree(final_dir)
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if stage is not None and stage.exists():
            paths.remove_staging_dir(stage)


def _ingest_file(
    input_path: Path | str,
    *,
    catalog: CohortCatalog,
    paths: CohortPaths,
    name: str | None = None,
    description: str = "",
    tags: Sequence[str] = (),
    limit: int | None = None,
    delimiter: str | None = None,
    origin_kind: str = "file_import",
    origin_details: dict[str, Any] | None = None,
    pinned: bool = False,
) -> IngestResult:
    source = Path(input_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if delimiter is not None and (len(delimiter) != 1 or delimiter not in _DELIMITERS):
        raise ValueError("delimiter must be one of comma, tab, or pipe")
    suffix = source.suffix.casefold()
    file_format = (
        "parquet"
        if suffix == ".parquet"
        else "txt"
        if suffix in {".txt", ".text"}
        else "delimited"
    )
    if delimiter is not None and file_format != "delimited":
        raise ValueError("delimiter applies only to CSV or TSV input")

    connection = connect()
    try:
        expression, cik_column, name_column = _source_expression(
            connection, source, file_format, delimiter
        )
        cte, count_params = _cte(expression, cik_column, name_column, limit)
        params = [str(source.resolve()), *count_params]
        quality = _quality(connection, cte, str(source.resolve()), count_params)
        details = {
            "input_name": source.name,
            "input_sha256": file_sha256(source),
            "input_format": file_format,
            "parser_version": _INGEST_SCHEMA_VERSION,
            "total_raw_rows": quality.total_raw_rows,
            "usable_rows": quality.usable_rows,
            "rejected_rows": quality.rejected_rows,
            "duplicate_rows": quality.duplicate_rows,
        }
        if origin_details:
            collisions = details.keys() & origin_details.keys()
            if collisions:
                raise ValueError(
                    f"origin_details cannot replace ingestion provenance: {sorted(collisions)}"
                )
            details.update(origin_details)
        cohort = _publish_query(
            connection,
            _canonical_query(cte),
            params,
            paths=paths,
            catalog=catalog,
            name=name,
            description=description,
            tags=tags,
            origin_kind=origin_kind,
            origin_details=details,
            pinned=pinned,
        )
        return IngestResult(cohort=cohort, quality=quality)
    finally:
        connection.close()


def ingest_file_to_cohort(
    input_path: Path | str,
    *,
    catalog: CohortCatalog,
    paths: CohortPaths,
    name: str | None = None,
    description: str = "",
    tags: Sequence[str] = (),
    limit: int | None = None,
    delimiter: str | None = None,
) -> IngestResult:
    return _ingest_file(
        input_path,
        catalog=catalog,
        paths=paths,
        name=name,
        description=description,
        tags=tags,
        limit=limit,
        delimiter=delimiter,
    )


def publish_derived_cohort(
    input_path: Path | str,
    *,
    catalog: CohortCatalog,
    paths: CohortPaths,
    origin_kind: Literal["sample", "set_operation"],
    origin_details: dict[str, Any] | None = None,
    name: str | None = None,
    description: str = "",
    tags: Sequence[str] = (),
    pinned: bool = False,
) -> IngestResult:
    """Register a materialized sample or set-operation dataset with provenance."""
    if origin_kind not in {"sample", "set_operation"}:
        raise ValueError("derived cohorts must use sample or set_operation origin")
    return _ingest_file(
        input_path,
        catalog=catalog,
        paths=paths,
        name=name,
        description=description,
        tags=tags,
        origin_kind=origin_kind,
        origin_details=origin_details,
        pinned=pinned,
    )


__all__ = [
    "IngestResult",
    "IngestionQuality",
    "ingest_file_to_cohort",
    "publish_derived_cohort",
]
