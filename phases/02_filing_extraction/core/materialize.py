"""Materialize Phase 2 catalogs from a finalized Phase 1 artifact."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from defs.filing_identity import (
    document_locator_key,
    is_amendment_form,
    normalize_accession,
    occurrence_id,
    parse_archive_url,
)
from defs.runtime import (
    load_manifest,
    make_manifest,
    publish_manifest,
    resolve_paths,
)
from defs.runtime.resources import derive_resources
from defs.storage import (
    FinalizedArtifact,
    StorageError,
    canonical_json,
    force_reclaim_memory,
    load_json,
)

from .config import DEFAULT_SOURCE_BATCH_SIZE
from .schemas import (
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)

SOURCE = importlib.import_module("phases.01_metadata_extraction.core.schemas")

logger = logging.getLogger("filing_extraction.materialize")


def _emit(progress: Callable[[dict], None] | None, event: dict) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("materialize progress callback failed")


def _catalog_id(source_hash: str, config: dict) -> str:
    value = canonical_json([source_hash, SOURCE.SCHEMA_VERSION, SCHEMA_VERSION, config])
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _publish_file(source: Path, destination: Path) -> None:
    """Copy a validated staging file into its durable location atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(source) != _sha256(destination):
            raise StorageError(f"conflicting immutable output: {destination}")
        return
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_occurrence(cik, accession, path):
    try:
        return occurrence_id(cik or "", accession or "", path)
    except ValueError:
        return None


def _safe_locator(accession, path):
    try:
        return document_locator_key(accession or "", path)
    except ValueError:
        return None


def _partition_key(form):
    value = str(form or "").strip()
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value) or "_unknown"


def _register_identity_functions(artifact: FinalizedArtifact) -> None:
    artifact.register_function(
        "filing_accession", normalize_accession, parameters=[str], return_type=str
    )
    artifact.register_function(
        "filing_document_path",
        lambda value: (
            parse_archive_url(value).document_path if parse_archive_url(value) else None
        ),
        parameters=[str],
        return_type=str,
    )
    artifact.register_function(
        "filing_occurrence_id",
        _safe_occurrence,
        parameters=[str, str, str],
        return_type=str,
    )
    artifact.register_function(
        "filing_locator_key", _safe_locator, parameters=[str, str], return_type=str
    )
    artifact.register_function(
        "filing_is_amendment", is_amendment_form, parameters=[str], return_type=bool
    )
    artifact.register_function(
        "filing_partition_key", _partition_key, parameters=[str], return_type=str
    )


