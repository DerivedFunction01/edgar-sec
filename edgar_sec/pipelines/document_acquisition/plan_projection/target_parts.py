"""Validate a target bundle's parquet parts and relation coverage."""

from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.pipelines.document_acquisition.paths import (
    form_partition_name,
    plan_target_part_path,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.relation_validation import (
    RelationValidationError,
    validate_additional_relations,
    validate_relation_coverage,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.target_contract import (
    _TARGET_SCHEMA,
    TargetPlanError,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.target_rows import (
    _validate_row,
)
from edgar_sec.pipelines.document_acquisition.schemas import PLAN_RELATION_SCHEMAS


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
