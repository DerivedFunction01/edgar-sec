"""Per-dimension availability statistics for a feature snapshot: counts run in
DuckDB, so a floor's satisfiability is known before selection runs and no
dimension value is ever materialized in the Python heap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import KNOWN_DIMENSIONS
from edgar_sec.infra.storage.duckdb import connect, sql_literal

LOCATOR_TABLE = "locator_features.parquet"


class UnknownDimensionError(ValueError):
    """A statistic was requested for a dimension the policy vocabulary rejects."""


class InventoryStatistics:
    """Compute reusable counts, rarity, and availability per dimension."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.locator_path = self.snapshot_dir / LOCATOR_TABLE
        self._threads = threads
        self._memory_limit = memory_limit

    def _require_dimension(self, dimension: str) -> None:
        if dimension not in KNOWN_DIMENSIONS:
            raise UnknownDimensionError(f"unknown selection dimension: {dimension!r}")

    def value_counts(self, dimension: str) -> list[dict[str, Any]]:
        """Per-value counts of unique locators and distinct CIKs; `locator_count` counts
        distinct *documents*, the unit a floor on that dimension is denominated in.
        """
        self._require_dimension(dimension)
        query = f"""
            SELECT {dimension} AS value,
                   COUNT(DISTINCT document_locator_key) AS locator_count,
                   COUNT(DISTINCT representative_cik) AS cik_count
            FROM read_parquet({sql_literal(str(self.locator_path))})
            GROUP BY value
            ORDER BY locator_count DESC, value
        """
        with connect(threads=self._threads, memory_limit=self._memory_limit) as con:
            rows = con.execute(query).fetchall()
        return [
            {
                "value": "none" if row[0] is None else str(row[0]),
                "locator_count": int(row[1]),
                "cik_count": int(row[2]),
            }
            for row in rows
        ]

    def check_floor_feasibility(
        self, floors: dict[str, dict[str, int]]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Whether the corpus can satisfy every declared floor; `deficit` is the actionable
        field, since `feasible: false` alone sends the reader back to the policy.
        """
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for dimension, requirements in floors.items():
            available = {
                row["value"]: row["locator_count"]
                for row in self.value_counts(dimension)
            }
            report[dimension] = {}
            for value, required in requirements.items():
                supply = available.get(str(value).lower(), 0)
                report[dimension][value] = {
                    "required": int(required),
                    "available": supply,
                    "feasible": supply >= int(required),
                    "deficit": max(0, int(required) - supply),
                }
        return report

    def check_composite_feasibility(
        self, composites: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Whether each composite stratum has enough matching locators, counted at the
        locator grain.
        """
        results: list[dict[str, Any]] = []
        if not composites:
            return results
        relation = sql_literal(str(self.locator_path))
        with connect(threads=self._threads, memory_limit=self._memory_limit) as con:
            for composite in composites:
                filters = composite.get("filters", {})
                required = int(composite.get("min", 1))
                clauses: list[str] = []
                params: list[Any] = []
                for dimension, value in filters.items():
                    self._require_dimension(dimension)
                    clauses.append(f"{dimension} = ?")
                    params.append(str(value))
                where = " AND ".join(clauses) if clauses else "TRUE"
                count = con.execute(
                    f"SELECT COUNT(*) FROM read_parquet({relation}) WHERE {where}",
                    params,
                ).fetchone()
                supply = int(count[0]) if count else 0
                results.append(
                    {
                        "filters": dict(filters),
                        "required": required,
                        "available": supply,
                        "feasible": supply >= required,
                    }
                )
        return results


__all__ = [
    "LOCATOR_TABLE",
    "InventoryStatistics",
    "UnknownDimensionError",
]
