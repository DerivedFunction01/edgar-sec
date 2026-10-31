from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import part_file_name
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.pipelines.document_acquisition.paths import (
    form_partition_name,
    plan_target_part_path,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    PLAN_RELATION_SCHEMAS,
    SOURCE_REQUEST_SCHEMA,
    TARGET_OPERATION_SCHEMA,
)

_OPERATIONS = frozenset({"raw", "render_to_txt", "render_to_xml"})


class RelationValidationError(ValueError):
    pass


def _row_maps(path: Path, schema: pa.Schema):
    previous: tuple[object, ...] | None = None
    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=resolve_parquet_read_batch_size(), columns=schema.names
    ):
        for row in batch.to_pylist():
            if schema is TARGET_OPERATION_SCHEMA:
                key = (row["target_id"], row["operation"])
                if previous is not None and key <= previous:
                    raise RelationValidationError(
                        "target-operation rows are not sorted and unique"
                    )
                if row["operation"] not in _OPERATIONS:
                    raise RelationValidationError("unknown operation in plan relation")
                if row["operation_id"] != canonical_hash(list(key)):
                    raise RelationValidationError(
                        "operation ID does not match identity"
                    )
                mode = row["request_mode"]
                if row["operation"] == "raw":
                    valid_intent = row["requested"] and mode == "mandatory_raw"
                elif mode in {"profile", "default_candidate"}:
                    valid_intent = row["requested"]
                else:
                    valid_intent = not row["requested"] and mode == "not_requested"
                if not valid_intent:
                    raise RelationValidationError(
                        "operation request mode disagrees with requested flag"
                    )
                previous = key
            elif schema is SOURCE_REQUEST_SCHEMA:
                source_id = row["source_request_id"]
                if previous is not None and source_id <= previous[0]:
                    raise RelationValidationError(
                        "source requests are not sorted and unique"
                    )
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
                    raise RelationValidationError(
                        "source-request ID does not match identity"
                    )
                if (
                    row["source_role"] != "primary_body"
                    or not row["request_url"]
                    or not row["canonical_path"]
                ):
                    raise RelationValidationError(
                        "source request lacks its selected body path"
                    )
                previous = (source_id,)
            else:
                key = (row["operation_id"], row["input_ordinal"])
                if previous is not None and key <= previous:
                    raise RelationValidationError(
                        "operation inputs are not sorted and unique"
                    )
                if (
                    row["input_ordinal"] != 0
                    or row["input_role"] != "selected_target_body"
                ):
                    raise RelationValidationError("operation input is invalid")
                if not row["operation_id"] or not row["source_request_id"]:
                    raise RelationValidationError(
                        "operation input has an empty reference"
                    )
                previous = key
            yield row


def _empty_scan(relation: str) -> str:
    types = {
        pa.string(): "VARCHAR",
        pa.bool_(): "BOOLEAN",
        pa.int32(): "INTEGER",
        pa.int64(): "BIGINT",
    }
    columns = ", ".join(
        f"CAST(NULL AS {types[field.type]}) AS {field.name}"
        for field in PLAN_RELATION_SCHEMAS[relation]
    )
    return f"(SELECT {columns} WHERE FALSE)"


def _scan(relation: str, paths: dict[str, tuple[Path, ...]]) -> str:
    files = paths[relation]
    if not files:
        return _empty_scan(relation)
    return f"read_parquet({sql_path_list([str(path) for path in files])})"


