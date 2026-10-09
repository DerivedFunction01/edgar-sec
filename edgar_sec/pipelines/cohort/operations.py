"""Bounded DuckDB set operations over canonical cohort datasets."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb

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


class FamilyIndexNotFoundError(FileNotFoundError):
    """The requested family index is absent, unreadable, or malformed."""


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


_DELTA_QUERY = """
WITH kept AS (
    SELECT requested.ordinal, requested.cik_padded, requested.name
    FROM read_parquet(?) AS requested
    WHERE NOT EXISTS (
        SELECT 1 FROM read_parquet(?) AS base
        WHERE base.cik = requested.cik_padded
    )
)
SELECT row_number() OVER (ORDER BY ordinal) - 1 AS ordinal, cik_padded, name
FROM kept
ORDER BY ordinal
"""


def execute_delta_roster(
    requested_dataset: Path,
    base_cik_map_dataset: Path,
    output_dataset: Path,
) -> int:
    with connect() as con:
        return copy_query_to_parquet(
            con,
            _DELTA_QUERY,
            output_dataset,
            params=[_dataset(requested_dataset), _dataset(base_cik_map_dataset)],
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


def sample_cohort(
    source_dataset: Path,
    output_dataset: Path,
    *,
    method: Literal["modulo", "random"] = "modulo",
    rate_percent: float | None = None,
    sample_limit: int | None = None,
    seed: int = 42,
    family_index_dataset: Path | None = None,
    group_by_family: bool = False,
    exclude_spv: bool = False,
) -> int:
    if method not in {"modulo", "random"}:
        raise ValueError(f"unsupported sampling method: {method!r}")
    if rate_percent is not None and not 0.0 < rate_percent <= 100.0:
        raise ValueError("rate_percent must be in (0, 100]")
    if sample_limit is not None and sample_limit < 1:
        raise ValueError("sample_limit must be at least 1")
    source = Path(source_dataset).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if group_by_family and (
        family_index_dataset is None or not Path(family_index_dataset).is_file()
    ):
        raise FamilyIndexNotFoundError("family index is missing")

    params: list[object] = [str(source)]
    if group_by_family:
        family_path = Path(family_index_dataset).resolve()
        try:
            with connect() as con:
                schema = {
                    str(row[0])
                    for row in con.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?)", [str(family_path)]
                    ).fetchall()
                }
            if not {"cik", "company_family", "family_kind"}.issubset(schema):
                raise ValueError("family index schema is incomplete")
        except (duckdb.Error, OSError, TypeError, ValueError) as exc:
            raise FamilyIndexNotFoundError("family index is unreadable") from exc
        params.append(str(family_path))
        family_cte = """
        , joined AS (
            SELECT s.ordinal, s.cik_padded, s.name,
                   coalesce(nullif(f.company_family, ''), 'cik:' || s.cik_padded) AS family,
                   coalesce(f.family_kind = 'spv', false) AS is_spv
            FROM source_rows s
            LEFT JOIN read_parquet(?) f
              ON lpad(cast(f.cik AS VARCHAR), 10, '0') = s.cik_padded
        ), candidates AS (
            SELECT *, row_number() OVER (
                PARTITION BY family ORDER BY is_spv, ordinal
            ) AS family_rank
            FROM joined
            {spv_filter}
        )
        """.format(spv_filter="WHERE NOT is_spv" if exclude_spv else "")
        sampling_source = (
            "SELECT ordinal, cik_padded, name FROM candidates WHERE family_rank = 1"
        )
    else:
        family_cte = ""
        sampling_source = "SELECT ordinal, cik_padded, name FROM source_rows"

    if method == "modulo":
        params.append(rate_percent if rate_percent is not None else 100.0)
        selection = f"""
            SELECT * FROM ({sampling_source}) sample_source
            WHERE try_cast('0x' || substr(md5(cik_padded), 1, 8) AS BIGINT) % 100 < ?
        """
        if sample_limit is not None:
            selection += " ORDER BY try_cast(cik_padded AS BIGINT) LIMIT ?"
            params.append(sample_limit)
    else:
        params.append(seed)
        limit_filter = ""
        if rate_percent is not None:
            params.append(rate_percent)
            limit_filter = "sample_rank <= ceil(sample_count * ? / 100.0)"
        if sample_limit is not None:
            params.append(sample_limit)
            limit_filter = (
                f"{limit_filter} AND " if limit_filter else ""
            ) + "sample_rank <= ?"
        selection = f"""
            SELECT ordinal, cik_padded, name FROM (
                SELECT *, row_number() OVER (ORDER BY hash(cik_padded, ?)) AS sample_rank,
                       count(*) OVER () AS sample_count
                FROM ({sampling_source}) sample_source
            ) ranked
            {f"WHERE {limit_filter}" if limit_filter else ""}
        """
    query = f"""
        WITH source_rows AS (SELECT ordinal, cik_padded, name FROM read_parquet(?))
        {family_cte}
        SELECT row_number() OVER (ORDER BY try_cast(cik_padded AS BIGINT)) - 1 AS ordinal,
               cik_padded, name
        FROM ({selection}) sampled
        ORDER BY try_cast(cik_padded AS BIGINT)
    """
    with connect() as con:
        return copy_query_to_parquet(con, query, output_dataset, params=params)


__all__ = [
    "BinaryOp",
    "CohortRef",
    "ExprNode",
    "FamilyIndexNotFoundError",
    "SetDiffReport",
    "SetOpKind",
    "compile_ast_to_sql",
    "diff_cohorts",
    "execute_delta_roster",
    "execute_set_operation",
    "parse_expression",
    "sample_cohort",
    "serialize_expression",
]
