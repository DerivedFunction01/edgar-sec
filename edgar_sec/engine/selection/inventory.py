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

from edgar_sec.engine.selection.policy import KNOWN_DIMENSIONS
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import sql_literal

LOCATOR_TABLE = "locator_features.parquet"
OCCURRENCE_TABLE = "occurrence_features.parquet"

# Dimensions resolved once per locator. Counting these on the locator table is
# correct because each dimension describes the *document*, not the filing.
LOCATOR_ONLY_DIMENSIONS = frozenset(
    {
        "form",
        "form_family",
        "era",
        "suffix",
        "xbrl_state",
        "size_band",
        "owner_org_presence",
        "foreign_status",
        "foreign_country_code",
        "entity_type",
        "filer_category_primary",
        "lifecycle_class",
        "has_revival_gap",
        "locator_class",
        "stub_suspect",
        "anchor_status",
        "comparison_status",
        "company_name",
        "company_family",
    }
)

# Dimensions only present at occurrence grain. Counting them on the locator
# table would silently return zero rows rather than an error.
OCCURRENCE_ONLY_DIMENSIONS = frozenset({"sic_code", "accession_class"})


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
        """Report whether each composite stratum has enough matching locators."""
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
    "LOCATOR_ONLY_DIMENSIONS",
    "LOCATOR_TABLE",
    "OCCURRENCE_ONLY_DIMENSIONS",
    "OCCURRENCE_TABLE",
    "InventoryStatistics",
    "UnknownDimensionError",
]
