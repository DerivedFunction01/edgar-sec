"""Read and discover immutable document-planning bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import (
    file_sha256,
    is_sha256_hex_digest,
    sha256_text,
)
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from .paths import (
    DocumentPlanningPaths,
    catalog_form_partition_name,
    resolve_document_planning_paths,
    validate_profile_id,
)
from .schemas import (
    MATCHER_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)


class DocumentPlanError(ValueError):
    """A published target-plan bundle is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class PublishedDocumentPlan:
    plan_id: str
    root: Path
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DiscoveredDocumentPlan:
    plan_id: str
    plan: PublishedDocumentPlan | None
    error: str | None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DocumentPlanError(f"duplicate manifest field: {key}")
        value[key] = item
    return value


def read_published_plan(
    plan_id: str, paths: DocumentPlanningPaths | None = None
) -> PublishedDocumentPlan:
    locations = paths or resolve_document_planning_paths()
    path = locations.plan_manifest_path(plan_id)
    root = path.parent.resolve()
    if not path.resolve().is_relative_to(root):
        raise DocumentPlanError("plan manifest escapes its bundle")
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DocumentPlanError) as error:
        raise DocumentPlanError(f"plan manifest is unreadable: {plan_id}") from error
    return _validate_plan_root(plan_id, root, manifest, locations.plans_root)


def validate_staged_plan(plan_id: str, root: Path) -> PublishedDocumentPlan:
    path = root / PLAN_FILE_NAME
    if not path.resolve().is_relative_to(root.resolve()):
        raise DocumentPlanError("staged plan manifest escapes its bundle")
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DocumentPlanError) as error:
        raise DocumentPlanError(
            f"staged plan manifest is unreadable: {plan_id}"
        ) from error
    return _validate_plan_root(plan_id, root, manifest, root.parent)


def _validate_plan_root(
    plan_id: str,
    root: Path,
    manifest: Any,
    plans_root: Path,
    *,
    validate_parts: bool = True,
) -> PublishedDocumentPlan:
    root = root.resolve()
    if not root.is_relative_to(plans_root.resolve()):
        raise DocumentPlanError("plan directory escapes published plan storage")
    if not isinstance(manifest, dict) or manifest.get("plan_id") != plan_id:
        raise DocumentPlanError("plan ID does not match its manifest")
    if manifest.get("target_schema_version") != TARGET_SCHEMA_VERSION:
        raise DocumentPlanError("unsupported target schema version")
    expected_digest = manifest.get("plan_digest")
    unsigned = dict(manifest)
    unsigned.pop("plan_digest", None)
    if (
        not isinstance(expected_digest, str)
        or canonical_hash(unsigned) != expected_digest
    ):
        raise DocumentPlanError("plan manifest digest mismatch")
    identity = manifest.get("plan_identity")
    if not isinstance(identity, dict):
        raise DocumentPlanError("plan identity is missing")
    if (
        not isinstance(manifest.get("bundle_schema_version"), int)
        or isinstance(manifest.get("bundle_schema_version"), bool)
        or manifest.get("bundle_schema_version") != PLAN_BUNDLE_SCHEMA_VERSION
        or not isinstance(identity.get("bundle_schema_version"), int)
        or isinstance(identity.get("bundle_schema_version"), bool)
        or identity.get("bundle_schema_version") != PLAN_BUNDLE_SCHEMA_VERSION
        or identity.get("matcher_version") != MATCHER_VERSION
        or manifest.get("matcher_version") != MATCHER_VERSION
    ):
        raise DocumentPlanError("unsupported plan bundle or matcher version")
    expected_id = f"dplan_{sha256_text(canonical_json(identity))[:32]}"
    if expected_id != plan_id:
        raise DocumentPlanError("plan ID does not match its canonical identity")
    row_group_size = manifest.get("row_group_size")
    if (
        identity.get("target_schema_version") != TARGET_SCHEMA_VERSION
        or not isinstance(row_group_size, int)
        or isinstance(row_group_size, bool)
        or row_group_size < 1
        or identity.get("row_group_size") != row_group_size
        or manifest.get("profile_digest") != identity.get("profile_digest")
        or manifest.get("catalog_plan_id") != identity.get("catalog_plan_id")
        or manifest.get("catalog_plan_digest") != identity.get("catalog_plan_digest")
        or manifest.get("inventory_snapshot_id")
        != identity.get("inventory_snapshot_id")
        or manifest.get("inventory_snapshot_digest")
        != identity.get("inventory_snapshot_digest")
    ):
        raise DocumentPlanError("manifest metadata does not match its identity")
    if validate_parts:
        _validate_parts(root, manifest)
    target_count = manifest.get("target_row_count")
    status_counts = manifest.get("status_counts")
    if (
        not isinstance(target_count, int)
        or isinstance(target_count, bool)
        or target_count < 0
        or not isinstance(status_counts, dict)
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in status_counts.values()
        )
        or sum(status_counts.values()) != target_count
    ):
        raise DocumentPlanError("plan row counts are invalid")
    validate_profile_id(str(manifest.get("profile_id") or ""))
    return PublishedDocumentPlan(plan_id, root, manifest)


