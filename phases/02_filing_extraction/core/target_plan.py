"""Deterministic target planner for Phase 02 filing catalogs.

Supports both full deterministic catalog partitioning and policy-driven
deficit fixture selection, producing an identical composite target-plan bundle
for Phase 2.5 consumption.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from defs.runtime.artifacts import load_manifest
from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.storage import (
    DuckDBStaging,
    FinalizedArtifact,
    StorageError,
    atomic_write_json,
)

from . import config as phase_config
from .selection import DeficitSelector
from .selection_features import FeatureSnapshotBuilder
from .selection_policy import (
    SelectionPolicy,
    compute_seed_fingerprint,
    load_seed_cik_csv,
)

logger = logging.getLogger("filing_extraction.target_plan")

TARGET_PLAN_SCHEMA_VERSION = "1.0"


def _emit(progress: Callable[[dict], None] | None, event: dict) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("target plan progress callback failed")


def _resolve_catalog_manifests(
    catalog: str, artifacts_root: Path, manifests_root: Path
) -> tuple[str, list[dict]]:
    catalog_path = Path(catalog) if catalog else None
    if catalog_path and catalog_path.is_file():
        candidate_paths = [catalog_path]
    elif catalog_path and catalog_path.is_dir():
        candidate_paths = sorted(catalog_path.glob("*.json"))
    else:
        candidate_paths = sorted((manifests_root / "filing_extraction").rglob("*.json"))
    distinct_manifests = {}
    for path in candidate_paths:
        try:
            item = load_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        art_id = item.get("artifact_id")
        if not art_id or art_id in distinct_manifests:
            continue
        if (
            not catalog
            or (catalog_path and catalog_path.exists())
            or str(catalog)
            in {
                str(item.get("run_id")),
                str(item.get("provenance", {}).get("catalog_id")),
            }
        ):
            distinct_manifests[art_id] = item
    manifests = list(distinct_manifests.values())
    target_manifests = [m for m in manifests if m.get("dataset") == "filing_targets"]
    if not target_manifests:
        raise StorageError("no published filing_targets manifests found for catalog")
    catalog_id = str(target_manifests[0].get("run_id") or "")
    all_catalog_manifests = [m for m in manifests if str(m.get("run_id")) == catalog_id]
    return catalog_id, all_catalog_manifests


def plan(
    catalog: str = "",
    output_root: str | None = None,
    *,
    scope: str = "full",
    selection_policy_path: str | Path | None = None,
    seed_cik_path: str | Path | None = None,
    forms: tuple[str, ...] | None = None,
    amendment: str | None = None,
    limit: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Execute deterministic target planning (full or fixture scope)."""
    if forms is None:
        forms = phase_config.load().target_forms
    if amendment is None:
        amendment = phase_config.load().amendment
    if scope not in {"full", "fixture"}:
        raise ValueError(f"scope must be 'full' or 'fixture', got {scope!r}")
    if amendment not in {"both", "original", "amendments"}:
        raise ValueError("amendment must be both, original, or amendments")

    resolved_paths = resolve_paths("filing_extraction")
    artifacts_root = resolved_paths.project.artifacts_root.resolve()
    manifests_root = resolved_paths.project.manifests_root.resolve()
    transient_root = (
        Path(output_root).resolve()
        if output_root is not None
        else resolved_paths.runs_root.resolve()
    )

    catalog_id, catalog_manifests = _resolve_catalog_manifests(
        catalog, artifacts_root, manifests_root
    )
    target_manifests = [
        m for m in catalog_manifests if m.get("dataset") == "filing_targets"
    ]
    profile_manifest = next(
        (m for m in catalog_manifests if m.get("dataset") == "company_profiles"), None
    )

    resources = derive_resources()

    if scope == "fixture":
        if not selection_policy_path:
            selection_policy_path = resolved_paths.phase_root / "selection_policy.json"
        pol_path = Path(selection_policy_path)
        if not pol_path.exists():
            from .selection_policy import auto_generate_policy

            auto_generate_policy(
                catalog_id, manifests_root=manifests_root, dest=pol_path
            )
        policy = SelectionPolicy.from_path(pol_path)
        actual_seed_path = Path(seed_cik_path or policy.seed_cik_path)
        seed_filers = {}
        if actual_seed_path.exists():
            seed_filers = load_seed_cik_csv(actual_seed_path)

        # Build feature snapshot
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "build_features",
                "forms": len(policy.forms),
            },
        )
        target_base_dir = resolved_paths.project.dataset_manifests(
            "filing_extraction", "filing_targets"
        )
        if not target_base_dir.exists() and target_manifests:
            art_path = Path(target_manifests[0]["artifact_path"])
            if not art_path.is_absolute():
                art_path = artifacts_root / art_path
            target_base_dir = art_path.parent.parent

        profile_dir = resolved_paths.project.dataset_manifests(
            "filing_extraction", "company_profiles"
        )
        profile_art_path = profile_dir / "company_profiles.parquet"
        if not profile_art_path.exists() and profile_manifest:
            art_path = Path(profile_manifest["artifact_path"])
            if not art_path.is_absolute():
                art_path = artifacts_root / art_path
            if art_path.exists():
                profile_art_path = art_path

        snapshot_builder = FeatureSnapshotBuilder(
            target_root=target_base_dir,
            profile_path=profile_art_path,
            output_root=transient_root,
            policy=policy,
            threads=resources.threads,
            memory_limit=resources.memory_limit,
            temp_directory=resources.temp_directory,
        )
        snapshot_paths = snapshot_builder.build()

        _emit(progress, {"type": "merge_stage", "stage": "select_deficit"})
        selector = DeficitSelector(
            snapshot_dir=snapshot_paths.snapshot_dir,
            policy=policy,
            seed_filers=seed_filers,
            threads=resources.threads,
            memory_limit=resources.memory_limit,
        )
        selection_res = selector.select()

        # Compute Plan Identity
        plan_hash_payload = {
            "catalog_id": catalog_id,
            "scope": scope,
            "policy_fingerprint": policy.policy_fingerprint,
            "seed_fingerprint": compute_seed_fingerprint(seed_filers),
            "level": policy.level,
            "active_locators": sorted(selection_res.active_locators),
        }
        plan_id = hashlib.sha256(
            json.dumps(plan_hash_payload, sort_keys=True).encode()
        ).hexdigest()[:24]

        final_plan_dir = (
            resolved_paths.project.dataset_manifests(
                "filing_extraction", "target_plans"
            )
            / plan_id
        )
        if final_plan_dir.exists():
            shutil.rmtree(final_plan_dir, ignore_errors=True)
        final_plan_dir.mkdir(parents=True, exist_ok=True)

        # Materialize form-partitioned active targets & locator groups
        _emit(progress, {"type": "merge_stage", "stage": "materialize_targets"})
        counts: dict[str, int] = {}
        target_root = final_plan_dir / "targets"
        target_root.mkdir(parents=True, exist_ok=True)

        db_file = final_plan_dir / "materialize_staging.duckdb"
        try:
            db_file.unlink(missing_ok=True)
        except OSError:
            pass
        with DuckDBStaging(
            db_file,
            threads=resources.threads,
            memory_limit=resources.memory_limit,
            cleanup_root=False,
        ) as staging:
            occ_parquet = snapshot_paths.occurrence_features
            loc_parquet = snapshot_paths.locator_features
            active_keys = selection_res.active_locators

            staging.execute(
                "CREATE TEMP TABLE selected_locs (document_locator_key VARCHAR)"
            )
            step = 5000
            for idx in range(0, len(active_keys), step):
                chunk = [[k] for k in active_keys[idx : idx + step]]
                staging.executemany("INSERT INTO selected_locs VALUES (?)", chunk)

            # Extract distinct forms in active selection
            forms_in_selection = [
                r[0]
                for r in staging.execute(f"""
                    SELECT DISTINCT form
                    FROM read_parquet('{occ_parquet}') o
                    JOIN selected_locs s ON o.document_locator_key = s.document_locator_key
                """)
            ]

            for form_name in sorted(forms_in_selection):
                form_part = form_name.replace("/", "_")
                dest_file = target_root / f"form={form_part}" / "data.parquet"
                val_q = f"""
                    SELECT
                        o.occurrence_id, o.document_locator_key, o.source_cik, o.accession,
                        o.form, o.is_amendment, o.filing_date, o.report_date, o.primary_document,
                        o.document_path, o.archive_url, o.reported_size, o.is_xbrl,
                        o.is_inline_xbrl, o.is_xbrl_numeric
                    FROM read_parquet('{occ_parquet}') o
                    JOIN selected_locs s ON o.document_locator_key = s.document_locator_key
                    WHERE o.form = '{form_name}'
                    ORDER BY o.document_locator_key, o.occurrence_id
                """
                cnt = staging.copy_query(val_q, dest_file)
                counts[form_name] = int(cnt)

            loc_dest = final_plan_dir / "locator_groups.parquet"
            loc_q = f"""
                SELECT
                    l.document_locator_key, l.form, l.form_family, l.era, l.suffix,
                    l.xbrl_state, l.size_band, l.owner_org_presence, l.foreign_status,
                    l.lifecycle_class, l.stub_suspect, l.representative_cik,
                    l.representative_accession, l.primary_document, l.document_path,
                    l.archive_url, l.company_name
                FROM read_parquet('{loc_parquet}') l
                JOIN selected_locs s ON l.document_locator_key = s.document_locator_key
                ORDER BY l.document_locator_key
            """
            staging.copy_query(loc_q, loc_dest)

            if selection_res.reserve_locators:
                res_keys = selection_res.reserve_locators
                staging.execute(
                    "CREATE TEMP TABLE reserve_locs (document_locator_key VARCHAR)"
                )
                for idx in range(0, len(res_keys), step):
                    chunk = [[k] for k in res_keys[idx : idx + step]]
                    staging.executemany("INSERT INTO reserve_locs VALUES (?)", chunk)

                res_dest = final_plan_dir / "reserve_targets.parquet"
                res_q = f"""
                    SELECT l.*
                    FROM read_parquet('{loc_parquet}') l
                    JOIN reserve_locs r ON l.document_locator_key = r.document_locator_key
                    ORDER BY l.document_locator_key
                """
                staging.copy_query(res_q, res_dest)

        # Write selection report
        atomic_write_json(
            final_plan_dir / "selection_report.json", selection_res.report
        )

        plan_meta = {
            "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
            "run_id": plan_id,
            "plan_id": plan_id,
            "catalog_id": catalog_id,
            "scope": "fixture",
            "policy_corpus": policy.corpus_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "seed_fingerprint": compute_seed_fingerprint(seed_filers),
            "level": policy.level,
            "active_targets_count": len(selection_res.active_occurrences),
            "unique_locators_count": len(selection_res.active_locators),
            "reserve_count": len(selection_res.reserve_locators),
            "forms": list(policy.forms),
            "counts": counts,
            "selected_rows": sum(counts.values()),
        }
        atomic_write_json(final_plan_dir / "plan.json", plan_meta)
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "publish_plan",
                "rows": sum(counts.values()),
            },
        )
        return plan_meta

    else:
        # Full Scope Selection
        selected_forms = set(forms)
        selected_entries = []
        for item in sorted(target_manifests, key=lambda m: m["artifact_path"]):
            match = re.search(r"/form=([^/]+)/", item["artifact_path"])
            form = match.group(1) if match else ""
            if selected_forms and form not in selected_forms:
                continue
            if amendment == "original" and form.upper().endswith("_A"):
                continue
            if amendment == "amendments" and not form.upper().endswith("_A"):
                continue
            selected_entries.append((form, item))

        full_hash_payload = {
            "catalog_id": catalog_id,
            "scope": "full",
            "forms": sorted(selected_forms) if selected_forms else "all",
            "amendment": amendment,
            "limit": limit,
        }
        run_id = hashlib.sha256(
            json.dumps(full_hash_payload, sort_keys=True).encode()
        ).hexdigest()[:24]

        destination = (
            resolved_paths.project.dataset_manifests(
                "filing_extraction", "target_plans"
            )
            / run_id
        )
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True, exist_ok=True)

        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "select_targets",
                "forms": len(selected_entries),
                "total_units": len(selected_entries) + 2,
            },
        )

        counts = {}
        source_artifact_ids = {}
        target_root = destination / "targets"
        target_root.mkdir(parents=True, exist_ok=True)

        targets_manifest_dir = resolved_paths.project.dataset_manifests(
            "filing_extraction", "filing_targets"
        )
        for form, item in selected_entries:
            form_part = form.replace("/", "_")
            source = targets_manifest_dir / f"form={form_part}" / "data.parquet"
            if not source.exists():
                art_path = Path(item["artifact_path"])
                if not art_path.is_absolute():
                    art_path = artifacts_root / art_path
                source = art_path
            destination_file = target_root / f"form={form_part}" / "data.parquet"
            if destination_file.exists():
                destination_file.unlink()
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            where = ""
            params = []
            if limit is not None:
                if limit < 0:
                    raise ValueError("limit must be non-negative")
                where = "LIMIT ?"
                params = [limit]
            with FinalizedArtifact(source) as artifact:
                query = f"SELECT * FROM {artifact.relation} {where}"
                counts[form] = artifact.copy_query(query, destination_file, params)
            source_artifact_ids[form] = item["artifact_id"]
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"targets:{form}",
                    "rows": counts[form],
                },
            )

        # Generate locator_groups.parquet for full plan
        target_files = sorted(target_root.glob("form=*/data.parquet"))
        unique_locators = 0
        if target_files:
            file_list = ", ".join(f"'{p}'" for p in target_files)
            loc_dest = destination / "locator_groups.parquet"
            db_file = destination / "full_plan_staging.duckdb"
            with DuckDBStaging(
                db_file, threads=resources.threads, memory_limit=resources.memory_limit
            ) as staging:
                unique_locators = staging.copy_query(
                    f"""
                    SELECT DISTINCT
                        document_locator_key,
                        form,
                        source_cik AS representative_cik,
                        accession AS representative_accession,
                        primary_document,
                        document_path,
                        archive_url
                    FROM read_parquet([{file_list}])
                    ORDER BY document_locator_key
                """,
                    loc_dest,
                )

        selection_report = {
            "scope": "full",
            "catalog_id": catalog_id,
            "active_targets_count": sum(counts.values()),
            "unique_locators_count": int(unique_locators),
            "counts": counts,
        }
        atomic_write_json(destination / "selection_report.json", selection_report)

        plan_meta = {
            "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
            "run_id": run_id,
            "plan_id": run_id,
            "catalog_id": catalog_id,
            "scope": "full",
            "forms": list(forms),
            "amendment": amendment,
            "limit": limit,
            "counts": counts,
            "selected_rows": sum(counts.values()),
            "active_targets_count": sum(counts.values()),
            "unique_locators_count": int(unique_locators),
            "source_artifact_ids": source_artifact_ids,
        }
        atomic_write_json(destination / "plan.json", plan_meta)
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "publish_plan",
                "rows": sum(counts.values()),
            },
        )
        return plan_meta


__all__ = ["TARGET_PLAN_SCHEMA_VERSION", "plan"]
