"""Read and discover immutable document-planning bundles."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import (
    file_sha256,
    is_sha256_hex_digest,
    sha256_text,
)
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME, part_file_name
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from .paths import (
    DiscoveredDocumentPlan,
    DocumentPlanningPaths,
    PublishedDocumentPlan,
    catalog_form_partition_name,
    form_partition_directory,
    plan_target_part_path,
    resolve_document_planning_paths,
    validate_profile_id,
)
from .schemas import (
    MATCHER_VERSION,
    OPERATION_INPUT_SCHEMA,
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_RELATION_SCHEMAS,
    PLAN_BUNDLE_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA,
    TARGET_OPERATION_SCHEMA_VERSION,
)


class DocumentPlanError(ValueError):
    """A published target-plan bundle is missing or inconsistent."""


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
        or not _is_version(
            manifest.get("target_operation_schema_version"),
            TARGET_OPERATION_SCHEMA_VERSION,
        )
        or not _is_version(
            manifest.get("source_request_schema_version"),
            SOURCE_REQUEST_SCHEMA_VERSION,
        )
        or not _is_version(
            manifest.get("operation_input_schema_version"),
            OPERATION_INPUT_SCHEMA_VERSION,
        )
        or not _is_version(
            identity.get("target_operation_schema_version"),
            TARGET_OPERATION_SCHEMA_VERSION,
        )
        or not _is_version(
            identity.get("source_request_schema_version"),
            SOURCE_REQUEST_SCHEMA_VERSION,
        )
        or not _is_version(
            identity.get("operation_input_schema_version"),
            OPERATION_INPUT_SCHEMA_VERSION,
        )
        or identity.get("profile_schema_version") != PROFILE_SCHEMA_VERSION
        or manifest.get("profile_schema_version") != PROFILE_SCHEMA_VERSION
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
        or manifest.get("profile_id") != identity.get("profile_id")
        or manifest.get("profile_version") != identity.get("profile_version")
        or manifest.get("catalog_plan_id") != identity.get("catalog_plan_id")
        or manifest.get("catalog_plan_digest") != identity.get("catalog_plan_digest")
        or manifest.get("inventory_snapshot_id")
        != identity.get("inventory_snapshot_id")
        or manifest.get("inventory_snapshot_digest")
        != identity.get("inventory_snapshot_digest")
    ):
        raise DocumentPlanError("manifest metadata does not match its identity")
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
    if validate_parts:
        _validate_parts(root, manifest)
    validate_profile_id(str(manifest.get("profile_id") or ""))
    return PublishedDocumentPlan(plan_id, root, manifest)


def _validate_parts(root: Path, manifest: dict[str, Any]) -> None:
    row_group_size = manifest["row_group_size"]
    parts = manifest.get("parts")
    if not isinstance(parts, list):
        raise DocumentPlanError("plan parts must be an array")
    observed: dict[str, int] = {}
    previous: tuple[str, str, str] | None = None
    indices: dict[tuple[str, str], int] = {}
    partitions: dict[str, str] = {}
    declared_files: set[Path] = set()
    requested_operation_counts: dict[str, int] = {}
    default_candidate_counts: dict[str, int] = {}
    unrequested_operation_counts: dict[str, int] = {}
    matched_source_count = 0
    input_row_count = 0
    for part in parts:
        if not isinstance(part, dict):
            raise DocumentPlanError("plan part must be an object")
        relation, relative, form, rows, digest = (
            part.get("relation"),
            part.get("path"),
            part.get("form"),
            part.get("rows"),
            part.get("sha256"),
        )
        if (
            not isinstance(relation, str)
            or relation not in PLAN_RELATION_SCHEMAS
            or not isinstance(relative, str)
            or not isinstance(form, str)
            or not form
        ):
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
        part_key = (relation, form)
        expected_index = indices.get(part_key, 0)
        expected_name = (
            plan_target_part_path(form, expected_index)
            if relation == "targets"
            else f"{relation}/{form_partition_directory(form)}/{part_file_name(expected_index)}"
        )
        if relative != expected_name:
            raise DocumentPlanError("relation parts are not numbered consecutively")
        order = (relation, form, relative)
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
                PLAN_RELATION_SCHEMAS[relation], check_metadata=False
            )
            actual_rows = parquet.metadata.num_rows
        except Exception as error:
            raise DocumentPlanError(f"plan part is corrupt: {relative}") from error
        if not schema_valid or actual_rows != rows:
            raise DocumentPlanError(
                f"plan part schema or row count mismatch: {relative}"
            )
        if relation == "targets":
            _validate_target_rows(absolute, form, str(manifest["plan_id"]))
        elif relation == "target_operations":
            requested, defaults, unrequested = _validate_operation_rows(absolute)
            _merge_counts(requested_operation_counts, requested)
            _merge_counts(default_candidate_counts, defaults)
            _merge_counts(unrequested_operation_counts, unrequested)
        elif relation == "source_requests":
            matched_source_count += _validate_source_request_rows(absolute)
        else:
            input_row_count += _validate_operation_input_rows(absolute)
        indices[part_key] = expected_index + 1
        observed[relation] = observed.get(relation, 0) + rows
        declared_files.add(absolute)
    for relation, form in indices:
        form_parts = [
            part
            for part in parts
            if part["relation"] == relation and part["form"] == form
        ]
        if any(part["rows"] != row_group_size for part in form_parts[:-1]):
            raise DocumentPlanError(
                "non-final relation parts must match parquet row_group_size"
            )
    if observed.get("targets", 0) != manifest.get("target_row_count"):
        raise DocumentPlanError("target part rows do not match target row count")
    expected_relation_counts = {
        relation: observed.get(relation, 0) for relation in PLAN_RELATION_SCHEMAS
    }
    if expected_relation_counts != manifest.get("relation_row_counts"):
        raise DocumentPlanError("relation part rows do not match relation counts")
    if requested_operation_counts != manifest.get("requested_operation_counts"):
        raise DocumentPlanError("requested operation counts do not match relation rows")
    if default_candidate_counts != manifest.get("default_candidate_operation_counts"):
        raise DocumentPlanError("default operation intents do not match relation rows")
    if unrequested_operation_counts != manifest.get("unrequested_operation_counts"):
        raise DocumentPlanError(
            "unrequested operation counts do not match relation rows"
        )
    target_count = manifest.get("target_row_count")
    matched_count = manifest.get("status_counts", {}).get("matched", 0)
    if (
        expected_relation_counts["target_operations"] != target_count * 3
        or expected_relation_counts["source_requests"] != matched_count
        or matched_source_count != matched_count
        or manifest.get("unique_source_request_count")
        != expected_relation_counts["source_requests"]
        or manifest.get("requested_operation_counts", {}).get("raw", 0) != target_count
        or input_row_count < matched_count
        or input_row_count > sum(requested_operation_counts.values())
    ):
        raise DocumentPlanError("plan operation or source counts violate S6 invariants")
    actual_files = {path.resolve() for path in root.rglob("*.parquet")}
    if actual_files != declared_files:
        raise DocumentPlanError("plan bundle has undeclared or missing relation parts")


def _validate_operation_rows(
    path: Path,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    previous: tuple[str, str] | None = None
    requested_counts: dict[str, int] = {}
    default_candidate_counts: dict[str, int] = {}
    unrequested_counts: dict[str, int] = {}
    try:
        columns = [field.name for field in TARGET_OPERATION_SCHEMA]
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=resolve_parquet_read_batch_size(), columns=columns
        ):
            for row in batch.to_pylist():
                key = (row["target_id"], row["operation"])
                if previous is not None and key <= previous:
                    raise DocumentPlanError("operation rows are not sorted and unique")
                if row["operation"] not in {"raw", "render_to_txt", "render_to_xml"}:
                    raise DocumentPlanError("operation row names an unknown operation")
                if not row["target_id"]:
                    raise DocumentPlanError("operation row has an empty target ID")
                if row["operation_id"] != canonical_hash(list(key)):
                    raise DocumentPlanError("operation row ID does not match identity")
                mode = row["request_mode"]
                if row["operation"] == "raw":
                    if not row["requested"] or mode != "mandatory_raw":
                        raise DocumentPlanError("raw operation intent is not mandatory")
                elif mode == "profile":
                    if not row["requested"]:
                        raise DocumentPlanError(
                            "profile operation intent is not requested"
                        )
                elif mode == "default_candidate":
                    if not row["requested"]:
                        raise DocumentPlanError(
                            "default operation intent is not requested"
                        )
                    default_candidate_counts[row["operation"]] = (
                        default_candidate_counts.get(row["operation"], 0) + 1
                    )
                elif mode == "not_requested":
                    if row["requested"]:
                        raise DocumentPlanError(
                            "excluded operation is marked requested"
                        )
                    unrequested_counts[row["operation"]] = (
                        unrequested_counts.get(row["operation"], 0) + 1
                    )
                else:
                    raise DocumentPlanError("operation row has invalid request mode")
                if row["requested"]:
                    requested_counts[row["operation"]] = (
                        requested_counts.get(row["operation"], 0) + 1
                    )
                previous = key
    except DocumentPlanError:
        raise
    except Exception as error:
        raise DocumentPlanError("operation rows are unreadable") from error
    return requested_counts, default_candidate_counts, unrequested_counts


def _merge_counts(destination: dict[str, int], counts: dict[str, int]) -> None:
    for name, count in counts.items():
        destination[name] = destination.get(name, 0) + count


def _is_version(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _validate_source_request_rows(path: Path) -> int:
    previous: str | None = None
    row_count = 0
    try:
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=resolve_parquet_read_batch_size(),
            columns=[field.name for field in SOURCE_REQUEST_SCHEMA],
        ):
            for row in batch.to_pylist():
                source_id = row["source_request_id"]
                if not source_id or not row["target_id"]:
                    raise DocumentPlanError("source request has an empty identity")
                if previous is not None and source_id <= previous:
                    raise DocumentPlanError("source requests are not sorted and unique")
                identity = [
                    row["target_id"],
                    row["source_role"],
                    row["source_origin"],
                    row["retrieval_mode"],
                    row["request_url"],
                    row["sequence"],
                    row["canonical_path"],
                ]
                if source_id != canonical_hash(identity):
                    raise DocumentPlanError("source request ID does not match identity")
                if (
                    row["source_role"] != "primary_body"
                    or not row["request_url"]
                    or not row["canonical_path"]
                ):
                    raise DocumentPlanError(
                        "source request lacks its selected body path"
                    )
                previous = source_id
                row_count += 1
    except DocumentPlanError:
        raise
    except Exception as error:
        raise DocumentPlanError("source request rows are unreadable") from error
    return row_count


def _validate_operation_input_rows(path: Path) -> int:
    previous: tuple[str, int] | None = None
    row_count = 0
    try:
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=resolve_parquet_read_batch_size(),
            columns=[field.name for field in OPERATION_INPUT_SCHEMA],
        ):
            for row in batch.to_pylist():
                key = (row["operation_id"], row["input_ordinal"])
                if previous is not None and key <= previous:
                    raise DocumentPlanError(
                        "operation inputs are not sorted and unique"
                    )
                if (
                    row["input_ordinal"] != 0
                    or row["input_role"] != "selected_target_body"
                ):
                    raise DocumentPlanError(
                        "operation input has invalid role or ordinal"
                    )
                if not row["operation_id"] or not row["source_request_id"]:
                    raise DocumentPlanError("operation input has an empty reference")
                previous = key
                row_count += 1
    except DocumentPlanError:
        raise
    except Exception as error:
        raise DocumentPlanError("operation input rows are unreadable") from error
    return row_count


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
