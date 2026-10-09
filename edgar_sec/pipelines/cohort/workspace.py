"""Session-scoped cohort variables and immutable expression nodes."""

from __future__ import annotations

import hashlib
import json
import keyword
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet
from edgar_sec.infra.storage.object_store.store import ObjectStore

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog, CohortNotFoundError
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.operations import (
    BinaryOp,
    CohortRef,
    ExprNode,
    SetDiffReport,
    compile_ast_to_sql,
    parse_expression,
)
from edgar_sec.pipelines.cohort.query import CohortMember

_EXPRESSION_SCHEMA = "cohort_expr_ast"
_VARIABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class WorkspaceVariable:
    name: str
    target_id: str
    kind: Literal["cohort", "expression"]


class CohortWorkspace:
    def __init__(
        self,
        paths: CohortPaths,
        catalog: CohortCatalog | None = None,
        store: ObjectStore | None = None,
        session_id: str | None = None,
    ) -> None:
        self.paths = paths
        self.catalog = catalog or CohortCatalog(paths)
        self.store = store or ObjectStore(paths.catalog_file)
        catalog_file = paths.catalog_file.resolve()
        if self.catalog.paths.catalog_file.resolve() != catalog_file:
            raise ValueError("catalog must use paths.catalog_file")
        if self.store.db_path.resolve() != catalog_file:
            raise ValueError("store must use paths.catalog_file")
        self.store.initialize_schema()
        if session_id is not None:
            self._validate_session_id(session_id)
        self.session_id = (
            session_id if session_id is not None else self.store.get_active_session()
        )
        self.store.touch_session(self.session_id)

    def switch_session(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        self.store.set_active_session(session_id)
        self.session_id = session_id

    def bind_alias(self, alias_name: str, cohort_id_or_name: str) -> None:
        self._validate_variable_name(alias_name)
        record = self.catalog.resolve_cohort_identifier(cohort_id_or_name)
        self.store.upsert_alias(self.session_id, alias_name, record.cohort_id)

    def let_expression(self, var_name: str, expression_str: str) -> str:
        self._validate_variable_name(var_name)
        parsed = parse_expression(expression_str)
        stored = self._store_expression(parsed)
        target_id = stored.get("object_id")
        if target_id is None:
            target_id = stored["cohort_id"]
        self.store.upsert_alias(self.session_id, var_name, target_id)
        return target_id

    def diff(self, var1: str, var2: str) -> SetDiffReport:
        left_name, left_sql = self._variable_query(var1)
        right_name, right_sql = self._variable_query(var2)
        counts_sql = """
            WITH l AS (SELECT DISTINCT cik_padded FROM _workspace_left),
                 r AS (SELECT DISTINCT cik_padded FROM _workspace_right)
            SELECT (SELECT count(*) FROM l),
                   (SELECT count(*) FROM r),
                   (SELECT count(*) FROM l SEMI JOIN r USING (cik_padded)),
                   (SELECT count(*) FROM l ANTI JOIN r USING (cik_padded)),
                   (SELECT count(*) FROM r ANTI JOIN l USING (cik_padded)),
                   (SELECT count(*) FROM (SELECT cik_padded FROM l UNION SELECT cik_padded FROM r))
        """
        left_only_sql = f"""
            SELECT l.cik_padded, l.name FROM _workspace_left AS l
            WHERE NOT EXISTS (
                SELECT 1 FROM _workspace_right AS r WHERE r.cik_padded = l.cik_padded
            )
            ORDER BY try_cast(l.cik_padded AS BIGINT) LIMIT 5
        """
        right_only_sql = f"""
            SELECT r.cik_padded, r.name FROM _workspace_right AS r
            WHERE NOT EXISTS (
                SELECT 1 FROM _workspace_left AS l WHERE l.cik_padded = r.cik_padded
            )
            ORDER BY try_cast(r.cik_padded AS BIGINT) LIMIT 5
        """
        with connect() as connection:
            connection.execute(f"CREATE TEMP TABLE _workspace_left AS {left_sql}")
            connection.execute(f"CREATE TEMP TABLE _workspace_right AS {right_sql}")
            counts = connection.execute(counts_sql).fetchone()
            left_only = connection.execute(left_only_sql).fetchall()
            right_only = connection.execute(right_only_sql).fetchall()
        return SetDiffReport(
            left_name=left_name,
            right_name=right_name,
            left_total=int(counts[0]),
            right_total=int(counts[1]),
            intersection_count=int(counts[2]),
            left_only_count=int(counts[3]),
            right_only_count=int(counts[4]),
            union_count=int(counts[5]),
            sample_left_only=tuple(
                (str(cik), str(name or "")) for cik, name in left_only
            ),
            sample_right_only=tuple(
                (str(cik), str(name or "")) for cik, name in right_only
            ),
        )

    def peek(self, var_name: str, limit: int = 10) -> list[CohortMember]:
        if limit < 1:
            raise ValueError("limit must be positive")
        _, query = self._variable_query(var_name)
        with connect() as connection:
            rows = connection.execute(f"{query} LIMIT ?", [limit]).fetchall()
        return [
            CohortMember(int(row[0]), str(row[1]), str(row[2] or "")) for row in rows
        ]

    def save(
        self,
        var_name: str,
        output_name: str,
        *,
        description: str = "",
        tags: Sequence[str] = (),
    ) -> CohortRecord:
        expression = self._variable_expression(var_name)
        query = compile_ast_to_sql(expression, self.catalog)
        roster = hashlib.sha256()
        row_count = 0
        with connect() as connection:
            cursor = connection.execute(query)
            while batch := cursor.fetchmany(4096):
                for _, cik, _ in batch:
                    if row_count:
                        roster.update(b"\n")
                    roster.update(str(cik).encode("utf-8"))
                    row_count += 1
        roster_id = roster.hexdigest()
        cohort_id = f"c-{roster_id[:16]}"
        existing = self.catalog.get_cohort(cohort_id)

        staging_dir = self.paths.create_staging_dir(cohort_id)
        staged_dataset = staging_dir / "ciks.parquet"
        try:
            with self.paths.active_staging_lease(staging_dir):
                with connect() as connection:
                    materialized_rows = copy_query_to_parquet(
                        connection, query, staged_dataset
                    )
                if materialized_rows != row_count:
                    raise ValueError("materialized expression row count changed")
            dataset_sha256 = file_sha256(staged_dataset)
            dataset_path = self.paths.relative_path(
                self.paths.cohort_dataset_file(cohort_id)
            )
            if existing is not None:
                existing_dataset = self.paths.resolve_relative_path(
                    existing.dataset_path
                )
                if (
                    not existing_dataset.is_file()
                    or file_sha256(existing_dataset) != existing.dataset_sha256
                ):
                    raise ValueError(f"existing cohort {cohort_id!r} is corrupt")
                if (
                    existing.dataset_sha256 != dataset_sha256
                    or existing.dataset_path != dataset_path
                ):
                    raise ValueError(f"cohort {cohort_id!r} is immutable")
                return existing
            with self.paths.publication_lock():
                self.paths.publish_staging_dir(cohort_id, staging_dir)
                return self.catalog.register_cohort(
                    cohort_id=cohort_id,
                    name=output_name,
                    description=description,
                    origin_kind="set_operation",
                    origin_details={"expression": self._serialize_node(expression)},
                    roster_id=roster_id,
                    row_count=row_count,
                    distinct_cik_count=row_count,
                    dataset_sha256=dataset_sha256,
                    dataset_path=dataset_path,
                    tags=tags,
                )
        finally:
            if staging_dir.exists():
                self.paths.remove_staging_dir(staging_dir)

    def drop_var(self, var_name: str) -> bool:
        return self.store.drop_alias(self.session_id, var_name)

    def clear(self) -> None:
        self.store.clear_session(self.session_id)
        self.session_id = self.store.get_active_session()

    def list_variables(self) -> list[WorkspaceVariable]:
        variables = []
        for name, target_id in self.store.list_aliases(self.session_id).items():
            stored = self.store.get_object(target_id)
            variables.append(
                WorkspaceVariable(
                    name=name,
                    target_id=target_id,
                    kind=(
                        "expression"
                        if stored is not None
                        and stored.schema_name == _EXPRESSION_SCHEMA
                        else "cohort"
                    ),
                )
            )
        return variables

    def serialize_expression(self, expression_str: str) -> dict[str, Any]:
        resolved = self._resolve_expression(parse_expression(expression_str))
        return self._serialize_node(resolved)

    def _store_expression(self, node: ExprNode) -> dict[str, str]:
        if isinstance(node, CohortRef):
            target_id = self.store.get_alias_target(
                self.session_id, node.cohort_identifier
            )
            if target_id is not None:
                stored = self.store.get_object(target_id)
                if stored is not None:
                    if stored.schema_name != _EXPRESSION_SCHEMA:
                        raise ValueError(
                            f"unsupported object schema {stored.schema_name!r}"
                        )
                    self._validate_expression_datasets(
                        node.cohort_identifier, self._object_expression(target_id)
                    )
                    return {"object_id": target_id}
                record = self._require_cohort_dataset(node.cohort_identifier, target_id)
                return {"cohort_id": record.cohort_id}
            record = self.catalog.resolve_cohort_identifier(node.cohort_identifier)
            return {"cohort_id": record.cohort_id}
        if not isinstance(node, BinaryOp):
            raise ValueError("invalid cohort expression node")
        data = {
            "node": "binary_op",
            "op": node.op,
            "left": self._storage_node(self._store_expression(node.left)),
            "right": self._storage_node(self._store_expression(node.right)),
        }
        payload = canonical_json(data)
        object_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.store.upsert_object(
            object_id=object_id,
            schema_name=_EXPRESSION_SCHEMA,
            data=payload,
        )
        return {"object_id": object_id}

    def _resolve_expression(self, node: ExprNode) -> ExprNode:
        if isinstance(node, CohortRef):
            target_id = self.store.get_alias_target(
                self.session_id, node.cohort_identifier
            )
            if target_id is not None:
                stored = self.store.get_object(target_id)
                if stored is not None:
                    if stored.schema_name != _EXPRESSION_SCHEMA:
                        raise ValueError(
                            f"unsupported object schema {stored.schema_name!r}"
                        )
                    expression = self._object_expression(target_id)
                    self._validate_expression_datasets(
                        node.cohort_identifier, expression
                    )
                    return expression
                record = self._require_cohort_dataset(node.cohort_identifier, target_id)
                return CohortRef(record.cohort_id)
            return CohortRef(
                self.catalog.resolve_cohort_identifier(node.cohort_identifier).cohort_id
            )
        if isinstance(node, BinaryOp):
            return BinaryOp(
                self._resolve_expression(node.left),
                self._resolve_expression(node.right),
                node.op,
            )
        raise ValueError("invalid cohort expression node")

    @staticmethod
    def _storage_node(reference: dict[str, str]) -> dict[str, str]:
        if "object_id" in reference:
            return {"node": "object_ref", "object_id": reference["object_id"]}
        return {"node": "cohort_ref", "cohort_identifier": reference["cohort_id"]}

    def _object_expression(
        self, object_id: str, ancestors: frozenset[str] = frozenset()
    ) -> ExprNode:
        if object_id in ancestors:
            raise ValueError("cyclic workspace expression reference")
        stored = self.store.get_object(object_id)
        if stored is None or stored.schema_name != _EXPRESSION_SCHEMA:
            raise ValueError(f"expression object not found: {object_id!r}")
        try:
            data = json.loads(stored.data)
        except json.JSONDecodeError as exc:
            raise ValueError("stored expression is invalid JSON") from exc
        return self._expression_from_data(data, ancestors | {object_id})

    def _expression_from_data(
        self, data: dict[str, Any], ancestors: frozenset[str]
    ) -> ExprNode:
        node_type = data.get("node")
        if node_type == "cohort_ref":
            return CohortRef(data["cohort_identifier"])
        if node_type == "object_ref":
            return self._object_expression(data["object_id"], ancestors)
        if node_type == "binary_op" and data.get("op") in {
            "union",
            "intersect",
            "difference",
        }:
            return BinaryOp(
                self._expression_from_data(data["left"], ancestors),
                self._expression_from_data(data["right"], ancestors),
                data["op"],
            )
        raise ValueError("invalid stored cohort expression")

    def _variable_expression(self, var_name: str) -> ExprNode:
        target_id = self.store.get_alias_target(self.session_id, var_name)
        if target_id is None:
            record = self.catalog.resolve_cohort_identifier(var_name)
            expression = CohortRef(record.cohort_id)
            self._validate_expression_datasets(var_name, expression)
            return expression
        stored = self.store.get_object(target_id)
        if stored is not None:
            expression = self._object_expression(target_id)
            self._validate_expression_datasets(var_name, expression)
            return expression
        record = self._require_cohort_dataset(var_name, target_id)
        return CohortRef(record.cohort_id)

    def _require_cohort_dataset(self, var_name: str, cohort_id: str) -> CohortRecord:
        record = self.catalog.get_cohort(cohort_id)
        if record is None:
            raise CohortNotFoundError(
                f"Variable {var_name!r} references cohort {cohort_id!r} "
                "which no longer exists."
            )
        dataset = self.paths.resolve_relative_path(record.dataset_path)
        if not dataset.is_file():
            raise CohortNotFoundError(
                f"Variable {var_name!r} references cohort {cohort_id!r} "
                "which no longer exists."
            )
        return record

    def _validate_expression_datasets(self, var_name: str, node: ExprNode) -> None:
        if isinstance(node, CohortRef):
            self._require_cohort_dataset(var_name, node.cohort_identifier)
        elif isinstance(node, BinaryOp):
            self._validate_expression_datasets(var_name, node.left)
            self._validate_expression_datasets(var_name, node.right)

    def _variable_query(self, var_name: str) -> tuple[str, str]:
        expression = self._variable_expression(var_name)
        return var_name, compile_ast_to_sql(expression, self.catalog)

    def _serialize_node(self, node: ExprNode) -> dict[str, Any]:
        if isinstance(node, CohortRef):
            return {"node": "cohort_ref", "cohort_identifier": node.cohort_identifier}
        if isinstance(node, BinaryOp):
            return {
                "node": "binary_op",
                "op": node.op,
                "left": self._serialize_node(node.left),
                "right": self._serialize_node(node.right),
            }
        raise ValueError("invalid cohort expression node")

    @staticmethod
    def _validate_variable_name(name: str) -> None:
        if (
            not isinstance(name, str)
            or not _VARIABLE_RE.fullmatch(name)
            or keyword.iskeyword(name)
        ):
            raise ValueError(f"invalid workspace variable name: {name!r}")

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")


__all__ = ["CohortWorkspace", "WorkspaceVariable"]