def validate_additional_relations(
    root: Path,
    manifest: dict[str, Any],
    parts: list[dict[str, Any]],
    row_group_size: int,
) -> tuple[dict[str, tuple[Path, ...]], dict[str, int]]:
    relation_paths: dict[str, list[Path]] = {
        name: [] for name in PLAN_RELATION_SCHEMAS if name != "targets"
    }
    indices: dict[tuple[str, str], int] = {}
    forms: dict[str, str] = {}
    counts: Counter[str] = Counter()
    requested: Counter[str] = Counter()
    default_candidates: Counter[str] = Counter()
    unrequested: Counter[str] = Counter()
    previous_order: tuple[str, str, str] | None = None
    for descriptor in parts:
        relation = descriptor["relation"]
        form = descriptor.get("form")
        relative = descriptor.get("path")
        rows = descriptor.get("rows")
        digest = descriptor.get("sha256")
        byte_size = descriptor.get("byte_size")
        if (
            not isinstance(form, str)
            or not form
            or not isinstance(relative, str)
            or not isinstance(rows, int)
            or isinstance(rows, bool)
            or not 1 <= rows <= row_group_size
            or not is_sha256_hex_digest(digest)
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
        ):
            raise RelationValidationError("plan relation part descriptor is invalid")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise RelationValidationError("plan relation part path is unsafe")
        partition = f"form={form_partition_name(form)}"
        if partition in forms and forms[partition] != form:
            raise RelationValidationError("plan forms collide in relation partitions")
        forms[partition] = form
        key = (relation, form)
        index = indices.get(key, 0)
        if relation == "targets":
            expected = plan_target_part_path(form, index)
        else:
            expected = f"{relation}/{partition}/{part_file_name(index)}"
        order = (relation, form, relative)
        if relative != expected or (
            previous_order is not None and order <= previous_order
        ):
            raise RelationValidationError(
                "relation part paths are not sorted and unique"
            )
        previous_order = order
        indices[key] = index + 1
        if relation == "targets":
            continue
        candidate = root.joinpath(*path.parts)
        current = root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise RelationValidationError("plan relation part contains a symlink")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise RelationValidationError(
                f"plan relation part is missing or unsafe: {relative}"
            )
        if resolved.stat().st_size != byte_size or file_sha256(resolved) != digest:
            raise RelationValidationError(
                f"plan relation part digest mismatch: {relative}"
            )
        try:
            parquet = pq.ParquetFile(resolved)
            if (
                not parquet.schema_arrow.equals(
                    PLAN_RELATION_SCHEMAS[relation], check_metadata=False
                )
                or parquet.metadata.num_rows != rows
            ):
                raise RelationValidationError(
                    f"plan relation schema or row count mismatch: {relative}"
                )
            for row in _row_maps(resolved, PLAN_RELATION_SCHEMAS[relation]):
                if relation == "target_operations":
                    if row["requested"]:
                        requested[row["operation"]] += 1
                    if row["request_mode"] == "default_candidate":
                        default_candidates[row["operation"]] += 1
                    if row["request_mode"] == "not_requested":
                        unrequested[row["operation"]] += 1
        except RelationValidationError:
            raise
        except Exception as error:
            raise RelationValidationError(
                f"plan relation is unreadable: {relative}"
            ) from error
        relation_paths[relation].append(resolved)
        counts[relation] += rows
    for relation, form in indices:
        form_parts = [
            part
            for part in parts
            if part["relation"] == relation and part["form"] == form
        ]
        if any(part["rows"] != row_group_size for part in form_parts[:-1]):
            raise RelationValidationError(
                "non-final relation parts must match parquet row_group_size"
            )
    result = {name: tuple(paths) for name, paths in relation_paths.items()}
    _validate_relation_counts(
        manifest, counts, requested, default_candidates, unrequested
    )
    return result, counts


def _validate_relation_counts(
    manifest: dict[str, Any],
    counts: Counter[str],
    requested: Counter[str],
    default_candidates: Counter[str],
    unrequested: Counter[str],
) -> None:
    declared = manifest.get("relation_row_counts")
    if (
        not isinstance(declared, dict)
        or set(declared) != set(PLAN_RELATION_SCHEMAS)
        or any(type(value) is not int or value < 0 for value in declared.values())
        or declared.get("targets") != manifest.get("target_row_count")
        or any(
            declared[name] != counts.get(name, 0)
            for name in PLAN_RELATION_SCHEMAS
            if name != "targets"
        )
    ):
        raise RelationValidationError("relation counts disagree with relation parts")
    for field, observed in (
        ("requested_operation_counts", requested),
        ("default_candidate_operation_counts", default_candidates),
        ("unrequested_operation_counts", unrequested),
    ):
        declared_counts = manifest.get(field)
        if (
            not isinstance(declared_counts, dict)
            or any(
                type(value) is not int or value < 0
                for value in declared_counts.values()
            )
            or declared_counts != dict(observed)
        ):
            raise RelationValidationError(f"{field} disagree with operation rows")
    unique_sources = manifest.get("unique_source_request_count")
    if type(unique_sources) is not int or unique_sources != counts.get(
        "source_requests", 0
    ):
        raise RelationValidationError("unique source request count disagrees with rows")
    if requested.get("raw", 0) != manifest.get("target_row_count"):
        raise RelationValidationError("raw operation intent does not cover targets")


