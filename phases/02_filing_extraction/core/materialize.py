"""Materialize Phase 2 catalogs from a finalized Phase 1 artifact."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from defs.filing_identity import (
    canonical_json,
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
from defs.storage import FinalizedArtifact, StorageError

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


def _load_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


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
) -> dict:
    handoff = None
    if source_manifest:
        handoff = load_manifest(source_manifest)
        artifact_root = resolve_paths().artifacts_root
        source_artifact = str(artifact_root / handoff["artifact_path"])
    if not source_artifact:
        raise ValueError("source_artifact or source_manifest is required")
    if output_root is None:
        output_root = str(resolve_paths("filing_extraction").phase_root / "catalogs")
    source = Path(source_artifact).resolve()
    if any(part in {"chunks", "checkpoints", "workers"} for part in source.parts):
        raise StorageError(
            "Phase 2 requires a finalized artifact, not a chunk/checkpoint"
        )
    report = _load_json(source.parent / "merge_report.json")
    with FinalizedArtifact(source_artifact) as artifact:
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
        manifest_path = root / "catalog_manifest.json"
        if manifest_path.exists():
            existing = _load_json(manifest_path)
            if existing and existing.get("source_artifact_sha256") == source_hash:
                return existing
        root.mkdir(parents=True, exist_ok=True)
        profile_query = (
            f"SELECT {', '.join('"' + c + '"' for c in PROFILE_COLUMNS[:-1])}, "
            f"'{PROFILE_SCHEMA_VERSION}' AS profile_schema_version "
            f'FROM {artifact.relation} ORDER BY "cik"'
        )
        profile_path = root / "company_profiles.parquet"
        profile_count = artifact.copy_query(profile_query, str(profile_path))
        configured_root = Path(resolve_paths().artifacts_root).resolve()
        handoff_root = (
            configured_root
            if profile_path.resolve().is_relative_to(configured_root)
            else Path(output_root).resolve().parent
        )
        profile_manifest = make_manifest(
            dataset="company_profiles",
            phase="filing_extraction",
            run_id=catalog_id,
            schema_version=PROFILE_SCHEMA_VERSION,
            artifact_path=str(profile_path),
            artifacts_root=handoff_root,
            row_count=profile_count,
            upstream=(handoff["artifact_id"],) if handoff else (),
        )
        publish_manifest(profile_manifest, artifacts_root=handoff_root)
        _emit(
            progress,
            {"type": "merge_stage", "stage": "company_profiles", "rows": profile_count},
        )
        target_root = root / "filing_targets"
        forms = [
            row[0]
            for row in artifact.run(
                f"SELECT DISTINCT filing.form FROM {artifact.relation} AS t, LATERAL unnest(t.filings) AS u(filing) WHERE filing.form IS NOT NULL ORDER BY 1"
            )
        ]
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "discover_forms",
                "forms": len(forms),
                "total_units": len(forms) + 5,
            },
        )
        counts = {}
        target_artifact_ids = {}
        for form in forms:
            partition = re.sub(r"[^A-Za-z0-9_.-]", "_", form) or "_unknown"
            output = target_root / f"form={partition}" / "data.parquet"
            metadata = {
                "source_artifact_sha256": source_hash,
                "input_fingerprint": report.get("input_fingerprint", "")
                if report
                else "",
                "schema_version": SOURCE.SCHEMA_VERSION,
                "catalog_id": catalog_id,
            }
            metadata_sql = ", ".join(
                f"'{value}' AS \"{key}\"" for key, value in metadata.items()
            )
            target_query = f"""
                SELECT filing_occurrence_id(t.cik, filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS occurrence_id,
                filing_locator_key(filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS document_locator_key,
                t.cik AS source_cik, filing_accession(filing.accession_number_normalized) AS accession, filing.form,
                filing_partition_key(filing.form) AS form_partition_key, filing_is_amendment(filing.form) AS is_amendment,
                filing.filing_date, filing.report_date, filing.acceptance_datetime, filing.primary_document,
                filing.primary_doc_description, filing_document_path(filing.archive_url) AS document_path,
                filing.archive_url, filing.source_section, filing.source_file, filing.source_array_index,
                filing.size AS reported_size, filing.is_xbrl, filing.is_inline_xbrl, filing.is_xbrl_numeric,
                {metadata_sql}
                FROM {artifact.relation} AS t, LATERAL unnest(t.filings) AS u(filing)
                WHERE filing.form = ? AND filing_accession(filing.accession_number_normalized) IS NOT NULL
                AND filing_document_path(filing.archive_url) IS NOT NULL AND filing.primary_document IS NOT NULL
                ORDER BY t.cik, accession, document_path
            """
            count = artifact.copy_query(target_query, str(output), [form])
            if count:
                counts[form] = count
                target_manifest = make_manifest(
                    dataset="filing_targets",
                    phase="filing_extraction",
                    run_id=catalog_id,
                    schema_version=TARGET_SCHEMA_VERSION,
                    artifact_path=str(output),
                    artifacts_root=handoff_root,
                    row_count=count,
                    partition=partition,
                    upstream=(handoff["artifact_id"],) if handoff else (),
                )
                publish_manifest(target_manifest, artifacts_root=handoff_root)
                target_artifact_ids[form] = target_manifest["artifact_id"]
            elif output.exists():
                output.unlink()
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"targets:{form}",
                    "rows": counts.get(form, 0),
                },
            )
        source_fields = """
            filing_occurrence_id(t.cik, filing_accession(filing.accession_number_normalized), filing_document_path(filing.archive_url)) AS occurrence_id,
            t.cik AS source_cik, filing_accession(filing.accession_number_normalized) AS accession,
            filing_document_path(filing.archive_url) AS document_path,
            filing.source_section, filing.source_file, filing.source_array_index
        """
        sources_path = root / "filing_occurrence_sources.parquet"
        sources_query = f"""
            SELECT {source_fields}
            FROM {artifact.relation} AS t, LATERAL unnest(t.filings) AS u(filing)
            WHERE filing_accession(filing.accession_number_normalized) IS NOT NULL
              AND filing_document_path(filing.archive_url) IS NOT NULL
            ORDER BY 2, 3, 4, 5, 6, 7
        """
        source_count = artifact.copy_query(sources_query, str(sources_path))
        sources_manifest = make_manifest(
            dataset="filing_occurrence_sources",
            phase="filing_extraction",
            run_id=catalog_id,
            schema_version=TARGET_SCHEMA_VERSION,
            artifact_path=str(sources_path),
            artifacts_root=handoff_root,
            row_count=source_count,
            upstream=(handoff["artifact_id"],) if handoff else (),
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
            "form_partition_mapping": {
                form: re.sub(r"[^A-Za-z0-9_.-]", "_", form) or "_unknown"
                for form in counts
            },
            "materializer_version": SCHEMA_VERSION,
            "source_artifact_id": handoff.get("artifact_id") if handoff else None,
            "handoff_mode": "manifest" if handoff else "legacy_merge_report",
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        report_payload = {
            "catalog_id": catalog_id,
            "source_artifact_sha256": source_hash,
            "target_counts": counts,
            "malformed_records": "invalid accession, archive URL, or primary document records are excluded from targets",
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
        return manifest
