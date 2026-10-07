"""Accelerated point lookup and range pruning query engine for DAG snapshots.

Filters Parquet candidate parts at the manifest layer to eliminate unneeded disk and network I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from edgar_sec.infra.storage.duckdb import sql_identifier, sql_path_list

from .manifest import PartDescriptor
from .resolution import _empty_table_sql
from .spec import RelationSpec
from .traversal import LineageChain


def derive_accession_range(cik: str) -> tuple[str, str]:
    """Derive bounding accession range from a 10-digit SEC CIK identifier."""
    padded = cik.zfill(10)
    return f"{padded}-00-000000", f"{padded}-99-999999"


def prune_parts_for_range(
    lineage: LineageChain,
    relation_name: str,
    key_min: str | None,
    key_max: str | None,
    snapshots_root: Path | str,
) -> list[tuple[int, Path]]:
    """Return topological (rank, path) pairs whose key bounds overlap the query range."""
    root = Path(snapshots_root)
    candidates: list[tuple[int, Path]] = []
    for rank, node in enumerate(lineage.nodes):
        parts: tuple[PartDescriptor, ...] = node.relations.get(relation_name, ())
        for part in parts:
            if (
                key_min is not None
                and part.key_max is not None
                and part.key_max < key_min
            ):
                continue
            if (
                key_max is not None
                and part.key_min is not None
                and part.key_min > key_max
            ):
                continue
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
                candidates.append((rank, full.resolve()))
    return candidates


def compile_pruned_views(
    con: duckdb.DuckDBPyConnection,
    specs: Sequence[RelationSpec],
    lineage: LineageChain,
    snapshots_root: Path | str,
    relation_ranges: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> dict[str, str]:
    """Register active views covering only candidate parts for the query predicates."""
    view_names: dict[str, str] = {}
    ranges = relation_ranges or {}

    for spec in specs:
        active_name = sql_identifier(f"active_{spec.name}")
        raw_name = sql_identifier(f"_raw_{spec.name}")
        view_names[spec.name] = active_name

        key_min, key_max = ranges.get(spec.name, (None, None))
        candidate_parts = prune_parts_for_range(
            lineage, spec.name, key_min, key_max, snapshots_root
        )

        if not candidate_parts:
            empty_stmt = (
                f"CREATE OR REPLACE TEMP VIEW {raw_name} AS {_empty_table_sql(spec)}"
            )
            con.execute(empty_stmt)
            active_empty_stmt = (
                f"CREATE OR REPLACE TEMP VIEW {active_name} AS {_empty_table_sql(spec)}"
            )
            con.execute(active_empty_stmt)
            continue

        subqueries = [
            f"SELECT {rank} AS _lineage_ord, * FROM read_parquet('{str(p)}')"
            for rank, p in candidate_parts
        ]
        union_stmt = f"CREATE OR REPLACE TEMP VIEW {raw_name} AS {' UNION ALL '.join(subqueries)}"
        con.execute(union_stmt)

        pk_cols = ", ".join(sql_identifier(k) for k in spec.primary_key)
        if spec.merge_strategy == "upsert":
            upsert_stmt = f"""
                CREATE OR REPLACE TEMP VIEW {active_name} AS
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
                CREATE OR REPLACE TEMP VIEW {active_name} AS
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY {pk_cols} ORDER BY {order_expr}
                    ) AS _rnk
                    FROM {raw_name}
                )
                SELECT * EXCLUDE(_lineage_ord, _rnk) FROM ranked WHERE _rnk = 1
            """
            con.execute(append_stmt)
        else:
            default_stmt = f"CREATE OR REPLACE TEMP VIEW {active_name} AS SELECT * EXCLUDE(_lineage_ord) FROM {raw_name}"
            con.execute(default_stmt)

    return view_names


def query_point(
    con: duckdb.DuckDBPyConnection,
    spec: RelationSpec,
    lineage: LineageChain,
    snapshots_root: Path | str,
    key_value: str,
    key_column: str | None = None,
) -> list[dict[str, Any]]:
    """Execute high-speed point query with automatic range pruning."""
    col = key_column or spec.entity_key or spec.primary_key[0]
    if col == "filing_cik" and "accession" in [f.name for f in spec.schema]:
        r_min, r_max = derive_accession_range(key_value)
    else:
        r_min, r_max = key_value, key_value

    compile_pruned_views(
        con, [spec], lineage, snapshots_root, {spec.name: (r_min, r_max)}
    )
    stmt = f"SELECT * FROM active_{sql_identifier(spec.name)} WHERE {sql_identifier(col)} = ?"
    cursor = con.execute(stmt, [key_value])
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


__all__ = [
    "compile_pruned_views",
    "derive_accession_range",
    "prune_parts_for_range",
    "query_point",
]
