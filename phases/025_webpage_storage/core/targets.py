"""Target loading, bundle validation, and partition assignment for Phase 2.5."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from defs.sql import (
    Select,
    SqlDialect,
    Table,
    col,
    make_sql_executor,
)

from .schemas import (
    DocumentLocator,
    FilingOccurrence,
    build_occurrence,
)

REQUIRED_LOCATOR_COLUMNS = (
    "document_locator_key",
    "representative_accession",
    "document_path",
    "archive_url",
    "form",
)
REQUIRED_TARGET_COLUMNS = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "document_path",
)
# Optional provenance column from catalogs implementing the full-submission
# fallback policy; older plan bundles simply omit it.
OPTIONAL_COLUMNS = ("document_path_source",)


def _read_parquet_rows(
    path: str | Path,
    columns: tuple[str, ...],
    view: str,
    optional: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    from defs.storage import parquet_column_names

    available = set(parquet_column_names(str(path)))
    missing_required = [column for column in columns if column not in available]
    if missing_required:
        raise ValueError(
            f"{view} parquet is missing required columns: {', '.join(missing_required)}"
        )
    projection = tuple(col(column) for column in columns)
    projection += tuple(col(column) for column in optional if column in available)
    executor = make_sql_executor(
        dialect=SqlDialect.DUCKDB,
        dataset_views={view: str(path)},
    )
    try:
        query = Select(
            source=Table(view),
            projection=projection,
        )
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def _validate_bundle(plan_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    manifest = plan_dir / "plan.json"
    locator_path = plan_dir / "locator_groups.parquet"
    if not manifest.is_file():
        raise FileNotFoundError(f"Phase 02 plan manifest not found: {manifest}")
    if not locator_path.is_file():
        raise FileNotFoundError(f"Phase 02 locator groups not found: {locator_path}")
    with manifest.open("r", encoding="utf-8") as stream:
        plan = json.load(stream)
    if not isinstance(plan, dict):
        raise ValueError("Phase 02 plan.json must contain an object")
    target_paths = sorted((plan_dir / "targets").glob("form=*/data.parquet"))
    if not target_paths:
        raise FileNotFoundError(
            f"Phase 02 target parquet files not found under {plan_dir / 'targets'}"
        )
    return locator_path, target_paths[0], plan


def load_targets(
    plan_dir: str | Path,
) -> tuple[list[DocumentLocator], list[FilingOccurrence], dict[str, Any]]:
    """Read and validate the published Phase 02 plan bundle."""
    root = Path(plan_dir)
    locator_path, _first_target_path, plan = _validate_bundle(root)
    locator_rows = _read_parquet_rows(
        locator_path,
        REQUIRED_LOCATOR_COLUMNS,
        "locator_groups",
        optional=OPTIONAL_COLUMNS,
    )
    target_paths = sorted((root / "targets").glob("form=*/data.parquet"))
    target_rows: list[dict[str, Any]] = []
    for target_path in target_paths:
        target_rows.extend(
            _read_parquet_rows(
                target_path,
                REQUIRED_TARGET_COLUMNS,
                "target_rows",
                optional=OPTIONAL_COLUMNS,
            )
        )
    if not locator_rows:
        return [], [], plan

    locators = [
        DocumentLocator(
            locator_key=str(row["document_locator_key"]),
            accession=str(row["representative_accession"]),
            document_path=str(row["document_path"]),
            archive_url=str(row["archive_url"]),
            form=str(row.get("form", "")),
            document_path_source=(
                None
                if row.get("document_path_source") is None
                else str(row["document_path_source"])
            ),
        )
        for row in locator_rows
    ]
    locator_by_key = {locator.locator_key: locator for locator in locators}
    occurrences: list[FilingOccurrence] = []
    for row in target_rows:
        key = str(row["document_locator_key"])
        locator = locator_by_key.get(key)
        if locator is None:
            raise ValueError(f"target references unknown document locator: {key}")
        target_source = (
            None
            if row.get("document_path_source") is None
            else str(row["document_path_source"])
        )
        if target_source != locator.document_path_source:
            raise ValueError(
                f"target document path provenance disagrees with locator group: {key}"
            )
        occurrence = build_occurrence(
            source_cik=str(row["source_cik"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            report_date=(
                None if row.get("report_date") is None else str(row["report_date"])
            ),
        )
        if occurrence.document_path != locator.document_path:
            raise ValueError(
                f"target document path disagrees with locator group: {key}"
            )
        occurrences.append(occurrence)

    del locator_rows
    del target_rows
    del locator_by_key
    return locators, occurrences, plan


def partition_locators(
    locators: list[DocumentLocator], partition_id: int, partition_count: int
) -> list[DocumentLocator]:
    """Deterministically slice locators into partition batches using round-robin distribution."""
    if partition_count < 1 or partition_id < 1 or partition_id > partition_count:
        raise ValueError("partition_id must be in the range 1..partition_count")
    ordered = sorted(locators, key=lambda locator: locator.locator_key)
    return [
        locator
        for index, locator in enumerate(ordered)
        if index % partition_count == partition_id - 1
    ]


def calculate_optimal_chunk_size(locator_count: int, workers: int = 1) -> int:
    """Calculate an optimal chunk size balancing concurrency and SQLite file overhead."""
    if locator_count <= 0:
        return 100
    target_chunks = max(1, workers * 4)
    computed = (locator_count + target_chunks - 1) // target_chunks
    return max(100, min(2500, computed))


__all__ = [
    "OPTIONAL_COLUMNS",
    "REQUIRED_LOCATOR_COLUMNS",
    "REQUIRED_TARGET_COLUMNS",
    "calculate_optimal_chunk_size",
    "load_targets",
    "partition_locators",
]
