"""Validate persisted acquisition runs before transport is initialized."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    SCHEMA_VERSION as RUN_STATE_SCHEMA_VERSION,
    validate_run_state,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    ACQUISITION_CONTRACT_VERSION,
    RUN_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
    target_relation_schema,
)


def load_validated_work_order(paths: AcquisitionPaths, run_id: str) -> tuple[Path, ...]:
    run_root = paths.run_dir(run_id)
    manifest_path = paths.run_manifest_path(run_id)
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("acquisition run directory is missing or unsafe")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("acquisition run manifest is missing or unsafe")
    raw = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or canonical_json(manifest) != raw:
        raise ValueError("acquisition run manifest is not canonical JSON")
    digest = manifest.get("run_digest")
    unsigned = dict(manifest)
    unsigned.pop("run_digest", None)
    if not is_sha256_hex_digest(digest) or canonical_hash(unsigned) != digest:
        raise ValueError("acquisition run manifest digest mismatch")
    if (
        manifest.get("run_id") != run_id
        or manifest.get("run_schema_version") != RUN_SCHEMA_VERSION
        or manifest.get("acquisition_contract_version") != ACQUISITION_CONTRACT_VERSION
        or manifest.get("work_order_schema_version") != WORK_ORDER_SCHEMA_VERSION
        or manifest.get("run_state_schema_version") != RUN_STATE_SCHEMA_VERSION
    ):
        raise ValueError("acquisition run manifest identity or version mismatch")
    descriptors = manifest.get("work_order_parts")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("acquisition run manifest has no work-order parts")
    parts: list[Path] = []
    row_count = 0
    target_schema = target_relation_schema()
    expected_schema = pa.schema(
        [
            *target_schema,
            pa.field("executable", pa.bool_(), nullable=False),
            pa.field("skip_reason", pa.string(), nullable=True),
        ],
        metadata=target_schema.metadata,
    )
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            raise ValueError("work-order part descriptor is invalid")
        relative = descriptor.get("path")
        path = PurePosixPath(relative) if isinstance(relative, str) else None
        if (
            path is None
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or not isinstance(descriptor.get("row_count"), int)
            or descriptor["row_count"] < 0
            or not isinstance(descriptor.get("byte_size"), int)
            or descriptor["byte_size"] < 0
            or not is_sha256_hex_digest(descriptor.get("sha256"))
        ):
            raise ValueError("work-order part descriptor is invalid")
        candidate = run_root.joinpath(*path.parts)
        resolved = candidate.resolve()
        if (
            candidate.is_symlink()
            or not resolved.is_relative_to(run_root.resolve())
            or not resolved.is_file()
            or resolved.stat().st_size != descriptor["byte_size"]
            or file_sha256(resolved) != descriptor["sha256"]
        ):
            raise ValueError("work-order part is missing, unsafe, or corrupt")
        try:
            parquet = pq.ParquetFile(resolved)
            if (
                not parquet.schema_arrow.equals(expected_schema, check_metadata=False)
                or parquet.metadata.num_rows != descriptor["row_count"]
            ):
                raise ValueError("work-order part schema or row count differs")
        except (OSError, pa.ArrowException) as error:
            raise ValueError("work-order part is unreadable") from error
        row_count += descriptor["row_count"]
        parts.append(resolved)
    if row_count != manifest.get("target_row_count"):
        raise ValueError("work-order row count differs from the run manifest")
    validate_run_state(paths.run_state_path(run_id))
    state_database = paths.run_state_path(run_id)
    with sqlite3.connect(
        f"file:{state_database.resolve()}?mode=ro", uri=True
    ) as connection:
        actual = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(executable), 0), "
            "COALESCE(SUM(1 - executable), 0) FROM target_state"
        ).fetchone()
        expected_counts = (
            manifest["target_row_count"],
            manifest["executable_count"],
            manifest["skipped_count"],
        )
        if actual != expected_counts:
            raise ValueError("run-state counts disagree with the run manifest")
    expected_count, state_count, mismatch = compare_work_order_seeds(
        state_database, tuple(parts)
    )
    if mismatch or expected_count != state_count or expected_count != actual[0]:
        raise ValueError("run-state seeds disagree with the work order")
    return tuple(parts)


def compare_work_order_seeds(
    database_path: Path, parts: tuple[Path, ...]
) -> tuple[int, int, int]:
    with connect() as con:
        if _sqlite_scanner_installed(con):
            con.execute("LOAD sqlite_scanner")
            con.execute(
                f"ATTACH {sql_literal(str(database_path.resolve()))} "
                "AS run_state (TYPE SQLITE, READ_ONLY)"
            )
            if parts:
                work_order = (
                    f"read_parquet({sql_path_list([str(path) for path in parts])})"
                )
                result = con.execute(
                    "SELECT COUNT(expected.target_id), "
                    "COUNT(DISTINCT actual.target_id), "
                    "COUNT(*) FILTER (WHERE expected.target_id IS NULL "
                    "OR actual.target_id IS NULL "
                    "OR expected.executable IS DISTINCT FROM actual.executable "
                    "OR expected.skip_reason IS DISTINCT FROM actual.skip_reason) "
                    "+ CASE WHEN COUNT(expected.target_id) "
                    "<> COUNT(DISTINCT expected.target_id) THEN 1 ELSE 0 END "
                    f"FROM {work_order} AS expected "
                    "FULL OUTER JOIN run_state.main.target_state AS actual "
                    "USING (target_id)"
                ).fetchone()
                return tuple(int(value) for value in result)
            state_count = int(
                con.execute(
                    "SELECT COUNT(*) FROM run_state.main.target_state"
                ).fetchone()[0]
            )
            return 0, state_count, state_count

    with sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro", uri=True
    ) as connection:
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(
            "CREATE TEMP TABLE expected_targets ("
            "target_id TEXT PRIMARY KEY, executable INTEGER NOT NULL, "
            "skip_reason TEXT)"
        )
        cursor = connection.cursor()
        for part in parts:
            for batch in pq.ParquetFile(part).iter_batches(
                batch_size=resolve_parquet_read_batch_size(),
                columns=["target_id", "executable", "skip_reason"],
            ):
                target_ids, executable, skip_reason = batch.columns
                cursor.executemany(
                    "INSERT INTO expected_targets VALUES (?, ?, ?)",
                    (
                        (
                            target_ids[row_index].as_py(),
                            int(executable[row_index].as_py()),
                            skip_reason[row_index].as_py(),
                        )
                        for row_index in range(batch.num_rows)
                    ),
                )
        mismatch = int(
            connection.execute(
                "SELECT COUNT(*) FROM expected_targets AS expected "
                "LEFT JOIN target_state AS actual USING (target_id) "
                "WHERE actual.target_id IS NULL "
                "OR actual.executable != expected.executable "
                "OR actual.skip_reason IS NOT expected.skip_reason"
            ).fetchone()[0]
        )
        expected_count = int(
            connection.execute("SELECT COUNT(*) FROM expected_targets").fetchone()[0]
        )
        state_count = int(
            connection.execute("SELECT COUNT(*) FROM target_state").fetchone()[0]
        )
        return expected_count, state_count, mismatch


def _sqlite_scanner_installed(con) -> bool:
    row = con.execute(
        "SELECT installed FROM duckdb_extensions() "
        "WHERE extension_name = 'sqlite_scanner'"
    ).fetchone()
    return row is not None and bool(row[0])


def iter_work_order_rows(
    parts: tuple[Path, ...],
) -> Iterator[dict[str, object]]:
    for part in parts:
        for batch in pq.ParquetFile(part).iter_batches(
            batch_size=resolve_parquet_read_batch_size()
        ):
            columns = tuple(batch.columns)
            names = batch.schema.names
            for row_index in range(batch.num_rows):
                yield {
                    name: column[row_index].as_py()
                    for name, column in zip(names, columns, strict=True)
                }


__all__ = [
    "compare_work_order_seeds",
    "iter_work_order_rows",
    "load_validated_work_order",
]
