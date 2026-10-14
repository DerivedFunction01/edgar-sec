"""Bounded DuckDB set operations over canonical cohort datasets."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_identifier,
    sql_literal,
)

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog

SetOpKind = Literal["union", "intersect", "difference"]


@dataclass(frozen=True, slots=True)
class ExprNode:
    pass


@dataclass(frozen=True, slots=True)
class CohortRef(ExprNode):
    cohort_identifier: str


@dataclass(frozen=True, slots=True)
class BinaryOp(ExprNode):
    left: ExprNode
    right: ExprNode
    op: SetOpKind


def parse_expression(expression: str) -> ExprNode:
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("cohort expression is invalid or too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (RecursionError, SyntaxError, TypeError) as exc:
        raise ValueError("invalid cohort expression") from exc
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise ValueError("cohort expression is too complex")

    def parse(node: ast.AST) -> ExprNode:
        if isinstance(node, ast.Name):
            return CohortRef(node.id)
        if isinstance(node, ast.BinOp):
            operators = {
                ast.Add: "union",
                ast.BitAnd: "intersect",
                ast.Sub: "difference",
            }
            op = operators.get(type(node.op))
            if op is None:
                raise ValueError("unsupported cohort expression operator")
            return BinaryOp(parse(node.left), parse(node.right), op)
        raise ValueError("cohort expressions allow only names and set operators")

    return parse(tree.body)


def compile_ast_to_sql(node: ExprNode, catalog: CohortCatalog) -> str:
    definitions: list[str] = []
    next_name = 0
    node_count = 0

    def compile_node(current: ExprNode) -> str:
        nonlocal next_name, node_count
        node_count += 1
        if node_count > 256:
            raise ValueError("cohort expression is too complex")
        name = sql_identifier(f"cohort_expr_{next_name}")
        next_name += 1
        if isinstance(current, CohortRef):
            record = catalog.resolve_cohort_identifier(current.cohort_identifier)
            dataset = catalog.paths.resolve_relative_path(record.dataset_path)
            if not dataset.is_file():
                raise FileNotFoundError(dataset)
            definitions.append(
                f"{name} AS (SELECT ordinal, cik_padded, name "
                f"FROM read_parquet({sql_literal(str(dataset))}))"
            )
            return name
        if not isinstance(current, BinaryOp) or current.op not in {
            "union",
            "intersect",
            "difference",
        }:
            raise ValueError("invalid cohort expression node")

        left = sql_identifier(compile_node(current.left))
        right = sql_identifier(compile_node(current.right))
        if current.op == "union":
            eligible = (
                f"SELECT cik_padded, name, 0 AS side FROM {left} "
                f"UNION ALL SELECT cik_padded, name, 1 AS side FROM {right}"
            )
        elif current.op == "intersect":
            eligible = (
                f"SELECT l.cik_padded, l.name, 0 AS side FROM {left} l "
                f"SEMI JOIN {right} r USING (cik_padded) UNION ALL "
                f"SELECT r.cik_padded, r.name, 1 AS side FROM {right} r "
                f"SEMI JOIN {left} l USING (cik_padded)"
            )
        else:
            eligible = (
                f"SELECT l.cik_padded, l.name, 0 AS side FROM {left} l "
                f"ANTI JOIN {right} r USING (cik_padded)"
            )
        definitions.append(
            f"""{name} AS (
                WITH eligible AS ({eligible}), grouped AS (
                    SELECT cik_padded,
                           coalesce(arg_min(nullif(name, ''), side), '') AS name
                    FROM eligible
                    GROUP BY cik_padded
                )
                SELECT row_number() OVER (
                           ORDER BY try_cast(cik_padded AS BIGINT)
                       ) - 1 AS ordinal,
                       cik_padded, name
                FROM grouped
            )"""
        )
        return name

    if not isinstance(node, (CohortRef, BinaryOp)):
        raise ValueError("invalid cohort expression node")
    root = sql_identifier(compile_node(node))
    return (
        f"WITH {', '.join(definitions)} "
        f"SELECT ordinal, cik_padded, name FROM {root} ORDER BY ordinal"
    )


def serialize_expression(node: ExprNode) -> dict[str, object]:
    if isinstance(node, CohortRef):
        return {"node": "cohort_ref", "cohort_identifier": node.cohort_identifier}
    if isinstance(node, BinaryOp) and node.op in {
        "union",
        "intersect",
        "difference",
    }:
        return {
            "node": "binary_op",
            "op": node.op,
            "left": serialize_expression(node.left),
            "right": serialize_expression(node.right),
        }
    raise ValueError("invalid cohort expression node")


@dataclass(frozen=True, slots=True)
class SetDiffReport:
    left_name: str
    right_name: str
    left_total: int
    right_total: int
    intersection_count: int
    left_only_count: int
    right_only_count: int
    union_count: int
    sample_left_only: tuple[tuple[str, str], ...]
    sample_right_only: tuple[tuple[str, str], ...]


_SET_QUERY = """
WITH left_rows AS (
    SELECT cik_padded, name FROM read_parquet(?)
), right_rows AS (
    SELECT cik_padded, name FROM read_parquet(?)
), eligible AS (
    {eligible}
), grouped AS (
    SELECT cik_padded,
           coalesce(arg_min(nullif(name, ''), side), '') AS name
    FROM eligible
    GROUP BY cik_padded
), numbered AS (
    SELECT row_number() OVER (ORDER BY try_cast(cik_padded AS BIGINT)) - 1 AS ordinal,
           cik_padded, name
    FROM grouped
)
SELECT ordinal, cik_padded, name FROM numbered ORDER BY ordinal
"""

_ELIGIBLE = {
    "union": """
        SELECT cik_padded, name, 0 AS side FROM left_rows
        UNION ALL
        SELECT cik_padded, name, 1 AS side FROM right_rows
    """,
    "intersect": """
        SELECT l.cik_padded, l.name, 0 AS side
        FROM left_rows l SEMI JOIN right_rows r USING (cik_padded)
        UNION ALL
        SELECT r.cik_padded, r.name, 1 AS side
        FROM right_rows r SEMI JOIN left_rows l USING (cik_padded)
    """,
    "difference": """
        SELECT l.cik_padded, l.name, 0 AS side
        FROM left_rows l ANTI JOIN right_rows r USING (cik_padded)
    """,
}


def _dataset(path: Path | str) -> str:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return str(source)


def execute_set_operation(
    left_dataset: Path,
    right_dataset: Path,
    op: SetOpKind,
    output_dataset: Path,
) -> int:
    if op not in _ELIGIBLE:
        raise ValueError(f"unsupported set operation: {op!r}")
    query = _SET_QUERY.format(eligible=_ELIGIBLE[op])
    with connect() as con:
        return copy_query_to_parquet(
            con,
            query,
            output_dataset,
            params=[_dataset(left_dataset), _dataset(right_dataset)],
        )


def diff_cohorts(
    left_dataset: Path,
    right_dataset: Path,
    *,
    left_name: str = "A",
    right_name: str = "B",
    sample_limit: int = 5,
) -> SetDiffReport:
    if sample_limit < 0:
        raise ValueError("sample_limit must be non-negative")
    left = _dataset(left_dataset)
    right = _dataset(right_dataset)
    counts_query = """
    WITH l AS (SELECT DISTINCT cik_padded FROM read_parquet(?)),
         r AS (SELECT DISTINCT cik_padded FROM read_parquet(?))
    SELECT (SELECT count(*) FROM l),
           (SELECT count(*) FROM r),
           (SELECT count(*) FROM l SEMI JOIN r USING (cik_padded)),
           (SELECT count(*) FROM l ANTI JOIN r USING (cik_padded)),
           (SELECT count(*) FROM r ANTI JOIN l USING (cik_padded)),
           (SELECT count(*) FROM (SELECT cik_padded FROM l UNION SELECT cik_padded FROM r))
    """
    sample_query = """
    SELECT cik_padded, name FROM read_parquet(?) AS l
    WHERE {condition}
    ORDER BY try_cast(cik_padded AS BIGINT)
    LIMIT ?
    """
    with connect() as con:
        counts = con.execute(counts_query, [left, right]).fetchone()
        left_only = con.execute(
            sample_query.format(
                condition="NOT EXISTS (SELECT 1 FROM read_parquet(?) r WHERE r.cik_padded = l.cik_padded)"
            ),
            [left, right, sample_limit],
        ).fetchall()
        right_only = con.execute(
            sample_query.format(
                condition="NOT EXISTS (SELECT 1 FROM read_parquet(?) r WHERE r.cik_padded = l.cik_padded)"
            ),
            [right, left, sample_limit],
        ).fetchall()
    return SetDiffReport(
        left_name=left_name,
        right_name=right_name,
        left_total=int(counts[0]),
        right_total=int(counts[1]),
        intersection_count=int(counts[2]),
        left_only_count=int(counts[3]),
        right_only_count=int(counts[4]),
        union_count=int(counts[5]),
        sample_left_only=tuple((str(cik), str(name or "")) for cik, name in left_only),
        sample_right_only=tuple(
            (str(cik), str(name or "")) for cik, name in right_only
        ),
    )


__all__ = [
    "BinaryOp",
    "CohortRef",
    "ExprNode",
    "SetDiffReport",
    "SetOpKind",
    "compile_ast_to_sql",
    "diff_cohorts",
    "execute_set_operation",
    "parse_expression",
    "serialize_expression",
]
