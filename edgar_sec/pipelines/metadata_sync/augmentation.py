"""Delta augmentation against a published snapshot.

Augmentation plans work only for CIKs the base snapshot does not already
contain. The published base is never refetched: delta chunks are merged with
the existing snapshot Parquet, so a snapshot that already holds N CIKs and
receives K new ones ends with N+K rows and only K network fetches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
)
from edgar_sec.infra.storage.duckdb import (
    concat_to_parquet,
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import (
    count_parquet_rows,
    read_parquet_schema,
    read_parquet_table,
)

from .manifest import InputManifest, read_cik_manifest
from .merger import MergeError, MergeReport, publish_snapshot
from .paths import MetadataPaths, resolve_run_paths
from .planner import build_plan, write_plan
from .sec_client import SubmissionsClient
from .worker import run_chunk

__all__ = [
    "AugmentResult",
    "augment",
    "augment_from_manifest",
    "base_snapshot_ciks",
    "plan_delta",
]


@dataclass(frozen=True, slots=True)
class AugmentResult:
    """Outcome of one augmentation run."""

    base_snapshot_id: str
    new_snapshot_id: str
    base_row_count: int
    delta_row_count: int
    refetched_ciks: tuple[str, ...]
    report: MergeReport

    @property
    def total_row_count(self) -> int:
        """Rows in the newly published snapshot."""
        return self.report.row_count


def base_snapshot_ciks(metadata_paths: MetadataPaths, snapshot_id: str) -> set[str]:
    """Read the CIK set already present in a published snapshot."""
    path = metadata_paths.snapshot_file(snapshot_id)
    if not path.is_file():
        raise FileNotFoundError(f"base snapshot not found: {path}")
    table = read_parquet_table(path, columns=["cik"])
    return {str(value) for value in table.column("cik").to_pylist() if value}


def plan_delta(
    manifest: InputManifest,
    base_ciks: set[str],
    *,
    chunk_size: int,
    partition_count: int = DEFAULT_PARTITION_COUNT,
) -> dict[str, Any]:
    """Build a plan covering only CIKs absent from the base snapshot."""
    delta_ciks = tuple(cik for cik in manifest.ciks if cik not in base_ciks)
    if not delta_ciks:
        return {
            "plan_id": "",
            "cik_padded": [],
            "chunks": [],
            "partitions": [],
            "row_count": 0,
            "is_empty": True,
        }
    delta_manifest = InputManifest(
        input_name=manifest.input_name,
        input_path=manifest.input_path,
        input_fingerprint=manifest.input_fingerprint,
        ciks=delta_ciks,
        names=tuple(manifest.name_for(cik) for cik in delta_ciks),
        skipped=manifest.skipped,
        duplicate_count=manifest.duplicate_count,
    )
    plan = build_plan(
        delta_manifest, chunk_size=chunk_size, partition_count=partition_count
    )
    plan["base_ciks_retained"] = len(base_ciks)
    plan["is_empty"] = False
    return plan


def augment(
    client: SubmissionsClient,
    manifest: InputManifest,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    partition_count: int = DEFAULT_PARTITION_COUNT,
    workers: int | None = None,
) -> AugmentResult:
    """Augment a published snapshot with any newly requested CIKs.

    The base snapshot file is merged alongside the delta checkpoints, so base
    CIKs are carried forward untouched and are never refetched.
    """
    base_path = metadata_paths.snapshot_file(base_snapshot_id)
    if not base_path.is_file():
        raise FileNotFoundError(f"base snapshot not found: {base_path}")
    base_ciks = base_snapshot_ciks(metadata_paths, base_snapshot_id)
    base_rows = count_parquet_rows(base_path)

    plan = plan_delta(
        manifest, base_ciks, chunk_size=chunk_size, partition_count=partition_count
    )
    if plan["is_empty"]:
        raise MergeError(
            "augmentation requested no work: every requested CIK is already "
            f"present in base snapshot {base_snapshot_id}"
        )

    run_paths = resolve_run_paths(plan["plan_id"], metadata_paths.artifacts_root)
    write_plan(plan, run_paths)

    refetched: list[str] = []
    for chunk in plan["chunks"]:
        result = run_chunk(
            client,
            plan,
            run_paths,
            int(chunk["chunk_id"]),
            snapshot_id=new_snapshot_id,
            workers=workers,
        )
        if not result.skipped_existing:
            refetched.extend(chunk["cik_padded"])

    delta_paths = [
        str(run_paths.chunk_file(int(c["chunk_id"]))) for c in plan["chunks"]
    ]
    inputs = [str(base_path), *delta_paths]
    output_path = metadata_paths.snapshot_file(new_snapshot_id)

    report = MergeReport(
        snapshot_id=new_snapshot_id,
        chunk_count=len(plan["chunks"]),
        plan_id=plan["plan_id"],
        input_fingerprint=plan["input_fingerprint"],
    )

    con = connect()
    try:
        if find_null_keys(con, inputs, "cik"):
            raise MergeError("augmentation rejected: null CIK in merged inputs")
        duplicates = find_duplicate_keys(con, inputs, "cik")
        if duplicates:
            raise MergeError(
                f"augmentation rejected: CIKs appear in both base and delta: "
                f"{duplicates}"
            )
        report.duplicate_accessions = find_duplicate_nested_values(
            con, inputs, "filings", "accession_number"
        )
        if report.duplicate_accessions:
            report.warnings.append(
                f"{len(report.duplicate_accessions)} duplicate accession(s) observed; "
                "accession is not globally unique"
            )
        row_count = concat_to_parquet(con, inputs, output_path, order_by=("cik",))
    finally:
        con.close()

    expected = base_rows + int(plan["row_count"])
    if row_count != expected:
        raise MergeError(
            f"augmentation rejected: merged row count {row_count} "
            f"!= expected {expected} ({base_rows} base + {plan['row_count']} delta)"
        )
    if not read_parquet_schema(output_path).equals(
        SUBMISSION_METADATA_SCHEMA, check_metadata=False
    ):
        raise MergeError("augmentation rejected: published artifact schema drifted")

    merged_ciks = read_parquet_table(output_path, columns=["cik"])
    actual = {str(v) for v in merged_ciks.column("cik").to_pylist() if v}
    if actual != base_ciks | set(plan["cik_padded"]):
        raise MergeError("augmentation rejected: merged CIK set differs from union")

    report.row_count = row_count
    report.output_path = str(output_path)
    report.artifact_sha256 = file_sha256(output_path)
    from .planner import utc_now_iso

    report.merged_at = utc_now_iso()
    publish_snapshot(report, metadata_paths)

    return AugmentResult(
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        base_row_count=base_rows,
        delta_row_count=int(plan["row_count"]),
        refetched_ciks=tuple(refetched),
        report=report,
    )


def augment_from_manifest(
    client: SubmissionsClient,
    input_path: str,
    metadata_paths: MetadataPaths,
    **kwargs: Any,
) -> AugmentResult:
    """Convenience wrapper reading the manifest from disk before augmenting."""
    manifest = read_cik_manifest(input_path)
    return augment(client, manifest, metadata_paths, **kwargs)
