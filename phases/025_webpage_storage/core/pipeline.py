"""End-to-end Phase 2.5 acquisition coordinator."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

from .chunk_worker import ChunkResult, process_chunk
from .fetcher import ArchiveFetcher, make_archive_fetcher
from .partition_merger import PartitionMergeResult, merge_partition
from .schemas import DocumentLocator, FilingOccurrence, build_occurrence

REQUIRED_LOCATOR_COLUMNS = (
    "document_locator_key",
    "representative_accession",
    "document_path",
    "archive_url",
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


def _read_parquet_rows(
    path: str | Path, columns: tuple[str, ...], view: str
) -> list[dict[str, Any]]:
    executor = make_sql_executor(
        dialect=SqlDialect.DUCKDB,
        dataset_views={view: str(path)},
    )
    try:
        query = Select(
            source=Table(view),
            projection=tuple(col(column) for column in columns),
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
        locator_path, REQUIRED_LOCATOR_COLUMNS, "locator_groups"
    )
    target_paths = sorted((root / "targets").glob("form=*/data.parquet"))
    target_rows: list[dict[str, Any]] = []
    for target_path in target_paths:
        target_rows.extend(
            _read_parquet_rows(target_path, REQUIRED_TARGET_COLUMNS, "target_rows")
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
    return locators, occurrences, plan


def _partition_locators(
    locators: list[DocumentLocator], partition_id: int, partition_count: int
) -> list[DocumentLocator]:
    if partition_count < 1 or partition_id < 1 or partition_id > partition_count:
        raise ValueError("partition_id must be in the range 1..partition_count")
    ordered = sorted(locators, key=lambda locator: locator.locator_key)
    return [
        locator
        for index, locator in enumerate(ordered)
        if index % partition_count == partition_id - 1
    ]


def run_partition(
    plan_dir: str | Path,
    output_dir: str | Path,
    *,
    mode: str = "fixture",
    fixture_paths: list[str | Path] | None = None,
    http_client=None,
    run_id: str = "local",
    partition_id: int = 1,
    partition_count: int = 1,
    chunk_size: int = 100,
    worker_id: str = "worker-00001",
    attempt_id: str = "attempt-00001",
    fetcher: ArchiveFetcher | None = None,
) -> dict[str, Any]:
    """Acquire one deterministic partition and merge its worker chunks."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    locators, occurrences, plan = load_targets(plan_dir)
    selected = _partition_locators(locators, partition_id, partition_count)
    occurrences_by_key: dict[str, list[FilingOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        for locator in selected:
            if (
                occurrence.accession == locator.accession
                and occurrence.document_path == locator.document_path
            ):
                occurrences_by_key[locator.locator_key].append(occurrence)
                break

    if fetcher is None:
        if mode.strip().lower() == "fixture" and not fixture_paths:
            raise ValueError("fixture mode requires fixture_paths")
        fetcher = make_archive_fetcher(mode, fixture_paths, http_client)

    run_paths = resolve_paths("webpage_storage", run_id)
    run_paths.ensure_run_layout()
    chunk_results: list[ChunkResult] = []
    try:
        for start in range(0, len(selected), chunk_size):
            chunk = selected[start : start + chunk_size]
            chunk_id = f"chunk-{start // chunk_size + 1:05d}"
            chunk_path = run_paths.worker_chunk_db(worker_id, attempt_id, chunk_id)
            run_paths.ensure_worker_layout(worker_id, attempt_id)
            chunk_occurrences = [
                occurrence
                for locator in chunk
                for occurrence in occurrences_by_key[locator.locator_key]
            ]
            chunk_results.append(
                process_chunk(
                    chunk_id,
                    worker_id,
                    chunk,
                    chunk_occurrences,
                    fetcher,
                    chunk_path,
                )
            )
    finally:
        close = getattr(fetcher, "close", None)
        if close is not None:
            close()

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    partition_name = (
        resolve_paths()
        .dataset_manifests(
            "webpage_storage", "filing_documents", f"partition-{partition_id:05d}"
        )
        .name
        + ".sqlite"
    )
    partition_path = output / partition_name
    merge_result: PartitionMergeResult = merge_partition(
        partition_path, [result.path for result in chunk_results]
    )
    return {
        "plan": plan,
        "partition_id": partition_id,
        "partition_count": partition_count,
        "locator_count": len(selected),
        "occurrence_count": sum(result.occurrence_count for result in chunk_results),
        "failures": [
            asdict(failure) for result in chunk_results for failure in result.failures
        ],
        "chunks": [asdict(result) for result in chunk_results],
        "merge": merge_result.to_dict(),
        "partition_db": str(partition_path),
    }


__all__ = ["load_targets", "run_partition"]
