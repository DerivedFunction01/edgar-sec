"""Explicit offline scale check for the S4 progress journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
import sys
import time
from pathlib import Path

from edgar_sec.domain.document_inventory.models import (
    InventoryEntry,
    IndexWorkItem,
    ParsedIndexPage,
    ParserDiagnostics,
    inventory_entry_id,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.storage.parquet import count_parquet_rows

from .checkpoint import AttemptWriters, finalize_attempt, validate_committed_chunk
from .paths import inventory_paths, inventory_run_paths
from .progress import open_progress
from .run_manifest import iter_work_order_chunks, write_run_manifest, write_work_order

DEFAULT_ROWS = 236_000
MAX_ROWS = 236_000
MAX_CHUNK_SIZE = 10_000
MAX_ENTRIES_PER_ACCESSION = 10
DEFAULT_OUTPUT_MIB = 8_192
_ESTIMATED_BYTES_PER_ACCESSION = 32 * 1024
_MIB = 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgar_sec.pipelines.document_inventory.progress_scale_check",
        description="Run the explicitly opted-in offline S4 progress simulation",
    )
    parser.add_argument(
        "--run-simulation",
        action="store_true",
        required=True,
        help="required opt-in; processes synthetic rows and writes only to --scratch",
    )
    parser.add_argument(
        "--scratch", required=True, help="empty, dedicated scratch directory"
    )
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="rows per chunk (default: runtime.chunk_size)",
    )
    parser.add_argument("--entries-per-accession", type=int, default=3)
    parser.add_argument("--max-output-mib", type=int, default=DEFAULT_OUTPUT_MIB)
    return parser


def _validate_arguments(args: argparse.Namespace) -> tuple[Path, int, int]:
    settings = resolve_runtime_settings()
    scratch = Path(args.scratch).expanduser().resolve()
    configured_artifacts = settings.artifacts_root.expanduser().resolve()
    if (
        scratch == Path.cwd().resolve()
        or scratch == configured_artifacts
        or scratch.is_relative_to(configured_artifacts)
        or configured_artifacts.is_relative_to(scratch)
    ):
        raise ValueError(
            "--scratch must be separate from the configured artifacts root"
        )
    if scratch == Path(scratch.anchor) or not scratch.parent.is_dir():
        raise ValueError(
            "--scratch must have an existing parent and cannot be a filesystem root"
        )
    if scratch.exists() and (not scratch.is_dir() or any(scratch.iterdir())):
        raise ValueError("--scratch must be a new or empty directory")
    if args.rows < 1 or args.rows > MAX_ROWS:
        raise ValueError(f"--rows must be between 1 and {MAX_ROWS}")
    chunk_size = (
        settings.default_chunk_size if args.chunk_size is None else args.chunk_size
    )
    if chunk_size < 1 or chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(f"--chunk-size must be between 1 and {MAX_CHUNK_SIZE}")
    if not 1 <= args.entries_per_accession <= MAX_ENTRIES_PER_ACCESSION:
        raise ValueError(
            f"--entries-per-accession must be between 1 and {MAX_ENTRIES_PER_ACCESSION}"
        )
    if args.max_output_mib < 1:
        raise ValueError("--max-output-mib must be positive")
    estimated_bytes = args.rows * _ESTIMATED_BYTES_PER_ACCESSION
    if estimated_bytes > args.max_output_mib * _MIB:
        raise ValueError(
            f"estimated scratch output ({estimated_bytes / _MIB:.0f} MiB) exceeds "
            f"--max-output-mib ({args.max_output_mib} MiB)"
        )
    return scratch, chunk_size, estimated_bytes


def _work_items(rows: int):
    for ordinal in range(1, rows + 1):
        accession = AccessionNumber.from_any(f"000000000126{ordinal:06d}")
        yield IndexWorkItem(
            accession,
            f"https://example.test/Archives/edgar/data/1/{accession}/{accession}-index.htm",
        )


def _synthetic_result(
    item: IndexWorkItem, entries_per_accession: int
) -> ParsedIndexPage:
    accession = item.accession
    digest = hashlib.sha256(str(accession).encode("ascii")).hexdigest()
    entries = tuple(
        InventoryEntry(
            entry_id=inventory_entry_id(accession, "document_format", ordinal, digest),
            accession=accession,
            table_kind="document_format",
            row_ordinal=ordinal,
            sequence=ordinal,
            document_type="10-K" if ordinal == 1 else "EX-10.1",
            document_label=f"document-{ordinal}.htm",
            description=f"Synthetic filing exhibit {ordinal}",
            filename=f"document-{ordinal}.htm",
            href=f"/Archives/edgar/data/1/{accession}/document-{ordinal}.htm",
            archive_url=(
                f"https://www.sec.gov/Archives/edgar/data/1/"
                f"{accession}/document-{ordinal}.htm"
            ),
            byte_size=4096 + ordinal * 257,
        )
        for ordinal in range(1, entries_per_accession + 1)
    )
    return ParsedIndexPage(
        accession=accession,
        source_url=item.index_url,
        page_sha256=digest,
        entries=entries,
        bundle_url=None,
        bundle_size=None,
        xbrl_candidate_url=None,
        diagnostics=ParserDiagnostics((), 0),
    )


def _directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _record_items(progress, items, entries_per_accession: int) -> tuple[int, float]:
    transactions = 0
    started = time.perf_counter()
    for item in items:
        progress.record(
            _synthetic_result(item, entries_per_accession), index_url=item.index_url
        )
        transactions += 1
    return transactions, time.perf_counter() - started


def run_simulation(
    scratch: Path,
    *,
    rows: int,
    chunk_size: int,
    entries_per_accession: int,
    max_output_mib: int,
    profile: RuntimeResourceProfile,
) -> dict[str, object]:
    run_id = f"progress-scale-{time.time_ns()}"
    paths = inventory_run_paths(scratch, run_id)
    work_order = paths.work_order_path()
    started = time.perf_counter()
    identity = write_work_order(work_order, _work_items(rows))
    if identity.row_count != rows:
        raise RuntimeError(
            f"work-order row mismatch: expected {rows}, got {identity.row_count}"
        )
    run = write_run_manifest(
        paths,
        parent_snapshot_id="synthetic-parent",
        canonical_cohort_id="synthetic-cohort",
        source_identity="synthetic-work-order",
        parser_version="synthetic-progress-scale-v1",
        chunk_size=chunk_size,
        refresh_mode="normal",
        fetch_mode="live",
        fixture_id=None,
        work_order_path=work_order,
    )

    transaction_count = 0
    transaction_seconds = 0.0
    outcome_count = 0
    entry_count = 0
    recovered_rows = 0
    chunks = 0
    for chunk, members in iter_work_order_chunks(
        work_order, chunk_size=chunk_size, work_order_version=run.work_order_version
    ):
        chunks += 1
        progress = open_progress(paths, chunk, run, profile=profile)
        try:
            missing = progress.completed_accessions(members)
            if chunks == 1:
                split = len(members) // 2
                first, elapsed = _record_items(
                    progress, members[:split], entries_per_accession
                )
                transaction_count += first
                transaction_seconds += elapsed
                recovered_rows = first
                progress.close()
                progress = open_progress(paths, chunk, run, profile=profile)
                missing = progress.completed_accessions(members)
                if len(missing) != len(members) - split:
                    raise RuntimeError(
                        "partial progress recovery returned an incorrect remainder"
                    )
            if missing:
                missing_set = set(missing)
                pending = tuple(
                    item for item in members if str(item.accession) in missing_set
                )
                recorded, elapsed = _record_items(
                    progress, pending, entries_per_accession
                )
                transaction_count += recorded
                transaction_seconds += elapsed
            if progress.completed_accessions(members):
                raise RuntimeError(
                    f"chunk {chunk.chunk_id} is incomplete after recording"
                )
            expected_entries = len(members) * entries_per_accession
            if progress.counts() != (len(members), 0, expected_entries):
                raise RuntimeError(
                    f"progress row counts are incorrect in {chunk.chunk_id}"
                )
            attempt_id = progress.attempt_id
            writers = AttemptWriters(paths, chunk.chunk_id, attempt_id)
            try:
                progress.export(writers)
            finally:
                writers.close()
            progress.close()
            progress = None
            manifest = finalize_attempt(
                paths,
                chunk.chunk_id,
                attempt_id,
                membership=tuple(str(item.accession) for item in members),
                run=run,
            )
            validation = validate_committed_chunk(
                paths, chunk.chunk_id, run=run, chunk=chunk
            )
            if not validation.valid or validation.manifest is None:
                raise RuntimeError(
                    f"committed chunk failed validation: {validation.reason}"
                )
            if (
                manifest.outcomes_rows != len(members)
                or manifest.entries_rows != expected_entries
            ):
                raise RuntimeError(
                    f"Parquet row counts are incorrect in {chunk.chunk_id}"
                )
            outcome_path = paths.attempt_outcomes_path(chunk.chunk_id, attempt_id)
            entry_path = paths.attempt_entries_path(chunk.chunk_id, attempt_id)
            if count_parquet_rows(outcome_path) != len(members):
                raise RuntimeError(
                    f"outcome Parquet row count is incorrect in {chunk.chunk_id}"
                )
            if count_parquet_rows(entry_path) != expected_entries:
                raise RuntimeError(
                    f"entry Parquet row count is incorrect in {chunk.chunk_id}"
                )
            outcome_count += manifest.outcomes_rows
            entry_count += manifest.entries_rows
        finally:
            if progress is not None:
                progress.close()
        scratch_bytes = _directory_size(scratch)
        if scratch_bytes > max_output_mib * _MIB:
            raise RuntimeError(
                f"scratch output exceeded its {max_output_mib} MiB bound at chunk {chunks}"
            )
        if chunks % 25 == 0:
            print(f"completed {chunks} chunks / {outcome_count} outcomes", flush=True)

    elapsed_seconds = time.perf_counter() - started
    if transaction_count != rows or outcome_count != rows:
        raise RuntimeError(
            "final outcome/transaction count does not match the work order"
        )
    expected_entries = rows * entries_per_accession
    if entry_count != expected_entries:
        raise RuntimeError("final entry count does not match the synthetic work order")
    if inventory_paths(scratch).catalog_file.exists():
        raise RuntimeError("scale check unexpectedly created a snapshot catalog")

    duckdb_bytes = sum(path.stat().st_size for path in scratch.rglob("*.duckdb"))
    parquet_bytes = sum(path.stat().st_size for path in scratch.rglob("*.parquet"))
    return {
        "status": "passed",
        "rows": rows,
        "chunks": chunks,
        "chunk_size": chunk_size,
        "entries_per_accession": entries_per_accession,
        "transactions": transaction_count,
        "transaction_throughput_per_second": round(
            transaction_count / transaction_seconds if transaction_seconds else 0.0, 2
        ),
        "transaction_seconds": round(transaction_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "peak_rss_mib": round(_peak_rss_bytes() / _MIB, 2),
        "duckdb_bytes": duckdb_bytes,
        "parquet_bytes": parquet_bytes,
        "scratch_bytes": _directory_size(scratch),
        "outcome_rows": outcome_count,
        "entry_rows": entry_count,
        "recovered_partial_rows": recovered_rows,
        "recovery_validated": recovered_rows > 0,
        "committed_chunks_validated": chunks,
        "broker_calls": 0,
        "network_access": "none",
        "snapshot_published": False,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_cores": profile.cpu_cores,
            "duckdb_threads": profile.threads,
            "duckdb_memory_limit": profile.memory_limit,
            "available_memory_bytes": profile.available_memory_bytes,
            "worker_memory_mib": profile.worker_memory_mib,
            "runtime_chunk_size": resolve_runtime_settings().default_chunk_size,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scratch, chunk_size, estimated_bytes = _validate_arguments(args)
        free_bytes = shutil.disk_usage(scratch.parent).free
        if free_bytes < estimated_bytes * 2:
            raise ValueError(
                f"insufficient free disk for bounded estimate: estimated "
                f"{estimated_bytes / _MIB:.0f} MiB, available {free_bytes / _MIB:.0f} MiB"
            )
        scratch.mkdir(parents=True, exist_ok=True)
        profile = derive_resources(
            cli_overrides={"runtime.temp_directory": str(scratch / "duckdb-temp")}
        )
        minimum_available = profile.worker_memory_mib * _MIB
        if profile.available_memory_bytes < minimum_available:
            raise ValueError(
                "available memory is below the configured per-worker budget; "
                f"available {profile.available_memory_bytes / _MIB:.0f} MiB, "
                f"configured worker budget {profile.worker_memory_mib} MiB, "
                f"estimated disk output {estimated_bytes / _MIB:.0f} MiB"
            )
        result = run_simulation(
            scratch,
            rows=args.rows,
            chunk_size=chunk_size,
            entries_per_accession=args.entries_per_accession,
            max_output_mib=args.max_output_mib,
            profile=profile,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