def materialize(
    source_artifact: str | None = None,
    output_root: str | None = None,
    *,
    source_manifest: str | None = None,
    progress: Callable[[dict], None] | None = None,
    source_batch_size: int | None = None,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | None = None,
) -> dict:
    source_batch_size = source_batch_size or DEFAULT_SOURCE_BATCH_SIZE
    if source_batch_size < 1:
        raise ValueError("source_batch_size must be >= 1")
    handoff = None
    if source_manifest:
        handoff = load_manifest(source_manifest)
        artifact_root = resolve_paths().artifacts_root
        source_artifact = str(artifact_root / handoff["artifact_path"])
    if not source_artifact:
        raise ValueError("source_artifact or source_manifest is required")
    if output_root is None:
        output_root = str(resolve_paths("filing_extraction").catalogs_root)
    configured_paths = resolve_paths("filing_extraction")
    configured_artifacts_root = configured_paths.project.artifacts_root.resolve()
    staging_root = Path(output_root).resolve()
    artifacts_root = (
        configured_artifacts_root
        if staging_root == configured_paths.catalogs_root.resolve()
        else staging_root.parent
    )
    source = Path(source_artifact).resolve()
    if any(part in {"chunks", "checkpoints", "workers"} for part in source.parts):
        raise StorageError(
            "Phase 2 requires a finalized artifact, not a chunk/checkpoint"
        )
    report = load_json(source.parent / "merge_report.json", default=None)
    resources = derive_resources(
        cli_overrides={"runtime.temp_directory": temp_directory}
        if temp_directory
        else None
    )
    effective_threads = threads if threads is not None else resources.threads
    effective_mem = memory_limit or resources.memory_limit
    effective_temp = resources.temp_directory

    with FinalizedArtifact(
        source_artifact,
        threads=effective_threads,
        memory_limit=effective_mem,
        temp_directory=effective_temp,
    ) as artifact:
        _register_identity_functions(artifact)
        if artifact.columns != SOURCE.SUBMISSION_METADATA_SCHEMA.names:
            raise StorageError(
                "source artifact columns do not match submission_metadata schema"
            )
        if report:
            if (
                report.get("artifact_sha256")
                and report["artifact_sha256"] != artifact.sha256
            ):
                raise StorageError(
                    "source artifact SHA-256 does not match merge report"
                )
            if (
                report.get("row_count") is not None
                and int(report["row_count"]) != artifact.count()
            ):
                raise StorageError(
                    "source artifact row count does not match merge report"
                )
        source_hash = artifact.sha256
        if handoff and handoff.get("artifact_sha256") != source_hash:
            raise StorageError(
                "source artifact SHA-256 does not match handoff manifest"
            )
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "validate_source",
                "rows": report["row_count"]
                if report and isinstance(report.get("row_count"), int)
                else None,
            },
        )
        catalog_id = _catalog_id(source_hash, {})
        root = Path(output_root).resolve() / catalog_id
        resolved_paths = resolve_paths(
            "filing_extraction", env={"ARTIFACTS_ROOT": str(artifacts_root)}
        )
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

        # Stage 1: Company Profiles (Column-Pruned Scalar Query)
        profile_cols = ", ".join(f'"{c}"' for c in PROFILE_COLUMNS[:-1])
        profile_query = (
            f"SELECT {profile_cols}, "
            f"'{PROFILE_SCHEMA_VERSION}' AS profile_schema_version "
            f"FROM {artifact.relation}"
        )
        profile_path = root / "company_profiles.parquet"
        profile_count = artifact.copy_query(profile_query, str(profile_path))
        profile_destination = (
            resolved_paths.project.dataset_manifests(
                "filing_extraction", "company_profiles"
            )
            / "company_profiles.parquet"
        )
        _publish_file(profile_path, profile_destination)
        handoff_root = artifacts_root
        profile_manifest = make_manifest(
            dataset="company_profiles",
            phase="filing_extraction",
            run_id=catalog_id,
            schema_version=PROFILE_SCHEMA_VERSION,
            artifact_path=str(profile_destination),
            artifacts_root=handoff_root,
            row_count=profile_count,
            upstream=(handoff["artifact_id"],) if handoff else (),
            provenance={
                "catalog_id": catalog_id,
                "source_artifact_sha256": source_hash,
            },
        )
        publish_manifest(profile_manifest, artifacts_root=handoff_root)
        _emit(
            progress,
            {"type": "merge_stage", "stage": "company_profiles", "rows": profile_count},
        )
        force_reclaim_memory()

        # Stage 2: Batched CIK Streaming into Form-Partitioned Parquet Files
        ciks = [
            r[0]
            for r in artifact.run(
                f"SELECT cik\n"
                f"FROM {artifact.relation}\n"
                f"WHERE cik IS NOT NULL\n"
                f"ORDER BY cik"
            )
        ]
        batch_count = (
            max(1, (len(ciks) + source_batch_size - 1) // source_batch_size)
            if ciks
            else 1
        )

        metadata = {
            "source_artifact_sha256": source_hash,
            "input_fingerprint": report.get("input_fingerprint", "") if report else "",
            "schema_version": SOURCE.SCHEMA_VERSION,
            "catalog_id": catalog_id,
        }
        metadata_sql = ", ".join(
            f"'{value}' AS \"{key}\"" for key, value in metadata.items()
        )
        target_root = root / "filing_targets"
        target_root.mkdir(parents=True, exist_ok=True)
        final_target_root = resolved_paths.project.dataset_manifests(
            "filing_extraction", "filing_targets"
        )
        staging_partitions_dir = root / ".staging_partitions"
        if staging_partitions_dir.exists():
            shutil.rmtree(staging_partitions_dir, ignore_errors=True)
        staging_partitions_dir.mkdir(parents=True, exist_ok=True)

        # Form Discovery & Initial Event (native columnar streaming)
        raw_forms = [
            r[0]
            for r in artifact.run(
                f"SELECT DISTINCT unnest(filings).form\n"
                f"FROM {artifact.relation}\n"
                f"WHERE filings IS NOT NULL"
            )
            if r[0]
        ]
        all_partition_keys = sorted({_partition_key(f) for f in raw_forms if f})
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "discover_forms",
                "forms": len(all_partition_keys),
                "total_units": len(all_partition_keys) + 5,
                "source_batch_size": source_batch_size,
            },
        )
        if ciks:
            for b_idx in range(batch_count):
                b_start = b_idx * source_batch_size
                b_end = min(b_start + source_batch_size, len(ciks))
                b_ciks = ciks[b_start:b_end]
                start_cik, end_cik = b_ciks[0], b_ciks[-1]

                batch_staging_dir = staging_partitions_dir / f"batch_{b_idx}"
                batch_query = f"""
                    SELECT 
                        filing_occurrence_id(t.cik, filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS occurrence_id,
                        filing_locator_key(filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS document_locator_key,
                        t.cik AS source_cik,
                        filing_accession(filing.accession_number_normalized) AS accession,
                        filing.form,
                        filing_partition_key(filing.form) AS form_partition_key,
                        filing_is_amendment(filing.form) AS is_amendment,
                        filing.filing_date,
                        filing.report_date,
                        filing.acceptance_datetime,
                        filing.primary_document,
                        filing.primary_doc_description,
                        filing_document_path(filing.archive_url) AS document_path,
                        filing.archive_url,
                        filing.source_section,
                        filing.source_file,
                        filing.source_array_index,
                        filing.size AS reported_size,
                        filing.is_xbrl,
                        filing.is_inline_xbrl,
                        filing.is_xbrl_numeric,
                        {metadata_sql}
                    FROM {artifact.relation} AS t, LATERAL unnest(t.filings) AS u(filing)
                    WHERE t.cik >= ? AND t.cik <= ?
                      AND filing_accession(filing.accession_number_normalized) IS NOT NULL
                      AND filing_document_path(filing.archive_url) IS NOT NULL
                      AND filing.primary_document IS NOT NULL
                      AND filing.form IS NOT NULL
                """
                artifact.copy_partitioned_query(
                    batch_query,
                    str(batch_staging_dir),
                    partition_by="form_partition_key",
                    parameters=[start_cik, end_cik],
                )
                _emit(
                    progress,
                    {
                        "type": "batch_done",
                        "batch": b_idx + 1,
                        "total_batches": batch_count,
                        "cik_start": start_cik,
                        "cik_end": end_cik,
                        "rows": b_end - b_start,
                        "total_ciks": len(ciks),
                        "ciks_done": b_end,
                    },
                )
                force_reclaim_memory()

        counts: dict[str, int] = {}
        target_artifact_ids: dict[str, str] = {}
        form_partition_mapping: dict[str, str] = {}

        all_partition_keys = sorted(
            {
                p.name.split("=", 1)[1]
                for p in staging_partitions_dir.glob("batch_*/form_partition_key=*")
                if "=" in p.name
            }
        )

        for part_key in all_partition_keys:
            dest_dir = target_root / f"form={part_key}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / "data.parquet"
            if dest_file.exists():
                dest_file.unlink()

            parquet_files = sorted(
                staging_partitions_dir.glob(
                    f"batch_*/form_partition_key={part_key}/*.parquet"
                )
            )
            if not parquet_files:
                continue

            if len(parquet_files) == 1:
                shutil.copyfile(parquet_files[0], dest_file)
            else:
                file_list = ", ".join(f"'{p}'" for p in parquet_files)
                concat_q = (
                    f"COPY (\n"
                    f"  SELECT *\n"
                    f"  FROM read_parquet([{file_list}])\n"
                    f") TO '{dest_file}' (FORMAT PARQUET, COMPRESSION 'zstd')"
                )
                artifact.run(concat_q)

            # Retrieve form and count
            group_q = (
                f"SELECT form, COUNT(*)\n"
                f"FROM read_parquet('{dest_file}')\n"
                f"GROUP BY form"
            )
            res = artifact.run(group_q)
            total_count = 0
            for form_name, row_cnt in res:
                form_name_str = str(form_name)
                counts[form_name_str] = int(row_cnt)
                form_partition_mapping[form_name_str] = part_key
                total_count += int(row_cnt)

            final_dest_file = final_target_root / f"form={part_key}" / "data.parquet"
            _publish_file(dest_file, final_dest_file)
            target_manifest = make_manifest(
                dataset="filing_targets",
                phase="filing_extraction",
                run_id=catalog_id,
                schema_version=TARGET_SCHEMA_VERSION,
                artifact_path=str(final_dest_file),
                artifacts_root=handoff_root,
                row_count=total_count,
                partition="",
                upstream=(handoff["artifact_id"],) if handoff else (),
                provenance={
                    "catalog_id": catalog_id,
                    "source_artifact_sha256": source_hash,
                    "form_partition_key": part_key,
                },
            )
            publish_manifest(target_manifest, artifacts_root=handoff_root)
            for form_name, row_cnt in res:
                form_name_str = str(form_name)
                target_artifact_ids[form_name_str] = target_manifest["artifact_id"]
                _emit(
                    progress,
                    {
                        "type": "merge_stage",
                        "stage": f"targets:{form_name_str}",
                        "rows": int(row_cnt),
                    },
                )

        shutil.rmtree(staging_partitions_dir, ignore_errors=True)
        force_reclaim_memory()

        # Stage 3: Occurrence Sources (Streaming Distinct Query from Flat Targets)
        target_files = sorted(target_root.glob("form=*/data.parquet"))
        if target_files:
            file_list = ", ".join(f"'{p}'" for p in target_files)
            sources_query = (
                f"SELECT DISTINCT\n"
                f"    occurrence_id, source_cik, accession, document_path,\n"
                f"    source_section, source_file, source_array_index\n"
                f"FROM read_parquet([{file_list}])"
            )
        else:
            sources_query = (
                f"SELECT DISTINCT\n"
                f"    filing_occurrence_id(t.cik, filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS occurrence_id,\n"
                f"    t.cik AS source_cik, filing_accession(filing.accession_number_normalized) AS accession,\n"
                f"    filing_document_path(filing.archive_url) AS document_path,\n"
                f"    filing.source_section, filing.source_file, filing.source_array_index\n"
                f"FROM {artifact.relation} AS t, LATERAL unnest(t.filings) AS u(filing)\n"
                f"WHERE filing_accession(filing.accession_number_normalized) IS NOT NULL\n"
                f"  AND filing_document_path(filing.archive_url) IS NOT NULL"
            )
        sources_path = root / "filing_occurrence_sources.parquet"
        source_count = artifact.copy_query(sources_query, str(sources_path))
        sources_destination = (
            resolved_paths.project.dataset_manifests(
                "filing_extraction", "filing_occurrence_sources"
            )
            / "filing_occurrence_sources.parquet"
        )
        _publish_file(sources_path, sources_destination)
        sources_manifest = make_manifest(
            dataset="filing_occurrence_sources",
            phase="filing_extraction",
            run_id=catalog_id,
            schema_version=TARGET_SCHEMA_VERSION,
            artifact_path=str(sources_destination),
            artifacts_root=handoff_root,
            row_count=source_count,
            upstream=(handoff["artifact_id"],) if handoff else (),
            provenance={
                "catalog_id": catalog_id,
                "source_artifact_sha256": source_hash,
            },
        )
        publish_manifest(sources_manifest, artifacts_root=handoff_root)
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "occurrence_sources",
                "rows": source_count,
            },
        )
        force_reclaim_memory()

        manifest = {
            "catalog_id": catalog_id,
            "source_artifact": handoff["artifact_path"] if handoff else source.name,
            "source_artifact_sha256": source_hash,
            "source_schema_version": SOURCE.SCHEMA_VERSION,
            "catalog_schema_version": SCHEMA_VERSION,
            "profile_schema_version": PROFILE_SCHEMA_VERSION,
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "form_partitions": counts,
            "artifact_ids": {
                "company_profiles": profile_manifest["artifact_id"],
                "filing_occurrence_sources": sources_manifest["artifact_id"],
                **target_artifact_ids,
            },
            "form_partition_mapping": form_partition_mapping,
            "materializer_version": SCHEMA_VERSION,
            "source_batch_size": source_batch_size,
            "batch_count": batch_count,
            "source_artifact_id": handoff.get("artifact_id") if handoff else None,
            "handoff_mode": "manifest" if handoff else "legacy_merge_report",
        }
        report_payload = {
            "catalog_id": catalog_id,
            "source_artifact_sha256": source_hash,
            "target_counts": counts,
            "malformed_records": "invalid accession, archive URL, or primary document records are excluded from targets",
            "source_batch_size": source_batch_size,
            "batch_count": batch_count,
        }
        (root / "materialization_report.json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "publish_manifest",
                "rows": sum(counts.values()),
            },
        )
        shutil.rmtree(root, ignore_errors=True)
        return manifest
