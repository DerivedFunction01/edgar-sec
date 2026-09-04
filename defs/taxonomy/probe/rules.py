"""Dynamic TableFamilySpec and cache loading helpers for the table probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import duckdb

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import TableFamilySpec
from defs.text.bow import EvidenceTier, LexicalEvidencePack


def query_probe_parquet(
    path: Path,
    *,
    where_clause: str | None = None,
    columns: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Execute a fast DuckDB SQL query directly over a probe parquet cache and return records."""
    con = duckdb.connect()
    col_str = ", ".join(columns) if columns else "*"
    query = f"SELECT {col_str} FROM read_parquet('{path}')"
    if where_clause:
        query += f" WHERE {where_clause}"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    return con.execute(query).fetch_arrow_table().to_pylist()


def count_probe_cache_tables(path: Path) -> tuple[int, int]:
    """Return (total_tables, non_toc_tables) in probe cache in milliseconds."""
    con = duckdb.connect()
    row = con.execute(
        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_toc = false) FROM read_parquet('{path}')"
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def load_parquet_records(
    path: Path, columns: list[str] | None = None
) -> list[dict[str, Any]]:
    """Load table records from a probe parquet cache using DuckDB."""
    return query_probe_parquet(path, columns=columns)


def load_external_rules(path: Path) -> dict[str, TableFamilySpec]:
    """Dynamically load TableFamilySpec definitions from an external Python or JSON file."""
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text("utf-8"))
        specs: dict[str, TableFamilySpec] = {}
        for name, entry in data.items():
            if isinstance(entry, dict):
                tiers = []
                if "required_phrases" in entry:
                    tiers.append(
                        EvidenceTier(
                            name="required",
                            priority=1,
                            value=50,
                            terms=tuple(entry["required_phrases"]),
                            match_kind="phrase",
                        )
                    )
                if "supporting_phrases" in entry:
                    tiers.append(
                        EvidenceTier(
                            name="supporting",
                            priority=2,
                            value=20,
                            terms=tuple(entry["supporting_phrases"]),
                            match_kind="ngram",
                            support=True,
                        )
                    )
                lexical = LexicalEvidencePack(
                    name=name,
                    tiers=tuple(tiers),
                    exclusion_terms=tuple((t,) for t in entry.get("exclusions", ())),
                )
                shape = ShapeConstraint(
                    min_cols=entry.get("min_cols", 2),
                    min_rows=entry.get("min_rows", 2),
                    min_numeric_density=entry.get("min_numeric_density", 0.0),
                )
                specs[name] = TableFamilySpec(
                    name=name,
                    shape=shape,
                    evidence_pack=lexical.compile(),
                )
        return specs

    spec_mod = importlib.util.spec_from_file_location("dynamic_rules", path)
    if spec_mod is None or spec_mod.loader is None:
        raise ImportError(f"Could not load rules module from {path}")
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)

    loaded_specs: dict[str, TableFamilySpec] = {}
    for attr_name in dir(mod):
        val = getattr(mod, attr_name)
        if isinstance(val, TableFamilySpec):
            loaded_specs[val.name] = val
        elif isinstance(val, dict):
            for v in val.values():
                if isinstance(v, TableFamilySpec):
                    loaded_specs[v.name] = v

    return loaded_specs


__all__ = [
    "load_external_rules",
    "load_parquet_records",
]
