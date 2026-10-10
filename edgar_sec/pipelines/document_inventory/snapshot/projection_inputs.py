"""Validation and bounded input-part resolution for inventory projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.filing_catalog.schemas import (
    READABLE_TARGET_PLAN_SCHEMA_VERSIONS,
    TARGET_SCHEMA,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME, PLAN_FILE_NAME
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.cohort import CohortInputError
from edgar_sec.pipelines.document_inventory.paths import (
    FORM_PARTITION_GLOB,
    FilingCatalogPaths,
    PLAN_TARGETS_DIR,
    REQUIRED_PLAN_FILES,
    SEED_FILERS_FILE,
    InventoryPaths,
    form_partition_name,
    plan_target_file_path,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.document_inventory.snapshot.errors import BaseSnapshotError
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.filing_catalog.discovery import discover_plans
from edgar_sec.pipelines.filing_catalog.publication import (
    plan_fingerprint_from_plan,
)

__all__ = ["base_snapshot_parts", "catalog_plan_parts"]


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CohortInputError(
            "invalid_bundle", detail=f"{label} is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise CohortInputError("invalid_bundle", detail=f"{label} must be an object")
    return payload


def catalog_plan_parts(
    plan_id: str, paths: FilingCatalogPaths
) -> tuple[Path, dict[str, Any], list[tuple[str, Path, int, str]], str, str]:
    known = {str(item.get("plan_id")) for item in discover_plans(paths)}
    if plan_id not in known:
        raise CohortInputError(
            "invalid_bundle", detail=f"unpublished catalog plan {plan_id!r}"
        )
    root = paths.plan_dir(plan_id)
    try:
        root.resolve().relative_to(paths.plans_root.resolve())
    except ValueError as exc:
        raise CohortInputError(
            "invalid_bundle", detail="plan escapes catalog storage"
        ) from exc
    plan_path = root / PLAN_FILE_NAME
    try:
        plan_path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CohortInputError(
            "invalid_bundle", detail="plan manifest escapes plan storage"
        ) from exc
    plan_sha256 = file_sha256(plan_path)
    document = _read_json(plan_path, label="plan manifest")
    if file_sha256(plan_path) != plan_sha256:
        raise CohortInputError(
            "invalid_bundle", detail="plan manifest changed while reading"
        )
    if document.get("plan_id") != plan_id:
        raise CohortInputError(
            "invalid_bundle", detail="plan id does not match its directory"
        )
    if document.get("plan_schema_version") not in READABLE_TARGET_PLAN_SCHEMA_VERSIONS:
        raise CohortInputError(
            "invalid_bundle", detail="unsupported plan schema version"
        )
    if document.get("scope") not in {"deterministic", "policy"}:
        raise CohortInputError("invalid_bundle", detail="unsupported plan scope")
    if document["scope"] == "policy":
        seed_path = root / SEED_FILERS_FILE
        if not seed_path.is_file():
            raise CohortInputError(
                "invalid_bundle", detail="policy plan seed filers are missing"
            )
        try:
            seed_path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise CohortInputError(
                "invalid_bundle", detail="policy plan seed filers escape plan storage"
            ) from exc
    forms = document.get("forms")
    counts = document.get("counts")
    if (
        not isinstance(forms, list)
        or any(
            not isinstance(form, str) or not form.strip() or form != form.strip()
            for form in forms
        )
        or len(forms) != len(set(forms))
        or not isinstance(counts, dict)
    ):
        raise CohortInputError(
            "invalid_bundle", detail="invalid plan form/count metadata"
        )
    if (
        not isinstance(document.get("catalog_id"), str)
        or not document["catalog_id"].strip()
    ):
        raise CohortInputError("invalid_bundle", detail="plan has no catalog identity")
    for relative in REQUIRED_PLAN_FILES:
        artifact_path = root / relative
        if not artifact_path.is_file():
            raise CohortInputError(
                "invalid_bundle", detail=f"plan file missing: {relative}"
            )
        try:
            artifact_path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise CohortInputError(
                "invalid_bundle", detail=f"plan file escapes plan storage: {relative}"
            ) from exc
    locator_path = root / "locator_groups.parquet"
    locator_sha256 = file_sha256(locator_path)
    try:
        locator_parquet = pq.ParquetFile(locator_path)
    except (OSError, pa.ArrowException, pq.ParquetException) as exc:
        raise CohortInputError(
            "invalid_bundle", detail="locator groups are unreadable"
        ) from exc
    if (
        "document_locator_key" not in locator_parquet.schema_arrow.names
        or locator_parquet.schema_arrow.field("document_locator_key").type
        != pa.string()
    ):
        raise CohortInputError("invalid_bundle", detail="locator-group schema mismatch")
    locator_count = document.get("unique_locators_count")
    if (
        not isinstance(locator_count, int)
        or isinstance(locator_count, bool)
        or locator_count != locator_parquet.metadata.num_rows
    ):
        raise CohortInputError(
            "invalid_bundle", detail="locator-group row count mismatch"
        )
    recorded_fingerprint = document.get("plan_fingerprint")
    if not isinstance(recorded_fingerprint, str) or not recorded_fingerprint:
        raise CohortInputError(
            "invalid_bundle", detail="plan has no selection fingerprint"
        )
    if plan_fingerprint_from_plan(root, document) != recorded_fingerprint:
        raise CohortInputError(
            "invalid_bundle", detail="plan selection fingerprint mismatch"
        )
    if file_sha256(locator_path) != locator_sha256:
        raise CohortInputError(
            "invalid_bundle", detail="locator groups changed while reading"
        )

    target_forms = sorted(counts)
    if any(
        not isinstance(form, str) or not form.strip() or form != form.strip()
        for form in target_forms
    ):
        raise CohortInputError("invalid_bundle", detail="invalid target form metadata")
    if forms and not set(target_forms).issubset(forms):
        raise CohortInputError(
            "invalid_bundle", detail="target forms exceed the requested form filter"
        )
    partition_names = [form_partition_name(form) for form in target_forms]
    if len(partition_names) != len(set(partition_names)):
        raise CohortInputError("invalid_bundle", detail="form partition names collide")
    parts: list[tuple[str, Path, int, str]] = []
    expected_parts: set[Path] = set()
    for form, partition in zip(target_forms, partition_names, strict=True):
        declared_count = counts.get(form)
        if (
            not isinstance(declared_count, int)
            or isinstance(declared_count, bool)
            or declared_count < 0
        ):
            raise CohortInputError(
                "invalid_bundle", detail=f"invalid row count for {form!r}"
            )
        path = root / plan_target_file_path(form, DATA_FILE_NAME)
        if not path.is_file():
            raise CohortInputError(
                "invalid_bundle", detail=f"target part missing: {path.name}"
            )
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise CohortInputError(
                "invalid_bundle", detail="target part escapes plan storage"
            ) from exc
        try:
            parquet = pq.ParquetFile(path)
        except (OSError, pa.ArrowException, pq.ParquetException) as exc:
            raise CohortInputError(
                "invalid_bundle", detail=f"target part unreadable: {path.name}"
            ) from exc
        schema = parquet.schema_arrow
        if schema.names != TARGET_SCHEMA.names or not schema.equals(
            TARGET_SCHEMA, check_metadata=False
        ):
            raise CohortInputError(
                "invalid_bundle", detail=f"target schema mismatch: {path.name}"
            )
        row_count = int(parquet.metadata.num_rows)
        if row_count != declared_count:
            raise CohortInputError(
                "invalid_bundle",
                detail=f"{form} declares {declared_count} rows but has {row_count}",
            )
        resolved = path.resolve()
        parts.append((form, resolved, row_count, file_sha256(path)))
        expected_parts.add(resolved)
    observed_parts = {
        path.resolve()
        for path in (root / PLAN_TARGETS_DIR).glob(f"{FORM_PARTITION_GLOB}/*.parquet")
        if path.is_file()
    }
    if observed_parts != expected_parts:
        raise CohortInputError(
            "invalid_bundle", detail="target part set does not match plan forms"
        )
    selected_rows = document.get("selected_rows")
    if (
        not isinstance(selected_rows, int)
        or isinstance(selected_rows, bool)
        or sum(counts.values()) != selected_rows
    ):
        raise CohortInputError(
            "invalid_bundle", detail="selected row count does not match target parts"
        )
    active_rows = document.get("active_targets_count")
    if (
        not isinstance(active_rows, int)
        or isinstance(active_rows, bool)
        or active_rows != selected_rows
    ):
        raise CohortInputError(
            "invalid_bundle", detail="active target count does not match selected rows"
        )
    return root, document, parts, plan_sha256, locator_sha256


def _resolve_snapshot_part(
    snapshots_root: Path, snapshot_id: str, raw_path: object
) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise BaseSnapshotError("base snapshot part path is invalid")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise BaseSnapshotError("base snapshot part path escapes snapshot storage")
    if relative.parts and relative.parts[0] == snapshot_id:
        candidate = snapshots_root / relative
    else:
        candidate = snapshots_root / snapshot_id / relative
    try:
        candidate.resolve().relative_to(snapshots_root.resolve())
    except ValueError as exc:
        raise BaseSnapshotError(
            "base snapshot part path escapes snapshot storage"
        ) from exc
    return candidate


def base_snapshot_parts(
    paths: InventoryPaths,
    snapshot_id: str | None = None,
    branch_name: str = "main",
) -> tuple[str | None, list[tuple[Path, int, str]], str | None]:
    catalog = DAGCatalog(paths.snapshots_root)
    if not catalog.catalog_file.is_file():
        return None, [], None
    if snapshot_id is not None:
        manifest = catalog.get_manifest(snapshot_id)
        if manifest is None:
            raise BaseSnapshotError(f"base snapshot manifest missing: {snapshot_id}")
        if manifest.snapshot_id != snapshot_id:
            raise BaseSnapshotError("base snapshot manifest identity mismatch")
        actual_manifest_sha = catalog.get_manifest_sha256(snapshot_id) or ""
    else:
        pointer = catalog.read_pointer(branch_name)
        if not pointer:
            return None, [], None
        snapshot_id = pointer.get("snapshot_id")
        if (
            not isinstance(snapshot_id, str)
            or not snapshot_id
            or snapshot_id in {".", ".."}
        ):
            raise BaseSnapshotError(
                f"{branch_name!r} branch pointer has no valid snapshot_id"
            )
        try:
            paths.snapshot_root(snapshot_id)
        except ValueError as exc:
            raise BaseSnapshotError(
                f"{branch_name!r} branch pointer names an unsafe snapshot_id"
            ) from exc
        manifest = catalog.get_manifest(snapshot_id)
        if manifest is None:
            raise BaseSnapshotError(f"{branch_name!r} base snapshot manifest missing")
        if manifest.snapshot_id != snapshot_id:
            raise BaseSnapshotError("base snapshot manifest identity mismatch")
        actual_manifest_sha = catalog.get_manifest_sha256(snapshot_id)
        pinned_manifest_sha = pointer.get("manifest_sha256")
        if (
            pinned_manifest_sha is not None
            and actual_manifest_sha != pinned_manifest_sha
        ):
            raise BaseSnapshotError(
                f"{branch_name!r} base snapshot manifest digest does not match branch tip"
            )
    records = manifest.relations.get("accessions")
    if records is None:
        raise BaseSnapshotError("base snapshot accession parts are missing")
    result: list[tuple[Path, int, str]] = []
    for record in records:
        part_path = record.path if hasattr(record, "path") else record.get("path")
        part_sha = record.sha256 if hasattr(record, "sha256") else record.get("sha256")
        part_row_count = (
            record.row_count
            if hasattr(record, "row_count")
            else record.get("row_count")
        )
        path = _resolve_snapshot_part(paths.snapshots_root, snapshot_id, part_path)
        if not path.is_file():
            raise BaseSnapshotError(
                f"base snapshot accession part missing: {path.name}"
            )
        if file_sha256(path) != part_sha:
            raise BaseSnapshotError(
                f"base snapshot accession digest mismatch: {path.name}"
            )
        try:
            parquet = pq.ParquetFile(path)
        except (OSError, pa.ArrowException, pq.ParquetException) as exc:
            raise BaseSnapshotError(
                f"base snapshot accession part unreadable: {path.name}"
            ) from exc
        schema = parquet.schema_arrow
        if schema.names != SNAPSHOT_ACCESSIONS_SCHEMA.names or any(
            schema.field(name).type != field.type
            for name, field in zip(
                SNAPSHOT_ACCESSIONS_SCHEMA.names,
                SNAPSHOT_ACCESSIONS_SCHEMA,
                strict=True,
            )
        ):
            raise BaseSnapshotError(
                f"base snapshot accession schema mismatch: {path.name}"
            )
        row_count = int(parquet.metadata.num_rows)
        if (
            not isinstance(part_row_count, int)
            or isinstance(part_row_count, bool)
            or row_count != part_row_count
        ):
            raise BaseSnapshotError(
                f"base snapshot accession row count mismatch: {path.name}"
            )
        result.append((path.resolve(), row_count, part_sha))
    return snapshot_id, result, actual_manifest_sha
