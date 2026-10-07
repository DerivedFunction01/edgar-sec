"""Candidate delta anti-join and idempotence checking.

Filters candidate rows against resolved active views to prevent redundant nodes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from edgar_sec.infra.storage.duckdb import copy_query_to_parquet, sql_identifier

from .spec import RelationSpec


@dataclass(frozen=True, slots=True)
class FilteredDelta:
    """Result of candidate anti-join against active lineage views."""

    is_noop: bool
    filtered_parts: dict[str, Path]
    row_counts: dict[str, int]


def filter_candidate_delta(
    con: duckdb.DuckDBPyConnection,
    specs: Sequence[RelationSpec],
    candidate_tables: Mapping[str, str],
    active_views: Mapping[str, str],
    output_dir: Path | str,
) -> FilteredDelta:
    """Anti-join candidate tables against active views and write non-duplicate parts."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filtered_parts: dict[str, Path] = {}
    row_counts: dict[str, int] = {}
    total_new_rows = 0

    for spec in specs:
        cand_table = candidate_tables.get(spec.name)
        if not cand_table:
            continue
        active_view = active_views.get(spec.name, f"active_{spec.name}")
        pk_cols = [sql_identifier(k) for k in spec.primary_key]
        join_on = " AND ".join(f"c.{k} = a.{k}" for k in pk_cols)

        # Detect new keys or value changes across non-pk columns
        all_cols = [f.name for f in spec.schema]
        non_pk_cols = [
            sql_identifier(col) for col in all_cols if col not in spec.primary_key
        ]
        if non_pk_cols and spec.merge_strategy == "upsert":
            diff_conditions = " OR ".join(
                f"c.{col} IS DISTINCT FROM a.{col}" for col in non_pk_cols
            )
            filter_query = f"""
                SELECT c.* FROM {sql_identifier(cand_table)} c
                LEFT JOIN {sql_identifier(active_view)} a ON {join_on}
                WHERE a.{pk_cols[0]} IS NULL OR ({diff_conditions})
            """
        else:
            filter_query = f"""
                SELECT c.* FROM {sql_identifier(cand_table)} c
                LEFT JOIN {sql_identifier(active_view)} a ON {join_on}
                WHERE a.{pk_cols[0]} IS NULL
            """

        dest_file = out_dir / f"{spec.name}.parquet"
        count = copy_query_to_parquet(con, filter_query, dest_file)
        if count > 0:
            filtered_parts[spec.name] = dest_file
            row_counts[spec.name] = count
            total_new_rows += count
        else:
            if dest_file.exists():
                dest_file.unlink()

    return FilteredDelta(
        is_noop=total_new_rows == 0,
        filtered_parts=filtered_parts,
        row_counts=row_counts,
    )


__all__ = ["FilteredDelta", "filter_candidate_delta"]
