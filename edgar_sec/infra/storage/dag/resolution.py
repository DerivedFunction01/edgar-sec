"""Dynamic DuckDB relational view compilation and canonical fingerprinting.

Compiles virtual active views from topological lineage nodes without domain hardcoding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import duckdb

from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_path_list

from .spec import RelationSpec
from .traversal import LineageChain


def _empty_table_sql(spec: RelationSpec) -> str:
    cols = []
    for field in spec.schema:
        name = sql_identifier(field.name)
        arrow_type = str(field.type)
        duck_type = "VARCHAR"
        if "int" in arrow_type:
            duck_type = "BIGINT"
        elif "bool" in arrow_type:
            duck_type = "BOOLEAN"
        elif "double" in arrow_type or "float" in arrow_type:
            duck_type = "DOUBLE"
        cols.append(f"CAST(NULL AS {duck_type}) AS {name}")
    return f"SELECT {', '.join(cols)} WHERE false"


def compile_virtual_views(
    con: duckdb.DuckDBPyConnection,
    specs: Sequence[RelationSpec],
    lineage: LineageChain,
    snapshots_root: Path | str,
) -> dict[str, str]:
    """Dynamically register active DuckDB views for each RelationSpec."""
    root = Path(snapshots_root)
    view_names: dict[str, str] = {}

    for rank, node in enumerate(lineage.nodes):
        pass  # rank is node index in topological order

    for spec in specs:
        table_name = sql_identifier(spec.name)
        raw_name = sql_identifier(f"_raw_{spec.name}")
        active_name = sql_identifier(f"active_{spec.name}")
        view_names[spec.name] = active_name

        subqueries: list[str] = []
        for rank, node in enumerate(lineage.nodes):
            parts = node.relations.get(spec.name, ())
            if not parts:
                continue
            part_paths: list[str] = []
            for part in parts:
                p = Path(part.path)
                if p.is_absolute():
                    full = p
                elif (root / node.snapshot_id / p).is_file():
                    full = root / node.snapshot_id / p
                elif (root / p).is_file():
                    full = root / p
                else:
                    full = root / node.snapshot_id / p
                if full.is_file():
                    part_paths.append(str(full.resolve()))
            if part_paths:
                subqueries.append(
                    f"SELECT {rank} AS _lineage_ord, * FROM read_parquet({sql_path_list(part_paths)})"
                )

        if not subqueries:
            empty_stmt = f"CREATE TEMP VIEW {raw_name} AS {_empty_table_sql(spec)}"
            con.execute(empty_stmt)
            active_empty_stmt = (
                f"CREATE TEMP VIEW {active_name} AS {_empty_table_sql(spec)}"
            )
            con.execute(active_empty_stmt)
            continue

        union_stmt = f"CREATE TEMP VIEW {raw_name} AS {' UNION ALL '.join(subqueries)}"
        con.execute(union_stmt)
        pk_cols = ", ".join(sql_identifier(k) for k in spec.primary_key)

        if spec.merge_strategy == "upsert":
            upsert_stmt = f"""
                CREATE TEMP VIEW {active_name} AS
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY {pk_cols} ORDER BY _lineage_ord DESC
                    ) AS _rnk
                    FROM {raw_name}
                )
                SELECT * EXCLUDE(_lineage_ord, _rnk) FROM ranked WHERE _rnk = 1
            """
            con.execute(upsert_stmt)

        elif spec.merge_strategy == "append":
            if spec.tie_breaker_column:
                tie = sql_identifier(spec.tie_breaker_column)
                direction = "ASC" if spec.tie_breaker_op == "min" else "DESC"
                order_expr = f"{tie} {direction}, _lineage_ord {direction}"
            else:
                order_expr = "_lineage_ord ASC"
            append_stmt = f"""
                CREATE TEMP VIEW {active_name} AS
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY {pk_cols} ORDER BY {order_expr}
                    ) AS _rnk
                    FROM {raw_name}
                )
                SELECT * EXCLUDE(_lineage_ord, _rnk) FROM ranked WHERE _rnk = 1
            """
            con.execute(append_stmt)

        elif spec.merge_strategy == "scoped_mask":
            parent_table = sql_identifier(spec.parent_relation or "")
            parent_join_keys = spec.parent_join_key or spec.primary_key
            p_join_cols = ", ".join(sql_identifier(k) for k in parent_join_keys)
            join_conditions = " AND ".join(
                f"c.{sql_identifier(k)} = p.{sql_identifier(k)}"
                for k in parent_join_keys
            )
            mask_stmt = f"""
                CREATE TEMP VIEW {active_name} AS
                WITH winning_parent AS (
                    SELECT {p_join_cols}, _lineage_ord
                    FROM (
                        SELECT {p_join_cols}, _lineage_ord,
                               ROW_NUMBER() OVER (
                                   PARTITION BY {p_join_cols} ORDER BY _lineage_ord DESC
                               ) AS _rnk
                        FROM {sql_identifier(f"_raw_{parent_table}")}
                    ) WHERE _rnk = 1
                )
                SELECT c.* EXCLUDE(_lineage_ord)
                FROM {raw_name} c
                JOIN winning_parent p
                  ON {join_conditions}
                 AND c._lineage_ord = p._lineage_ord
            """
            con.execute(mask_stmt)

    return view_names


def compute_logical_fingerprint(
    con: duckdb.DuckDBPyConnection,
    specs: Sequence[RelationSpec],
) -> str:
    """Streamed deterministic SHA-256 digest over active views."""
    hasher = hashlib.sha256()
    for spec in specs:
        view = sql_identifier(f"active_{spec.name}")
        order_cols = ", ".join(sql_identifier(k) for k in spec.primary_key)
        select_stmt = f"SELECT * FROM {view} ORDER BY {order_cols}"
        result = con.execute(select_stmt)
        batch_size = resolve_read_batch_size()
        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break
            for row in batch:
                hasher.update(canonical_json(list(row)).encode("utf-8"))
    return hasher.hexdigest()


__all__ = ["compile_virtual_views", "compute_logical_fingerprint"]
