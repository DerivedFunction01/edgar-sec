"""Validate target bundles and stream their work-order projection."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import accession_hyphenated, validate_archive_url
from edgar_sec.domain.forms.families.processing_profiles import (
    get_lazy_index_trigger,
    LAZY_INDEX_FORM_FAMILIES,
)
from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME, part_file_name
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
    WORK_ORDER_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.paths import (
    form_partition_name,
    plan_target_part_path,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_RELATION_SCHEMAS,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.relation_validation import (
    RelationValidationError,
    validate_additional_relations,
    validate_relation_coverage,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    iter_resolved_operation_batches,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    RESOLVED_OPERATION_SCHEMA_VERSION,
    target_relation_schema,
    target_relation_schema_version,
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)

_TARGET_SCHEMA = target_relation_schema()
_TARGET_SCHEMA_VERSION = target_relation_schema_version()
_PLAN_BUNDLE_SCHEMA_VERSION = target_plan_bundle_schema_version()
_TARGET_MATCHER_VERSION = target_plan_matcher_version()
_STATUSES = frozenset(
    {
        "matched",
        "not_filed",
        "required_missing",
        "ambiguous",
        "unresolved",
        "constructed_candidate",
    }
)
_RETRIEVAL_MODES = frozenset(
    {"direct_url", "bundle_sequence", "constructed_package", "none"}
)
_SELECTORS = frozenset({"submitted_primary", "exact_form_with_lazy_index"})


class TargetPlanError(ValueError):
    """A target bundle or its work-order projection is invalid."""


@dataclass(frozen=True, slots=True)
class WorkOrderProjection:
    plan_id: str
    plan_digest: str
    bundle_schema_version: int
    matcher_version: str
    target_schema_version: int
    target_operation_schema_version: int
    source_request_schema_version: int
    operation_input_schema_version: int
    resolved_operation_schema_version: int
    catalog_plan_id: str
    catalog_plan_digest: str
    inventory_snapshot_id: str | None
    inventory_snapshot_digest: str | None
    target_row_count: int
    executable_count: int
    skipped_count: int
    parquet_path: Path
    relation_parts: dict[str, list[dict[str, Any]]]
    relation_counts: dict[str, int]
    relation_digests: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ValidatedPlan:
    root: Path
    manifest: dict[str, Any]
    parts: tuple[Path, ...]
    relations: dict[str, tuple[Path, ...]]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TargetPlanError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


def _read_manifest(root: Path) -> dict[str, Any]:
    path = root / PLAN_FILE_NAME
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root)
    ):
        raise TargetPlanError("target-plan manifest is missing or unsafe")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TargetPlanError) as error:
        raise TargetPlanError("target-plan manifest is unreadable") from error
    if not isinstance(value, dict):
        raise TargetPlanError("target-plan manifest must be an object")
    return value


def _validate_manifest(plan_dir: Path) -> tuple[Path, dict[str, Any]]:
    if plan_dir.is_symlink() or not plan_dir.is_dir():
        raise TargetPlanError("target-plan directory is missing or unsafe")
    root = plan_dir.resolve()
    manifest = _read_manifest(root)
    plan_id = manifest.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id or root.name != plan_id:
        raise TargetPlanError("plan ID does not match its bundle directory")
    bundle_schema_version = manifest.get("bundle_schema_version")
    if (
        type(bundle_schema_version) is not int
        or bundle_schema_version != _PLAN_BUNDLE_SCHEMA_VERSION
    ):
        raise TargetPlanError(
            "missing or unsupported target-plan bundle schema version; "
            f"requires bundle version {_PLAN_BUNDLE_SCHEMA_VERSION}"
        )
    if manifest.get("matcher_version") != _TARGET_MATCHER_VERSION:
        raise TargetPlanError(
            f"unsupported target matcher version; requires {_TARGET_MATCHER_VERSION}"
        )
    target_schema_version = manifest.get("target_schema_version")
    if (
        type(target_schema_version) is not int
        or target_schema_version != _TARGET_SCHEMA_VERSION
    ):
        raise TargetPlanError("unsupported target schema version")
    schema_versions = {
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
    }
    for name, expected in schema_versions.items():
        value = manifest.get(name)
        if type(value) is not int or value != expected:
            raise TargetPlanError(f"unsupported or mismatched {name}")
    plan_digest = manifest.get("plan_digest")
    unsigned = dict(manifest)
    unsigned.pop("plan_digest", None)
    if not is_sha256_hex_digest(plan_digest) or canonical_hash(unsigned) != plan_digest:
        raise TargetPlanError("target-plan manifest digest mismatch")
    identity = manifest.get("plan_identity")
    if not isinstance(identity, dict):
        raise TargetPlanError("target-plan identity is missing")
    if any(
        type(identity.get(name)) is not int or identity.get(name) != expected
        for name, expected in schema_versions.items()
    ):
        raise TargetPlanError("plan relation schema versions do not match identity")
    identity_bundle_schema_version = identity.get("bundle_schema_version")
    if (
        type(identity_bundle_schema_version) is not int
        or identity_bundle_schema_version != _PLAN_BUNDLE_SCHEMA_VERSION
    ):
        raise TargetPlanError(
            "missing or unsupported bundle schema version in target-plan identity"
        )
    if identity.get("matcher_version") != _TARGET_MATCHER_VERSION:
        raise TargetPlanError(
            "unsupported target matcher version in target-plan identity"
        )
    identity_target_schema_version = identity.get("target_schema_version")
    if (
        type(identity_target_schema_version) is not int
        or identity_target_schema_version != _TARGET_SCHEMA_VERSION
        or manifest.get("target_schema_version") != identity_target_schema_version
        or manifest.get("matcher_version") != identity.get("matcher_version")
        or manifest.get("profile_digest") != identity.get("profile_digest")
        or manifest.get("catalog_plan_id") != identity.get("catalog_plan_id")
        or manifest.get("catalog_plan_digest") != identity.get("catalog_plan_digest")
        or manifest.get("inventory_snapshot_id")
        != identity.get("inventory_snapshot_id")
        or manifest.get("inventory_snapshot_digest")
        != identity.get("inventory_snapshot_digest")
    ):
        raise TargetPlanError("target-plan metadata does not match its identity")
    if f"dplan_{canonical_hash(identity)[:32]}" != plan_id:
        raise TargetPlanError("plan ID does not match its canonical identity")
    if not is_sha256_hex_digest(manifest.get("profile_digest")):
        raise TargetPlanError("profile digest is invalid")
    if not isinstance(manifest.get("profile_id"), str) or not manifest["profile_id"]:
        raise TargetPlanError("target plan is missing its profile ID")
    for name in ("profile_schema_version", "profile_version"):
        if not isinstance(manifest.get(name), str) or not manifest[name]:
            raise TargetPlanError(f"target plan is missing {name}")
    catalog_id = manifest.get("catalog_plan_id")
    catalog_digest = manifest.get("catalog_plan_digest")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise TargetPlanError("catalog plan ID is required")
    if not is_sha256_hex_digest(catalog_digest):
        raise TargetPlanError("catalog plan digest is required and must be SHA-256")
    inventory_id = manifest.get("inventory_snapshot_id")
    inventory_digest = manifest.get("inventory_snapshot_digest")
    if (inventory_id is None) != (inventory_digest is None):
        raise TargetPlanError(
            "inventory snapshot ID and digest must be pinned together"
        )
    if inventory_id is not None and (
        not isinstance(inventory_id, str)
        or not inventory_id
        or not is_sha256_hex_digest(inventory_digest)
    ):
        raise TargetPlanError("inventory snapshot pin is invalid")
    count = manifest.get("target_row_count")
    statuses = manifest.get("status_counts")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or not isinstance(statuses, dict)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in statuses.values()
        )
        or sum(statuses.values()) != count
    ):
        raise TargetPlanError("target-plan row counts are invalid")
    return root, manifest


def _validate_url(url: object, accession: str, *, bundle: bool) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise TargetPlanError("matched target is missing a valid SEC URL")
    try:
        accession_number = AccessionNumber(accession)
        archive = validate_archive_url(url, accession_number)
    except ValueError as error:
        raise TargetPlanError(
            "target URL is outside the accession's SEC archive"
        ) from error
    if (
        bundle
        and archive.document_path
        != f"{accession_hyphenated(str(accession_number))}.txt"
    ):
        raise TargetPlanError(
            "bundle URL is not the accession's canonical submission file"
        )
    return url


def _validate_row(
    row: dict[str, Any],
    plan_id: str,
    has_inventory_pin: bool,
    form: str,
) -> None:
    if row["form"] != form:
        raise TargetPlanError("target row form disagrees with its partition")
    try:
        accession = AccessionNumber(row["accession"])
    except (TypeError, ValueError) as error:
        raise TargetPlanError("target row has an invalid accession") from error
    if row["target_id"] != canonical_hash(
        [
            plan_id,
            row["accession"],
            row["request_id"],
            row["inventory_entry_id"],
            row["status"],
        ]
    ):
        raise TargetPlanError("target row ID does not match its identity")
    if row["status"] not in _STATUSES:
        raise TargetPlanError("target row has an unsupported status")
    if row["source_origin"] not in {"inventory_index", "catalog_direct"}:
        raise TargetPlanError("target row has an unsupported source origin")
    if row["retrieval_mode"] not in _RETRIEVAL_MODES:
        raise TargetPlanError("target row has an unsupported retrieval mode")
    if row["catalog_direct_selection"] not in (None, *_SELECTORS):
        raise TargetPlanError("target row has an unsupported pinned selector")
    if has_inventory_pin:
        if row["source_origin"] != "inventory_index":
            raise TargetPlanError(
                "inventory-pinned plan contains a non-inventory target"
            )
    elif (
        row["source_origin"] != "catalog_direct"
        or row["target_role"] != "primary"
        or row["target_type"] != "primary"
    ):
        raise TargetPlanError(
            "null inventory pin is valid only for catalog-only primary targets"
        )
    sequence = row["sequence"]
    if sequence is not None and (
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
    ):
        raise TargetPlanError("target sequence must be a positive integer")
    size = row["byte_size"]
    if size is not None and (
        isinstance(size, bool) or not isinstance(size, int) or size < 0
    ):
        raise TargetPlanError("target byte_size must be a non-negative integer")
    if row["retrieval_mode"] in {"direct_url", "bundle_sequence"}:
        if row["target_url"] is not None:
            _validate_url(
                row["target_url"],
                str(accession),
                bundle=row["retrieval_mode"] == "bundle_sequence",
            )
        if row["status"] == "matched" and row["target_url"] is None:
            raise TargetPlanError("matched target is missing its SEC URL")
        if (
            row["status"] == "matched"
            and row["retrieval_mode"] == "bundle_sequence"
            and sequence is None
        ):
            raise TargetPlanError(
                "bundle_sequence target is missing its positive sequence"
            )


def _validate_parts(
    root: Path, manifest: dict[str, Any]
) -> tuple[tuple[Path, ...], dict[str, tuple[Path, ...]]]:
    row_group_size = manifest.get("row_group_size")
    if (
        not isinstance(row_group_size, int)
        or isinstance(row_group_size, bool)
        or row_group_size < 1
    ):
        raise TargetPlanError("target-plan manifest row_group_size is invalid")
    read_batch_size = resolve_parquet_read_batch_size()
    parts = manifest.get("parts")
    if not isinstance(parts, list):
        raise TargetPlanError("target-plan parts must be an array")
    if any(
        not isinstance(part, dict) or part.get("relation") not in PLAN_RELATION_SCHEMAS
        for part in parts
    ):
        raise TargetPlanError("target-plan relation part descriptor is invalid")
    all_parts = parts
    parts = [part for part in all_parts if part["relation"] == "targets"]
    paths: list[Path] = []
    declared: set[Path] = set()
    indices: dict[str, int] = {}
    forms: dict[str, str] = {}
    observed_statuses: Counter[str] = Counter()
    observed_origins: Counter[str] = Counter()
    previous_order: tuple[str, str] | None = None
    for descriptor in parts:
        if "byte_size" not in descriptor:
            raise TargetPlanError(
                "target part descriptor is missing declared byte_size; manifest contract must be updated"
            )
        relative, form, rows, digest, byte_size = (
            descriptor.get("path"),
            descriptor.get("form"),
            descriptor.get("rows"),
            descriptor.get("sha256"),
            descriptor.get("byte_size"),
        )
        if (
            not isinstance(relative, str)
            or not isinstance(form, str)
            or not form
            or not isinstance(rows, int)
            or isinstance(rows, bool)
            or not 1 <= rows <= row_group_size
            or not is_sha256_hex_digest(digest)
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
        ):
            raise TargetPlanError("target part descriptor is invalid")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise TargetPlanError("target part path is unsafe")
        partition = form_partition_name(form)
        if partition in forms and forms[partition] != form:
            raise TargetPlanError("target forms collide in partition names")
        forms[partition] = form
        index = indices.get(form, 0)
        expected = plan_target_part_path(form, index)
        if relative != expected:
            raise TargetPlanError("target part paths are not numbered and sorted")
        order = (form, relative)
        if previous_order is not None and order <= previous_order:
            raise TargetPlanError("target part descriptors are not sorted")
        previous_order = order
        resolved = (root / Path(*path.parts)).resolve()
        candidate = root / Path(*path.parts)
        if (
            candidate.is_symlink()
            or not resolved.is_relative_to(root)
            or not resolved.is_file()
        ):
            raise TargetPlanError(f"target part is missing or unsafe: {relative}")
        if resolved.stat().st_size != byte_size:
            raise TargetPlanError(f"target part byte_size mismatch: {relative}")
        if file_sha256(resolved) != digest:
            raise TargetPlanError(f"target part digest mismatch: {relative}")
        try:
            parquet = pq.ParquetFile(resolved)
            if (
                not parquet.schema_arrow.equals(_TARGET_SCHEMA, check_metadata=False)
                or parquet.metadata.num_rows != rows
            ):
                raise TargetPlanError(
                    f"target part schema or row count mismatch: {relative}"
                )
            previous_row: tuple[str, str, str, str] | None = None
            for batch in parquet.iter_batches(batch_size=read_batch_size):
                columns = tuple(batch.columns)
                for row_index in range(batch.num_rows):
                    row = {
                        name: column[row_index].as_py()
                        for name, column in zip(
                            _TARGET_SCHEMA.names, columns, strict=True
                        )
                    }
                    _validate_row(
                        row,
                        str(manifest["plan_id"]),
                        manifest["inventory_snapshot_id"] is not None,
                        form,
                    )
                    key = (
                        row["accession"],
                        row["request_id"],
                        row["inventory_entry_id"] or "",
                        row["status"],
                    )
                    if previous_row is not None and key < previous_row:
                        raise TargetPlanError("target rows are not canonically sorted")
                    previous_row = key
                    observed_statuses[row["status"]] += 1
                    observed_origins[row["source_origin"]] += 1
        except TargetPlanError:
            raise
        except Exception as error:
            raise TargetPlanError(f"target part is unreadable: {relative}") from error
        indices[form] = index + 1
        paths.append(resolved)
        declared.add(resolved)
    for form, count in indices.items():
        form_parts = [part for part in parts if part["form"] == form]
        if any(part["rows"] != row_group_size for part in form_parts[:-1]):
            raise TargetPlanError(
                "non-final target parts must match parquet row_group_size"
            )
    actual: set[Path] = set()
    if root.exists():
        for item in root.rglob("*.parquet"):
            if item.is_symlink():
                raise TargetPlanError("target bundle contains a symlink")
            if item.is_file():
                actual.add(item.resolve())
    target_declared = {path for path in declared}
    if not target_declared.issubset(actual):
        raise TargetPlanError("target bundle has missing target Parquet parts")
    target_count = manifest["target_row_count"]
    if sum(observed_statuses.values()) != target_count:
        raise TargetPlanError("target part rows do not match target_row_count")
    if dict(observed_statuses) != manifest["status_counts"]:
        raise TargetPlanError("target status counts disagree with the manifest")
    origins = manifest.get("origin_counts")
    if (
        not isinstance(origins, dict)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in origins.values()
        )
        or dict(observed_origins) != origins
    ):
        raise TargetPlanError("target origin counts disagree with the manifest")
    if paths:
        with connect() as con:
            duplicate_count = con.execute(
                "SELECT count(*) FROM (SELECT target_id FROM read_parquet("
                f"{sql_path_list([str(path) for path in paths])}) "
                "GROUP BY target_id HAVING count(*) > 1)"
            ).fetchone()[0]
        if duplicate_count:
            raise TargetPlanError("target IDs are not unique")
    try:
        additional, relation_counts = validate_additional_relations(
            root, manifest, all_parts, row_group_size
        )
    except RelationValidationError as error:
        raise TargetPlanError(str(error)) from error
    all_declared = declared | {
        path for relation_paths in additional.values() for path in relation_paths
    }
    if actual != all_declared:
        raise TargetPlanError("target bundle has undeclared or missing relation parts")
    expected_counts = {
        relation: relation_counts.get(relation, 0) for relation in PLAN_RELATION_SCHEMAS
    }
    expected_counts["targets"] = target_count
    if manifest.get("relation_row_counts") != expected_counts:
        raise TargetPlanError("plan relation counts disagree with its part rows")
    try:
        validate_relation_coverage(tuple(paths), additional)
    except RelationValidationError as error:
        raise TargetPlanError(str(error)) from error
    return tuple(paths), additional


def _validate_target_plan(plan_dir: Path) -> _ValidatedPlan:
    try:
        root, manifest = _validate_manifest(plan_dir)
        parts, relations = _validate_parts(root, manifest)
    except TargetPlanError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise TargetPlanError(f"target bundle is invalid: {error}") from error
    return _ValidatedPlan(root, manifest, parts, relations)


def _iter_projected_batches(parts: tuple[Path, ...]):
    if not parts:
        return
    batch_size = resolve_parquet_read_batch_size()
    reason = (
        "CASE "
        "WHEN status = 'constructed_candidate' "
        "OR retrieval_mode = 'constructed_package' "
        "THEN 'candidate_not_authorized' "
        "WHEN status <> 'matched' THEN 'target_not_matched' "
        "WHEN retrieval_mode NOT IN ('direct_url', 'bundle_sequence') "
        "THEN 'unsupported_retrieval_mode' ELSE NULL END"
    )
    lazy_index_triggers = {
        family: trigger
        for family in sorted(LAZY_INDEX_FORM_FAMILIES)
        if (trigger := get_lazy_index_trigger(family)) is not None
    }
    eligible_forms_sql = ", ".join(
        sql_literal(family) for family in lazy_index_triggers
    )
    trigger_id_sql = (
        "CASE form "
        + " ".join(
            f"WHEN {sql_literal(family)} THEN {sql_literal(trigger_id)}"
            for family, (trigger_id, _) in lazy_index_triggers.items()
        )
        + " ELSE NULL END"
    )
    trigger_version_sql = (
        "CASE form "
        + " ".join(
            f"WHEN {sql_literal(family)} THEN {sql_literal(version)}"
            for family, (_, version) in lazy_index_triggers.items()
        )
        + " ELSE NULL END"
    )
    trigger_predicate = (
        "catalog_direct_selection = 'exact_form_with_lazy_index' "
        "AND source_origin = 'catalog_direct' "
        "AND target_role = 'primary' "
        f"AND form IN ({eligible_forms_sql})"
    )
    query = (
        "SELECT target.*, ("
        f"{reason} IS NULL) AS executable, {reason} AS skip_reason "
        f", CASE WHEN {trigger_predicate} THEN ({trigger_id_sql}) "
        "ELSE NULL END AS lazy_index_trigger_id, "
        f"CASE WHEN {trigger_predicate} THEN ({trigger_version_sql}) "
        "ELSE NULL END AS lazy_index_trigger_version "
        f"FROM read_parquet({sql_path_list([str(path) for path in parts])}, hive_partitioning=false) AS target "
        "ORDER BY form, accession, request_id, "
        "COALESCE(inventory_entry_id, ''), status"
    )
    with connect() as con:
        reader = con.execute(query).to_arrow_reader(batch_size)
        for batch in reader:
            yield batch.cast(WORK_ORDER_SCHEMA)


def load_acquisition_work_order(
    plan_dir: str | os.PathLike[str],
    parquet_path: str | os.PathLike[str],
) -> WorkOrderProjection:
    """Validate an entire bundle, then atomically stream its work-order rows."""
    validated = _validate_target_plan(Path(plan_dir))
    destination = Path(parquet_path).resolve()
    if destination == validated.root or destination.is_relative_to(validated.root):
        raise TargetPlanError(
            "work-order output must not modify the immutable target bundle"
        )
    if os.path.lexists(destination):
        raise TargetPlanError("work-order output already exists")
    manifest = validated.manifest
    executable_count = skipped_count = 0
    writer = StagedParquetWriter(destination, WORK_ORDER_SCHEMA)
    relation_parts: dict[str, list[dict[str, Any]]] = {
        "targets": [],
        **{name: [] for name in validated.relations},
        "resolved_operations": [],
    }
    try:
        for batch in _iter_projected_batches(validated.parts):
            batch_executable_count = int(
                pc.sum(
                    pc.cast(
                        batch.column(batch.schema.get_field_index("executable")),
                        pa.int64(),
                    )
                ).as_py()
            )
            executable_count += batch_executable_count
            skipped_count += batch.num_rows - batch_executable_count
            writer.write_batch(batch)
        writer.commit(expected_count=manifest["target_row_count"])
        relation_parts["targets"].append(
            {
                "path": destination.name,
                "row_count": manifest["target_row_count"],
                "byte_size": destination.stat().st_size,
                "sha256": file_sha256(destination),
            }
        )
        for relation, paths in validated.relations.items():
            for source in paths:
                original = source.relative_to(validated.root)
                output = destination.parent / original
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() or output.is_symlink():
                    raise TargetPlanError("work-order relation output already exists")
                shutil.copyfile(source, output)
                relation_parts[relation].append(
                    {
                        "path": original.as_posix(),
                        "row_count": pq.ParquetFile(source).metadata.num_rows,
                        "byte_size": output.stat().st_size,
                        "sha256": file_sha256(output),
                    }
                )
        resolved_path = destination.parent / "resolved_operations" / part_file_name(0)
        resolved_writer = StagedParquetWriter(resolved_path, RESOLVED_OPERATION_SCHEMA)
        try:
            for batch in iter_resolved_operation_batches(
                validated.parts,
                validated.relations["target_operations"],
                validated.relations["source_requests"],
                validated.relations["operation_inputs"],
            ):
                resolved_writer.write_batch(batch)
            resolved_writer.commit(
                expected_count=manifest["relation_row_counts"]["target_operations"]
            )
        except Exception:
            resolved_writer.reset()
            resolved_path.unlink(missing_ok=True)
            raise
        relation_parts["resolved_operations"].append(
            {
                "path": f"resolved_operations/{part_file_name(0)}",
                "row_count": manifest["relation_row_counts"]["target_operations"],
                "byte_size": resolved_path.stat().st_size,
                "sha256": file_sha256(resolved_path),
            }
        )
    except Exception:
        writer.reset()
        destination.unlink(missing_ok=True)
        for relation, descriptors in relation_parts.items():
            if relation == "targets":
                continue
            for descriptor in descriptors:
                (destination.parent / descriptor["path"]).unlink(missing_ok=True)
        raise
    relation_counts = {
        relation: sum(part["row_count"] for part in descriptors)
        for relation, descriptors in relation_parts.items()
    }
    relation_digests = {
        relation: canonical_hash(
            [
                [
                    f"work_order/{part['path']}",
                    part["row_count"],
                    part["byte_size"],
                    part["sha256"],
                ]
                for part in descriptors
            ]
        )
        for relation, descriptors in relation_parts.items()
    }
    return WorkOrderProjection(
        plan_id=manifest["plan_id"],
        plan_digest=manifest["plan_digest"],
        bundle_schema_version=_PLAN_BUNDLE_SCHEMA_VERSION,
        matcher_version=_TARGET_MATCHER_VERSION,
        target_schema_version=_TARGET_SCHEMA_VERSION,
        target_operation_schema_version=TARGET_OPERATION_SCHEMA_VERSION,
        source_request_schema_version=SOURCE_REQUEST_SCHEMA_VERSION,
        operation_input_schema_version=OPERATION_INPUT_SCHEMA_VERSION,
        resolved_operation_schema_version=RESOLVED_OPERATION_SCHEMA_VERSION,
        catalog_plan_id=manifest["catalog_plan_id"],
        catalog_plan_digest=manifest["catalog_plan_digest"],
        inventory_snapshot_id=manifest["inventory_snapshot_id"],
        inventory_snapshot_digest=manifest["inventory_snapshot_digest"],
        target_row_count=manifest["target_row_count"],
        executable_count=int(executable_count),
        skipped_count=int(skipped_count),
        parquet_path=destination,
        relation_parts=relation_parts,
        relation_counts=relation_counts,
        relation_digests=relation_digests,
    )


__all__ = ["TargetPlanError", "WorkOrderProjection", "load_acquisition_work_order"]
