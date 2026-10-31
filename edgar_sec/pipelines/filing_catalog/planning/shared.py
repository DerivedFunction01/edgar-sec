"""Shared validation, target files resolution, and cohort loading for catalog planning."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import PARQUET_PART_GLOB
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.paths import FilingCatalogPaths
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

_ID_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
_FORM_SEPARATOR = "/"
_FORM_SAFE = _ID_SAFE | {_FORM_SEPARATOR, " "}


def validate_forms(forms: tuple[str, ...]) -> tuple[str, ...]:
    """Validate and deduplicate requested form names."""
    for form in forms:
        if not form or not form.strip():
            raise ValueError("form filters must be non-empty")
        if not set(form) <= _FORM_SAFE:
            raise ValueError(f"unsafe form filter: {form!r}")
    return tuple(dict.fromkeys(forms))


def catalog_target_files(paths: FilingCatalogPaths, catalog_id: str) -> list[Path]:
    """Resolve active target Parquet files for a catalog snapshot or DAG node."""
    catalog = DAGCatalog(paths.snapshots_root)
    if catalog.catalog_file.is_file() and catalog.has_snapshot(catalog_id):
        active_parts = catalog.get_active_parts(catalog_id, {"filing_targets"})
        if active_parts:
            resolved: list[Path] = []
            for part in active_parts:
                p = Path(part.path)
                if (paths.snapshots_root / p).is_file():
                    resolved.append(paths.snapshots_root / p)
                elif (paths.snapshot_dir(catalog_id) / p).is_file():
                    resolved.append(paths.snapshot_dir(catalog_id) / p)
            if resolved:
                return resolved
    targets_dir = paths.snapshot_targets_dir(catalog_id)
    if not targets_dir.is_dir():
        raise PlanConflictError(f"catalog has no published targets: {targets_dir}")
    files = sorted(targets_dir.glob(PARQUET_PART_GLOB))
    if not files:
        raise PlanConflictError(f"catalog target directory is empty: {targets_dir}")
    return files


def resolve_cohort(
    artifacts_root: Path, identifier: str | None
) -> tuple[CohortRecord, Path] | None:
    """Resolve and verify a cohort identifier against its catalog and dataset."""
    if identifier is None:
        return None
    try:
        cohort_paths = resolve_cohort_paths(artifacts_root)
        record = CohortCatalog(cohort_paths).resolve_cohort_identifier(identifier)
        dataset = cohort_paths.resolve_relative_path(record.dataset_path)
        if not dataset.is_file():
            raise FileNotFoundError(dataset)
        if file_sha256(dataset) != record.dataset_sha256:
            raise ValueError(f"cohort dataset digest mismatch: {record.cohort_id}")
        with connect() as con:
            rows, distinct_ciks, invalid_ciks = con.execute(
                "SELECT count(*), "
                "count(DISTINCT try_cast(cik_padded AS BIGINT)), "
                "count(*) FILTER (WHERE try_cast(cik_padded AS BIGINT) IS NULL) "
                "FROM read_parquet(?)",
                [str(dataset)],
            ).fetchone()
        if rows != record.row_count or distinct_ciks != record.distinct_cik_count:
            raise ValueError("cohort row counts do not match its catalog record")
        if invalid_ciks:
            raise ValueError(f"cohort contains invalid CIK values: {record.cohort_id}")
        return record, dataset
    except Exception as error:
        raise ValueError(f"unable to load cohort {identifier!r}: {error}") from error