def validate_relation_coverage(
    targets: tuple[Path, ...], relations: dict[str, tuple[Path, ...]]
) -> None:
    if not targets:
        if any(relations.values()):
            raise RelationValidationError("relations exist without target rows")
        return
    scans = {
        "targets": f"read_parquet({sql_path_list([str(path) for path in targets])})",
        **{
            name: _scan(name, relations)
            for name in (
                "target_operations",
                "source_requests",
                "operation_inputs",
            )
        },
    }
    target_scan = scans["targets"]
    operation_scan = scans["target_operations"]
    source_scan = scans["source_requests"]
    input_scan = scans["operation_inputs"]
    with connect() as connection:
        dangling_ops = connection.execute(
            f"SELECT count(*) FROM {operation_scan} o LEFT JOIN {target_scan} t "
            "ON t.target_id = o.target_id WHERE t.target_id IS NULL"
        ).fetchone()[0]
        duplicate_ops = connection.execute(
            f"SELECT count(*) FROM (SELECT operation_id FROM {operation_scan} "
            "GROUP BY operation_id HAVING count(*) <> 1)"
        ).fetchone()[0]
        incomplete_ops = connection.execute(
            f"SELECT count(*) FROM (SELECT t.target_id FROM {target_scan} t "
            f"LEFT JOIN {operation_scan} o ON o.target_id = t.target_id "
            "GROUP BY t.target_id HAVING count(DISTINCT o.operation) <> 3)"
        ).fetchone()[0]
        dangling_sources = connection.execute(
            f"SELECT count(*) FROM {source_scan} s LEFT JOIN {target_scan} t "
            "ON t.target_id = s.target_id WHERE t.target_id IS NULL"
        ).fetchone()[0]
        duplicate_sources = connection.execute(
            f"SELECT count(*) FROM (SELECT source_request_id FROM {source_scan} "
            "GROUP BY source_request_id HAVING count(*) <> 1)"
        ).fetchone()[0]
        source_coverage = connection.execute(
            f"SELECT count(*) FROM (SELECT t.target_id FROM {target_scan} t "
            f"LEFT JOIN {source_scan} s ON s.target_id = t.target_id "
            "GROUP BY t.target_id, t.status HAVING "
            "(t.status = 'matched' AND count(s.source_request_id) <> 1) OR "
            "(t.status <> 'matched' AND count(s.source_request_id) <> 0))"
        ).fetchone()[0]
        mismatched_sources = connection.execute(
            f"SELECT count(*) FROM {source_scan} s JOIN {target_scan} t "
            "ON t.target_id = s.target_id WHERE s.source_role <> 'primary_body' "
            "OR s.source_origin <> t.source_origin "
            "OR s.retrieval_mode <> t.retrieval_mode "
            "OR s.request_url IS DISTINCT FROM t.target_url "
            "OR s.sequence IS DISTINCT FROM t.sequence"
        ).fetchone()[0]
        dangling_inputs = connection.execute(
            f"SELECT count(*) FROM {input_scan} i LEFT JOIN {operation_scan} o "
            "ON o.operation_id = i.operation_id LEFT JOIN "
            f"{source_scan} s ON s.source_request_id = i.source_request_id "
            "WHERE o.operation_id IS NULL OR s.source_request_id IS NULL "
            "OR s.target_id <> o.target_id"
        ).fetchone()[0]
        input_coverage = connection.execute(
            f"SELECT count(*) FROM (SELECT o.operation_id FROM {operation_scan} o "
            f"LEFT JOIN {input_scan} i ON i.operation_id = o.operation_id "
            f"LEFT JOIN {source_scan} s ON s.source_request_id = i.source_request_id "
            f"LEFT JOIN {target_scan} t ON t.target_id = o.target_id "
            "GROUP BY o.operation_id, o.requested, o.target_id, t.status "
            "HAVING (o.requested AND t.status = 'matched' AND "
            "(count(i.operation_id) <> 1 OR min(s.target_id) <> o.target_id)) OR "
            "(NOT (o.requested AND t.status = 'matched') AND "
            "count(i.operation_id) <> 0))"
        ).fetchone()[0]
    if any(
        (
            dangling_ops,
            duplicate_ops,
            incomplete_ops,
            dangling_sources,
            duplicate_sources,
            source_coverage,
            mismatched_sources,
            dangling_inputs,
            input_coverage,
        )
    ):
        raise RelationValidationError(
            "target operations, source requests, and inputs lack full matching coverage"
        )


