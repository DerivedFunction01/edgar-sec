"""Project a validated target plan into an immutable acquisition run."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.arrow_schemas import WORK_ORDER_SCHEMA
from edgar_sec.pipelines.document_acquisition.models import ProjectedAcquisitionRun
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    SCHEMA_VERSION as RUN_STATE_SCHEMA_VERSION,
    initialize_run_state,
    validate_run_state,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    ACQUISITION_CONTRACT_VERSION,
    RUN_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.target_plan import (
    TargetPlanError,
    load_acquisition_work_order,
)

_WORK_ORDER_PART = "part-00000.parquet"


class AcquisitionProjectError(ValueError):
    """An invalid plan or conflicting acquisition run was refused."""


def _run_id(projection: Any) -> str:
    return (
        "acq_"
        + canonical_hash(
            {
                "target_plan_id": projection.plan_id,
                "target_plan_digest": projection.plan_digest,
                "run_schema_version": RUN_SCHEMA_VERSION,
                "acquisition_contract_version": ACQUISITION_CONTRACT_VERSION,
                "target_plan_bundle_schema_version": projection.bundle_schema_version,
                "target_schema_version": projection.target_schema_version,
                "target_matcher_version": projection.matcher_version,
                "work_order_schema_version": WORK_ORDER_SCHEMA_VERSION,
                "run_state_schema_version": RUN_STATE_SCHEMA_VERSION,
            }
        )[:32]
    )


def _staged_path(
    paths: AcquisitionPaths, run_id: str, staged_root: Path, final_path: Path
) -> Path:
    return staged_root / final_path.relative_to(paths.run_dir(run_id))


def _work_order_seeds(path: Path) -> Iterator[WorkOrderTargetSeed]:
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=resolve_parquet_read_batch_size(),
        columns=["target_id", "executable", "skip_reason"],
    ):
        target_ids = batch.column(0).to_pylist()
        executable_values = batch.column(1).to_pylist()
        skip_reasons = batch.column(2).to_pylist()
        for target_id, executable, skip_reason in zip(
            target_ids, executable_values, skip_reasons, strict=True
        ):
            yield WorkOrderTargetSeed(target_id, executable, skip_reason)


def _manifest_for(projection: Any, work_order: Path) -> dict[str, Any]:
    part = {
        "path": f"work_order/{_WORK_ORDER_PART}",
        "row_count": projection.target_row_count,
        "byte_size": work_order.stat().st_size,
        "sha256": file_sha256(work_order),
    }
    manifest: dict[str, Any] = {
        "run_id": _run_id(projection),
        "run_schema_version": RUN_SCHEMA_VERSION,
        "acquisition_contract_version": ACQUISITION_CONTRACT_VERSION,
        "target_plan_id": projection.plan_id,
        "target_plan_digest": projection.plan_digest,
        "bundle_schema_version": projection.bundle_schema_version,
        "target_schema_version": projection.target_schema_version,
        "matcher_version": projection.matcher_version,
        "catalog_plan_id": projection.catalog_plan_id,
        "catalog_plan_digest": projection.catalog_plan_digest,
        "inventory_snapshot_id": projection.inventory_snapshot_id,
        "inventory_snapshot_digest": projection.inventory_snapshot_digest,
        "work_order_schema_version": WORK_ORDER_SCHEMA_VERSION,
        "work_order_parts": [part],
        "target_row_count": projection.target_row_count,
        "executable_count": projection.executable_count,
        "skipped_count": projection.skipped_count,
        "run_state_schema_version": RUN_STATE_SCHEMA_VERSION,
    }
    manifest["run_digest"] = canonical_hash(manifest)
    return manifest


def _load_existing_manifest(path: Path) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AcquisitionProjectError("run manifest contains duplicate fields")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file():
        raise AcquisitionProjectError("existing run manifest is missing or unsafe")
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcquisitionProjectError("existing run manifest is unreadable") from error
    if not isinstance(value, dict) or canonical_json(value) != raw:
        raise AcquisitionProjectError("existing run manifest is not canonical JSON")
    digest = value.get("run_digest")
    unsigned = dict(value)
    unsigned.pop("run_digest", None)
    if not isinstance(digest, str) or canonical_hash(unsigned) != digest:
        raise AcquisitionProjectError("existing run manifest digest mismatch")
    return value


def _validate_database(
    database: Path,
    work_order: Path,
    target_count: int,
    executable_count: int,
    skipped_count: int,
) -> None:
    if database.is_symlink() or not database.is_file():
        raise AcquisitionProjectError("run-state database is missing or unsafe")
    try:
        validate_run_state(database)
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            counts = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(executable), 0), "
                "COALESCE(SUM(1 - executable), 0) "
                "FROM target_state"
            ).fetchone()
            if counts != (target_count, executable_count, skipped_count):
                raise AcquisitionProjectError("run-state target counts disagree")
            connection.execute(
                "CREATE TEMP TABLE expected_targets ("
                "target_id TEXT PRIMARY KEY, executable INTEGER NOT NULL, "
                "skip_reason TEXT)"
            )
            cursor = connection.cursor()
            for batch in pq.ParquetFile(work_order).iter_batches(
                batch_size=resolve_parquet_read_batch_size(),
                columns=["target_id", "executable", "skip_reason"],
            ):
                cursor.executemany(
                    "INSERT INTO expected_targets VALUES (?, ?, ?)",
                    zip(
                        batch.column(0).to_pylist(),
                        (int(value) for value in batch.column(1).to_pylist()),
                        batch.column(2).to_pylist(),
                        strict=True,
                    ),
                )
            mismatch = connection.execute(
                "SELECT COUNT(*) FROM expected_targets AS expected "
                "LEFT JOIN target_state AS actual USING (target_id) "
                "WHERE actual.target_id IS NULL "
                "OR actual.executable != expected.executable "
                "OR actual.skip_reason IS NOT expected.skip_reason"
            ).fetchone()[0]
            if mismatch:
                raise AcquisitionProjectError(
                    "run-state seeds disagree with the work order"
                )
            actual_count = connection.execute(
                "SELECT COUNT(*) FROM target_state"
            ).fetchone()[0]
            expected_count = connection.execute(
                "SELECT COUNT(*) FROM expected_targets"
            ).fetchone()[0]
            if actual_count != expected_count:
                raise AcquisitionProjectError(
                    "run-state contains targets outside the work order"
                )
        finally:
            connection.close()
    except AcquisitionProjectError:
        raise
    except (OSError, sqlite3.Error, ValueError, pa.ArrowException) as error:
        raise AcquisitionProjectError(
            "run-state database failed integrity checks"
        ) from error


def _verify_existing(
    paths: AcquisitionPaths,
    run_id: str,
    expected_manifest: dict[str, Any],
    work_order: Path,
) -> None:
    run_root = paths.run_dir(run_id)
    if run_root.is_symlink() or not run_root.is_dir():
        raise AcquisitionProjectError("existing run directory is unsafe")
    manifest = _load_existing_manifest(paths.run_manifest_path(run_id))
    if manifest != expected_manifest:
        raise AcquisitionProjectError("existing run differs from the validated plan")
    part = manifest["work_order_parts"][0]
    stored_work_order_root = paths.work_order_root(run_id)
    if (
        stored_work_order_root.is_symlink()
        or not stored_work_order_root.is_dir()
        or not stored_work_order_root.resolve().is_relative_to(run_root.resolve())
    ):
        raise AcquisitionProjectError("existing work-order directory is unsafe")
    stored_work_order = stored_work_order_root / _WORK_ORDER_PART
    if (
        stored_work_order.is_symlink()
        or not stored_work_order.is_file()
        or stored_work_order.stat().st_size != part["byte_size"]
        or file_sha256(stored_work_order) != part["sha256"]
    ):
        raise AcquisitionProjectError("existing work order failed digest validation")
    try:
        parquet = pq.ParquetFile(stored_work_order)
        if (
            not parquet.schema_arrow.equals(WORK_ORDER_SCHEMA, check_metadata=False)
            or parquet.metadata.num_rows != part["row_count"]
        ):
            raise AcquisitionProjectError("existing work-order schema or count differs")
    except AcquisitionProjectError:
        raise
    except (OSError, ValueError, pa.ArrowException) as error:
        raise AcquisitionProjectError("existing work order is unreadable") from error
    _validate_database(
        paths.run_state_path(run_id),
        stored_work_order,
        expected_manifest["target_row_count"],
        expected_manifest["executable_count"],
        expected_manifest["skipped_count"],
    )


def project_acquisition_run(
    target_plan_id: str,
    *,
    paths: AcquisitionPaths,
) -> ProjectedAcquisitionRun:
    try:
        plan_dir = paths.target_plan_dir(target_plan_id)
    except (OSError, TypeError, ValueError) as error:
        raise AcquisitionProjectError("target-plan path is invalid") from error

    runs_root = paths.runs_root
    runs_root.mkdir(parents=True, exist_ok=True)
    staged_root = Path(tempfile.mkdtemp(prefix=".project-", dir=runs_root))
    try:
        run_id: str | None = None
        try:
            staged_work_order = staged_root / "work_order" / _WORK_ORDER_PART
            projection = load_acquisition_work_order(plan_dir, staged_work_order)
            run_id = _run_id(projection)
            expected_manifest = _manifest_for(projection, staged_work_order)
        except (TargetPlanError, OSError, TypeError, ValueError) as error:
            raise AcquisitionProjectError(
                f"target plan cannot be projected: {error}"
            ) from error

        final_root = paths.run_dir(run_id)
        if os.path.lexists(final_root):
            _verify_existing(paths, run_id, expected_manifest, staged_work_order)
            return ProjectedAcquisitionRun(
                run_id,
                expected_manifest,
                projection.executable_count,
                projection.skipped_count,
                expected_manifest["work_order_parts"][0]["sha256"],
                True,
            )

        staged_database = _staged_path(
            paths, run_id, staged_root, paths.run_state_path(run_id)
        )
        initialize_run_state(staged_database, _work_order_seeds(staged_work_order))
        _validate_database(
            staged_database,
            staged_work_order,
            projection.target_row_count,
            projection.executable_count,
            projection.skipped_count,
        )
        staged_manifest = _staged_path(
            paths, run_id, staged_root, paths.run_manifest_path(run_id)
        )
        atomic_write_json(staged_manifest, expected_manifest)
        if _load_existing_manifest(staged_manifest) != expected_manifest:
            raise AcquisitionProjectError("staged run manifest verification failed")
        if (
            file_sha256(staged_work_order)
            != expected_manifest["work_order_parts"][0]["sha256"]
        ):
            raise AcquisitionProjectError("staged work-order verification failed")

        if os.path.lexists(final_root):
            _verify_existing(paths, run_id, expected_manifest, staged_work_order)
            return ProjectedAcquisitionRun(
                run_id,
                expected_manifest,
                projection.executable_count,
                projection.skipped_count,
                expected_manifest["work_order_parts"][0]["sha256"],
                True,
            )
        try:
            os.rename(staged_root, final_root)
        except OSError:
            if not os.path.lexists(final_root):
                raise
            _verify_existing(paths, run_id, expected_manifest, staged_work_order)
            return ProjectedAcquisitionRun(
                run_id,
                expected_manifest,
                projection.executable_count,
                projection.skipped_count,
                expected_manifest["work_order_parts"][0]["sha256"],
                True,
            )
        return ProjectedAcquisitionRun(
            run_id,
            expected_manifest,
            projection.executable_count,
            projection.skipped_count,
            expected_manifest["work_order_parts"][0]["sha256"],
            False,
        )
    except AcquisitionProjectError:
        raise
    except (OSError, sqlite3.Error, ValueError, pa.ArrowException) as error:
        raise AcquisitionProjectError(
            f"acquisition run projection failed: {error}"
        ) from error
    finally:
        if staged_root.exists():
            shutil.rmtree(staged_root)


__all__ = [
    "AcquisitionProjectError",
    "ProjectedAcquisitionRun",
    "project_acquisition_run",
]
