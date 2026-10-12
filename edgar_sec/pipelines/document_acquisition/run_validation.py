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
    MATCHER_VERSION,
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
    RESOLVED_OPERATION_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    WORK_ORDER_RELATION_SCHEMAS,
    WORK_ORDER_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.relation_validation import (
    RelationValidationError,
    validate_relation_coverage,
    validate_resolved_operations,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    iter_resolved_operation_rows,
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
    if (
        type(manifest.get("bundle_schema_version")) is not int
        or manifest["bundle_schema_version"] != PLAN_BUNDLE_SCHEMA_VERSION
        or type(manifest.get("target_schema_version")) is not int
        or manifest["target_schema_version"] != TARGET_SCHEMA_VERSION
        or manifest.get("matcher_version") != MATCHER_VERSION
    ):
        raise ValueError("acquisition run target-plan schema version mismatch")
    for name, expected in (
        ("target_operation_schema_version", TARGET_OPERATION_SCHEMA_VERSION),
        ("source_request_schema_version", SOURCE_REQUEST_SCHEMA_VERSION),
        ("operation_input_schema_version", OPERATION_INPUT_SCHEMA_VERSION),
        ("resolved_operation_schema_version", RESOLVED_OPERATION_SCHEMA_VERSION),
    ):
        if type(manifest.get(name)) is not int or manifest[name] != expected:
            raise ValueError(f"acquisition run {name} mismatch")
    descriptors = manifest.get("work_order_parts")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("acquisition run manifest has no work-order parts")
    relations = validate_work_order_relations(run_root, manifest)
    parts: list[Path] = []
    row_count = 0
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
                not parquet.schema_arrow.equals(WORK_ORDER_SCHEMA, check_metadata=False)
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
    operation_parts = relations["resolved_operations"]
    expected_operations, state_operations, operation_mismatch = compare_operation_seeds(
        state_database, operation_parts
    )
    if (
        operation_mismatch
        or expected_operations != state_operations
        or expected_operations
        != sum(pq.ParquetFile(path).metadata.num_rows for path in operation_parts)
    ):
        raise ValueError("run-state operation seeds disagree with the work order")
    return tuple(parts)


def validate_work_order_relations(
    run_root: Path, manifest: dict[str, object]
) -> dict[str, tuple[Path, ...]]:
    descriptors = manifest.get("work_order_relations")
    if not isinstance(descriptors, dict) or set(descriptors) != set(
        WORK_ORDER_RELATION_SCHEMAS
    ):
        raise ValueError("run manifest work-order relations are invalid")
    paths: dict[str, tuple[Path, ...]] = {}
    declared: set[Path] = set()
    for relation, schema in WORK_ORDER_RELATION_SCHEMAS.items():
        record = descriptors[relation]
        if not isinstance(record, dict) or set(record) != {
            "parts",
            "row_count",
            "sha256",
        }:
            raise ValueError("work-order relation descriptor is invalid")
        relation_parts = record.get("parts")
        relation_count = record.get("row_count")
        relation_digest = record.get("sha256")
        if (
            not isinstance(relation_parts, list)
            or type(relation_count) is not int
            or relation_count < 0
            or not is_sha256_hex_digest(relation_digest)
        ):
            raise ValueError("work-order relation count or digest is invalid")
        loaded: list[Path] = []
        observed_count = 0
        digest_rows = []
        previous_path: str | None = None
        for part in relation_parts:
            if not isinstance(part, dict) or set(part) != {
                "path",
                "row_count",
                "byte_size",
                "sha256",
            }:
                raise ValueError("work-order relation part is invalid")
            relative = part.get("path")
            path = PurePosixPath(relative) if isinstance(relative, str) else None
            row_count = part.get("row_count")
            byte_size = part.get("byte_size")
            digest = part.get("sha256")
            if (
                path is None
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in relative
                or not path.parts
                or path.parts[0] != "work_order"
                or (
                    relation != "targets"
                    and (len(path.parts) < 3 or path.parts[1] != relation)
                )
                or (relation == "targets" and len(path.parts) != 2)
                or (previous_path is not None and relative <= previous_path)
                or type(row_count) is not int
                or row_count < 0
                or type(byte_size) is not int
                or byte_size < 0
                or not is_sha256_hex_digest(digest)
            ):
                raise ValueError("work-order relation part fields are invalid")
            candidate = run_root.joinpath(*path.parts)
            current = run_root
            for piece in path.parts:
                current = current / piece
                if current.is_symlink():
                    raise ValueError("work-order relation contains a symlink")
            resolved = candidate.resolve()
            if (
                not resolved.is_relative_to(run_root.resolve())
                or not resolved.is_file()
                or resolved.stat().st_size != byte_size
                or file_sha256(resolved) != digest
            ):
                raise ValueError("work-order relation part is missing or corrupt")
            parquet = pq.ParquetFile(resolved)
            if (
                not parquet.schema_arrow.equals(schema, check_metadata=False)
                or parquet.metadata.num_rows != row_count
            ):
                raise ValueError("work-order relation schema or rows differ")
            if resolved in declared:
                raise ValueError("work-order relation part is referenced twice")
            declared.add(resolved)
            loaded.append(resolved)
            previous_path = relative
            observed_count += row_count
            digest_rows.append([relative, row_count, byte_size, digest])
        if (
            observed_count != relation_count
            or canonical_hash(digest_rows) != relation_digest
        ):
            raise ValueError("work-order relation digest or row count differs")
        paths[relation] = tuple(loaded)
    target_part_paths = [part.get("path") for part in manifest["work_order_parts"]]
    if target_part_paths != [
        part.relative_to(run_root).as_posix() for part in paths["targets"]
    ]:
        raise ValueError("target work-order references disagree")
    work_order_root = run_root / "work_order"
    actual = {
        item.resolve() for item in work_order_root.rglob("*.parquet") if item.is_file()
    }
    if any(item.is_symlink() for item in work_order_root.rglob("*.parquet")):
        raise ValueError("work order contains an undeclared symlink")
    if actual != declared:
        raise ValueError("work order has undeclared or missing relation parts")
    if descriptors["targets"]["row_count"] != manifest.get("target_row_count"):
        raise ValueError("target relation count disagrees with run manifest")
    try:
        validate_relation_coverage(
            paths["targets"],
            {relation: paths[relation] for relation in paths if relation != "targets"},
        )
    except RelationValidationError as error:
        raise ValueError(str(error)) from error
    try:
        validate_resolved_operations(paths)
    except RelationValidationError as error:
        raise ValueError(str(error)) from error
    return paths


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


def compare_operation_seeds(
    database_path: Path, parts: tuple[Path, ...]
) -> tuple[int, int, int]:
    columns = (
        "operation_id",
        "target_id",
        "operation",
        "requested",
        "request_mode",
        "selected",
        "source_request_id",
        "input_ordinal",
        "input_role",
        "support_status",
        "support_reason",
        "capability_id",
        "capability_version",
        "handler_id",
        "handler_version",
        "output_kind",
    )
    with sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro", uri=True
    ) as connection:
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(
            "CREATE TEMP TABLE expected_operations ("
            "operation_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, "
            "operation TEXT NOT NULL, requested INTEGER NOT NULL, "
            "request_mode TEXT NOT NULL, selected INTEGER NOT NULL, "
            "source_request_id TEXT, input_ordinal INTEGER, input_role TEXT, "
            "support_status TEXT NOT NULL, support_reason TEXT, "
            "capability_id TEXT, capability_version TEXT, handler_id TEXT, "
            "handler_version TEXT, output_kind TEXT)"
        )
        cursor = connection.cursor()
        insert = "INSERT INTO expected_operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        for part in parts:
            for batch in pq.ParquetFile(part).iter_batches(
                batch_size=resolve_parquet_read_batch_size(), columns=list(columns)
            ):
                values = []
                arrays = batch.columns
                for index in range(batch.num_rows):
                    row = [column[index].as_py() for column in arrays]
                    row[3] = int(row[3])
                    row[5] = int(row[5])
                    values.append(tuple(row))
                cursor.executemany(insert, values)
        mismatch = int(
            connection.execute(
                "SELECT COUNT(*) FROM expected_operations expected "
                "LEFT JOIN operation_state actual USING (operation_id) "
                "WHERE actual.operation_id IS NULL "
                "OR expected.target_id IS NOT actual.target_id "
                "OR expected.operation IS NOT actual.operation "
                "OR expected.requested IS NOT actual.requested "
                "OR expected.request_mode IS NOT actual.request_mode "
                "OR expected.selected IS NOT actual.selected "
                "OR expected.source_request_id IS NOT actual.source_request_id "
                "OR expected.input_ordinal IS NOT actual.input_ordinal "
                "OR expected.input_role IS NOT actual.input_role "
                "OR expected.support_status IS NOT actual.support_status "
                "OR expected.support_reason IS NOT actual.support_reason "
                "OR expected.capability_id IS NOT actual.capability_id "
                "OR expected.capability_version IS NOT actual.capability_version "
                "OR expected.handler_id IS NOT actual.handler_id "
                "OR expected.handler_version IS NOT actual.handler_version "
                "OR expected.output_kind IS NOT actual.output_kind"
            ).fetchone()[0]
        )
        mismatch += int(
            connection.execute(
                "SELECT COUNT(*) FROM operation_state actual "
                "LEFT JOIN expected_operations expected USING (operation_id) "
                "WHERE expected.operation_id IS NULL"
            ).fetchone()[0]
        )
        expected_count = int(
            connection.execute("SELECT COUNT(*) FROM expected_operations").fetchone()[0]
        )
        state_count = int(
            connection.execute("SELECT COUNT(*) FROM operation_state").fetchone()[0]
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


def iter_resolved_work_order_operations(
    paths: AcquisitionPaths, run_id: str
) -> Iterator[dict[str, object]]:
    load_validated_work_order(paths, run_id)
    run_root = paths.run_dir(run_id)
    manifest = json.loads(paths.run_manifest_path(run_id).read_text(encoding="utf-8"))
    relations = validate_work_order_relations(run_root, manifest)
    yield from iter_resolved_operation_rows(relations)


__all__ = [
    "compare_work_order_seeds",
    "iter_work_order_rows",
    "load_validated_work_order",
    "validate_work_order_relations",
    "iter_resolved_work_order_operations",
]