def validate_resolved_operations(relations: dict[str, tuple[Path, ...]]) -> None:
    scans = {
        relation: (
            f"read_parquet({sql_path_list([str(path) for path in paths])})"
            if paths
            else _empty_scan(relation)
        )
        for relation, paths in relations.items()
    }
    resolved = scans["resolved_operations"]
    intents = scans["target_operations"]
    inputs = scans["operation_inputs"]
    sources = scans["source_requests"]
    targets = scans["targets"]
    with connect() as connection:
        failures = (
            connection.execute(
                f"SELECT count(*) FROM (SELECT operation_id FROM {resolved} "
                "GROUP BY operation_id HAVING count(*) <> 1)"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {intents} intent FULL OUTER JOIN {resolved} "
                "operation USING (operation_id) WHERE intent.operation_id IS NULL "
                "OR operation.operation_id IS NULL OR intent.target_id IS DISTINCT FROM "
                "operation.target_id OR intent.operation IS DISTINCT FROM operation.operation "
                "OR intent.requested IS DISTINCT FROM operation.requested "
                "OR intent.request_mode IS DISTINCT FROM operation.request_mode"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {resolved} operation LEFT JOIN {targets} target "
                "ON target.target_id = operation.target_id "
                "WHERE target.target_id IS NULL"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {resolved} operation FULL OUTER JOIN {inputs} input "
                "USING (operation_id) WHERE (operation.operation_id IS NULL) "
                "OR (input.operation_id IS NULL AND (operation.source_request_id IS NOT NULL "
                "OR operation.input_ordinal IS NOT NULL OR operation.input_role IS NOT NULL)) "
                "OR (input.operation_id IS NOT NULL AND (operation.source_request_id "
                "IS DISTINCT FROM input.source_request_id OR operation.input_ordinal "
                "IS DISTINCT FROM input.input_ordinal OR operation.input_role "
                "IS DISTINCT FROM input.input_role))"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {resolved} operation LEFT JOIN {sources} source "
                "ON source.source_request_id = operation.source_request_id "
                "WHERE operation.source_request_id IS NOT NULL AND "
                "(source.source_request_id IS NULL OR source.target_id <> operation.target_id)"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {resolved} operation WHERE "
                "(operation.request_mode = 'mandatory_raw' AND (operation.operation <> 'raw' "
                "OR NOT operation.requested)) OR "
                "(operation.operation = 'raw' AND operation.request_mode <> 'mandatory_raw') OR "
                "(operation.requested AND operation.request_mode = 'not_requested') OR "
                "(NOT operation.requested AND operation.request_mode <> 'not_requested') OR "
                "(operation.selected AND (NOT operation.requested OR "
                "operation.support_status <> 'supported')) OR "
                "(operation.support_status = 'supported' AND (operation.support_reason IS NOT NULL "
                "OR operation.capability_id IS NULL OR operation.capability_version IS NULL "
                "OR operation.handler_id IS NULL OR operation.handler_version IS NULL "
                "OR operation.output_kind IS NULL)) OR "
                "(operation.support_status = 'unsupported' AND (operation.requested = FALSE "
                "OR operation.selected OR operation.support_reason IS NULL "
                "OR operation.capability_id IS NOT NULL OR operation.capability_version IS NOT NULL "
                "OR operation.handler_id IS NOT NULL OR operation.handler_version IS NOT NULL "
                "OR operation.output_kind IS NOT NULL)) OR "
                "(operation.support_status = 'not_evaluated' AND (operation.requested "
                "OR operation.selected OR operation.support_reason IS NOT NULL "
                "OR operation.capability_id IS NOT NULL OR operation.capability_version IS NOT NULL "
                "OR operation.handler_id IS NOT NULL OR operation.handler_version IS NOT NULL "
                "OR operation.output_kind IS NOT NULL))"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM (SELECT target_id FROM {resolved} "
                "GROUP BY target_id HAVING count(*) <> 3 OR "
                "count(DISTINCT operation) <> 3)"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM (SELECT target_id FROM {resolved} "
                "WHERE request_mode = 'default_candidate' AND requested AND "
                "support_status = 'supported' GROUP BY target_id HAVING "
                "count(*) > 0 AND count(*) FILTER (WHERE selected) <> 1)"
            ).fetchone()[0],
            connection.execute(
                f"SELECT count(*) FROM {resolved} operation WHERE "
                "operation.request_mode = 'default_candidate' AND operation.selected AND "
                "EXISTS (SELECT 1 FROM "
                f"{resolved} preferred WHERE preferred.target_id = operation.target_id "
                "AND preferred.operation = 'render_to_xml' "
                "AND preferred.request_mode = 'default_candidate' AND preferred.requested "
                "AND preferred.support_status = 'supported') "
                "AND operation.operation = 'render_to_txt'"
            ).fetchone()[0],
        )
    if any(failures):
        raise RelationValidationError(
            "resolved operations disagree with intent, inputs, or support policy"
        )


__all__ = [
    "RelationValidationError",
    "validate_additional_relations",
    "validate_relation_coverage",
    "validate_resolved_operations",
]
