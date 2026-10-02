"""Per-dimension availability statistics for a feature snapshot.

Selection floors are only as good as the evidence behind them. A policy asking
for 40 filers with ``sic_code = '7372'`` is either satisfiable from this corpus
or silently impossible, and the difference is knowable before any selection
runs. This module answers that question, and it is the natural place to look
when a published plan reports an underfilled floor.

Every count runs in DuckDB against the snapshot Parquet. The snapshot is
already the narrowed, feature-resolved projection, so no catalog-level scan is
needed and no dimension value is ever materialized in the Python heap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import (
    KNOWN_DIMENSIONS,
    OCCURRENCE_ONLY_DIMENSIONS,
)
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import sql_literal

LOCATOR_TABLE = "locator_features.parquet"
OCCURRENCE_TABLE = "occurrence_features.parquet"


class UnknownDimensionError(ValueError):
    """A statistic was requested for a dimension the policy vocabulary rejects."""


class OccurrenceOnlyDimensionError(ValueError):
    """A composite stratum was filtered on a dimension with no locator grain."""


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
        self.occurrence_path = self.snapshot_dir / OCCURRENCE_TABLE
        self._threads = threads
        self._memory_limit = memory_limit

    def _require_dimension(self, dimension: str) -> None:
        if dimension not in KNOWN_DIMENSIONS:
            raise UnknownDimensionError(f"unknown selection dimension: {dimension!r}")

    def value_counts(self, dimension: str) -> list[dict[str, Any]]:
        """Return per-value counts of unique locators and distinct CIKs.

        ``locator_count`` is the number of distinct *documents* carrying the
        value, which is what a floor on that dimension is denominated in.
        """
        self._require_dimension(dimension)
        if dimension in OCCURRENCE_ONLY_DIMENSIONS:
            relation = sql_literal(str(self.occurrence_path))
            cik_column = "source_cik"
        else:
            relation = sql_literal(str(self.locator_path))
            cik_column = "representative_cik"
        query = f"""
            SELECT {dimension} AS value,
                   COUNT(DISTINCT document_locator_key) AS locator_count,
                   COUNT(DISTINCT {cik_column}) AS cik_count
            FROM read_parquet({relation})
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
        """Report whether the corpus can satisfy every declared floor.

        The ``deficit`` field is the actionable part: a floor that is impossible
        is a policy bug, and a report that only says ``feasible: false`` sends
        the reader back to the policy to work out by how how much.
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
        """Report whether each composite stratum has enough matching locators.

        Counted on the locator table, because that is the grain a composite
        selects candidates at: the selector draws composites from
        ``locator_features``, so a count taken at any other grain would answer a
        different question than the one selection asks. A composite filtered on an
        occurrence-only dimension is therefore refused rather than answered -- the
        locator table has no such column, and a count that silently returned zero
        would look like an undersupplied stratum rather than an invalid one.
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
                    if dimension in OCCURRENCE_ONLY_DIMENSIONS:
                        raise OccurrenceOnlyDimensionError(
                            f"composite stratum filters on {dimension!r}, which has no "
                            "locator grain; composites select from locator_features"
                        )
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
    "OCCURRENCE_TABLE",
    "InventoryStatistics",
    "OccurrenceOnlyDimensionError",
    "UnknownDimensionError",
]