def _validate_parts(root: Path, manifest: dict[str, Any]) -> None:
    row_group_size = manifest["row_group_size"]
    parts = manifest.get("parts")
    if not isinstance(parts, list):
        raise DocumentPlanError("plan parts must be an array")
    observed: dict[str, int] = {}
    previous: tuple[str, str] | None = None
    indices: dict[str, int] = {}
    partitions: dict[str, str] = {}
    declared_files: set[Path] = set()
    for part in parts:
        if not isinstance(part, dict):
            raise DocumentPlanError("plan part must be an object")
        relative, form, rows, digest = (
            part.get("path"),
            part.get("form"),
            part.get("rows"),
            part.get("sha256"),
        )
        if not isinstance(relative, str) or not isinstance(form, str) or not form:
            raise DocumentPlanError("plan part descriptor is invalid")
        if (
            not isinstance(rows, int)
            or isinstance(rows, bool)
            or rows < 1
            or rows > row_group_size
        ):
            raise DocumentPlanError("plan part descriptor is invalid")
        if not isinstance(digest, str) or not is_sha256_hex_digest(digest):
            raise DocumentPlanError("plan part descriptor is invalid")
        byte_size = part.get("byte_size")
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
        ):
            raise DocumentPlanError("plan part descriptor is invalid")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise DocumentPlanError("plan part path is unsafe")
        partition = catalog_form_partition_name(form)
        if partition in partitions and partitions[partition] != form:
            raise DocumentPlanError("plan forms collide in partition names")
        partitions[partition] = form
        form_dir = f"targets/form={partition}"
        prefix = f"{form_dir}/part-"
        if not relative.startswith(prefix) or not relative.endswith(".parquet"):
            raise DocumentPlanError("plan part path does not match its form")
        expected_index = indices.get(form, 0)
        expected_name = f"{form_dir}/part-{expected_index:05d}.parquet"
        if relative != expected_name:
            raise DocumentPlanError("plan parts are not numbered consecutively")
        order = (form, relative)
        if previous is not None and order <= previous:
            raise DocumentPlanError("plan part records are not sorted and unique")
        previous = order
        absolute = (root / Path(*path.parts)).resolve()
        if not absolute.is_relative_to(root) or not absolute.is_file():
            raise DocumentPlanError(
                f"plan part is missing or escapes its bundle: {relative}"
            )
        if absolute.stat().st_size != byte_size:
            raise DocumentPlanError(f"plan part byte size mismatch: {relative}")
        if file_sha256(absolute) != digest:
            raise DocumentPlanError(f"plan part digest mismatch: {relative}")
        try:
            parquet = pq.ParquetFile(absolute)
            schema_valid = parquet.schema_arrow.equals(
                TARGET_SCHEMA, check_metadata=False
            )
            actual_rows = parquet.metadata.num_rows
        except Exception as error:
            raise DocumentPlanError(f"plan part is corrupt: {relative}") from error
        if not schema_valid or actual_rows != rows:
            raise DocumentPlanError(
                f"plan part schema or row count mismatch: {relative}"
            )
        _validate_target_rows(absolute, form, str(manifest["plan_id"]))
        indices[form] = expected_index + 1
        observed[form] = observed.get(form, 0) + rows
        declared_files.add(absolute)
    for form in indices:
        form_parts = [part for part in parts if part["form"] == form]
        if any(part["rows"] != row_group_size for part in form_parts[:-1]):
            raise DocumentPlanError(
                "non-final plan parts must match parquet row_group_size"
            )
    if sum(observed.values()) != manifest.get("target_row_count"):
        raise DocumentPlanError("plan part rows do not match target row count")
    actual_files = {path.resolve() for path in (root / "targets").rglob("*.parquet")}
    if actual_files != declared_files:
        raise DocumentPlanError("plan bundle has undeclared or missing target parts")


def _validate_target_rows(path: Path, form: str, plan_id: str) -> None:
    previous: tuple[str, str, str, str] | None = None
    try:
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=resolve_parquet_read_batch_size(),
            columns=[
                "target_id",
                "accession",
                "form",
                "request_id",
                "inventory_entry_id",
                "status",
            ],
        ):
            for row in batch.to_pylist():
                if row["form"] != form:
                    raise DocumentPlanError(
                        "target row form disagrees with its partition"
                    )
                key = (
                    row["accession"],
                    row["request_id"],
                    row["inventory_entry_id"] or "",
                    row["status"],
                )
                if previous is not None and key < previous:
                    raise DocumentPlanError("target rows are not sorted canonically")
                if row["target_id"] != canonical_hash(
                    [
                        plan_id,
                        row["accession"],
                        row["request_id"],
                        row["inventory_entry_id"],
                        row["status"],
                    ]
                ):
                    raise DocumentPlanError("target row ID does not match its identity")
                previous = key
    except DocumentPlanError:
        raise
    except Exception as error:
        raise DocumentPlanError(f"target rows are unreadable: {path.name}") from error


def discover_document_plans(
    paths: DocumentPlanningPaths | None = None,
) -> tuple[DiscoveredDocumentPlan, ...]:
    locations = paths or resolve_document_planning_paths()
    if not locations.plans_root.exists():
        return ()
    results: list[DiscoveredDocumentPlan] = []
    for root in sorted(locations.plans_root.iterdir(), key=lambda item: item.name):
        if not root.is_dir():
            continue
        try:
            manifest_path = root / PLAN_FILE_NAME
            if not manifest_path.resolve().is_relative_to(root.resolve()):
                raise DocumentPlanError("plan manifest escapes its bundle")
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
            )
            plan = _validate_plan_root(
                root.name,
                root,
                manifest,
                locations.plans_root,
                validate_parts=False,
            )
        except (OSError, ValueError) as error:
            results.append(DiscoveredDocumentPlan(root.name, None, str(error)))
        else:
            results.append(DiscoveredDocumentPlan(root.name, plan, None))
    return tuple(results)


__all__ = [
    "DiscoveredDocumentPlan",
    "DocumentPlanError",
    "PublishedDocumentPlan",
    "discover_document_plans",
    "read_published_plan",
    "validate_staged_plan",
]
