"""Per-dimension availability statistics for a feature snapshot: counts run in
DuckDB, and value distributions stream one row at a time rather than being retained
as a Python collection.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import KNOWN_DIMENSIONS
from edgar_sec.engine.selection.snapshot import load_snapshot_paths
from edgar_sec.infra.storage.duckdb import connect


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
        snapshot = load_snapshot_paths(self.snapshot_dir)
        self.locator_relation = snapshot.locator_relation
        required = snapshot.locator_feature_parts
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(f"feature snapshot is missing {path}")
        self._threads = threads
        self._memory_limit = memory_limit

    def _require_dimension(self, dimension: str) -> None:
        if dimension not in KNOWN_DIMENSIONS:
            raise UnknownDimensionError(f"unknown selection dimension: {dimension!r}")

    def value_counts(self, dimension: str) -> Iterator[dict[str, Any]]:
        """Stream supply counts by value, using accessions for exhibit-like names."""
        self._require_dimension(dimension)
        accession_count = (
            ", COUNT(DISTINCT representative_accession) AS accession_count"
            if dimension == "primary_exhibit_like"
            else ""
        )
        query = f"""
            SELECT {dimension} AS value,
                   COUNT(DISTINCT document_locator_key) AS locator_count
                   {accession_count},
                   COUNT(DISTINCT representative_cik) AS cik_count
            FROM {self.locator_relation}
            GROUP BY value
            ORDER BY locator_count DESC, value
        """

        def rows() -> Iterator[dict[str, Any]]:
            with connect(threads=self._threads, memory_limit=self._memory_limit) as con:
                cursor = con.execute(query)
                while row := cursor.fetchone():
                    value = row[0]
                    if isinstance(value, bool):
                        value = str(value).lower()
                    item = {
                        "value": "none" if value is None else str(value),
                        "locator_count": int(row[1]),
                    }
                    if dimension == "primary_exhibit_like":
                        item["accession_count"] = int(row[2])
                        item["cik_count"] = int(row[3])
                    else:
                        item["cik_count"] = int(row[2])
                    yield item

        return rows()

    def check_floor_feasibility(
        self, floors: dict[str, dict[str, int]]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Whether the corpus can satisfy every declared floor; `deficit` is the actionable
        field, since `feasible: false` alone sends the reader back to the policy.
        """
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for dimension, requirements in floors.items():
            self._require_dimension(dimension)
            conditions: list[str] = []
            params: list[str] = []
            for value in requirements:
                normalized = str(value).strip().lower()
                if normalized == "none":
                    conditions.append(
                        f"{dimension} IS NULL OR lower(trim(CAST({dimension} AS VARCHAR))) = ?"
                    )
                    params.append(normalized)
                else:
                    conditions.append(f"lower(trim(CAST({dimension} AS VARCHAR))) = ?")
                    params.append(normalized)
            accession_count = (
                "COUNT(DISTINCT representative_accession)"
                if dimension == "primary_exhibit_like"
                else "COUNT(DISTINCT document_locator_key)"
            )
            available: dict[str, int] = {}
            if conditions:
                query = f"""
                    SELECT lower(COALESCE(trim(CAST({dimension} AS VARCHAR)), 'none')) AS value,
                           {accession_count} AS available
                    FROM {self.locator_relation}
                    WHERE {" OR ".join(f"({condition})" for condition in conditions)}
                    GROUP BY value
                """
                with connect(
                    threads=self._threads, memory_limit=self._memory_limit
                ) as con:
                    cursor = con.execute(query, params)
                    while row := cursor.fetchone():
                        value = str(row[0]).lower()
                        available[value] = int(row[1])
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
                count_expression = (
                    "COUNT(DISTINCT representative_accession)"
                    if "primary_exhibit_like" in filters
                    else "COUNT(*)"
                )
                count = con.execute(
                    f"SELECT {count_expression} FROM {self.locator_relation} "
                    f"WHERE {where}",
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
    "InventoryStatistics",
    "UnknownDimensionError",
]
