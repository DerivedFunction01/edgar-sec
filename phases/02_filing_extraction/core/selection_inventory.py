"""Dimension statistics and inventory analysis computed from a feature snapshot.

Provides rarity, feasibility, and distribution insights for target selection
without loading the entire catalog into memory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from defs.runtime.resources import derive_resources
from defs.storage import FinalizedArtifact

LOCATOR_TABLE = "locator_features.parquet"
OCCURRENCE_TABLE = "occurrence_features.parquet"

_LOCATOR_ONLY_DIMENSIONS = {
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
    "locator_class",
    "stub_suspect",
    "anchor_status",
    "comparison_status",
}

_OCCURRENCE_ONLY_DIMENSIONS = {"sic_code", "accession_class"}


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
        res = derive_resources()
        self.threads = threads if threads is not None else res.threads
        self.memory_limit = memory_limit or res.memory_limit

    def _open_locator(self) -> FinalizedArtifact:
        return FinalizedArtifact(
            self.snapshot_dir / LOCATOR_TABLE,
            threads=self.threads,
            memory_limit=self.memory_limit,
        )

    def _open_occurrence(self) -> FinalizedArtifact:
        return FinalizedArtifact(
            self.snapshot_dir / OCCURRENCE_TABLE,
            threads=self.threads,
            memory_limit=self.memory_limit,
        )

    def value_counts(self, dimension: str) -> list[dict[str, Any]]:
        """Return per-value counts of unique locators and eligible CIKs."""
        if dimension in _LOCATOR_ONLY_DIMENSIONS:
            with self._open_locator() as artifact:
                rows = artifact.run(f"""
                    SELECT {dimension} AS value,
                           COUNT(*) AS locator_count,
                           COUNT(DISTINCT representative_cik) AS cik_count
                    FROM {artifact.relation}
                    GROUP BY value ORDER BY locator_count DESC
                """)
        else:
            with self._open_occurrence() as artifact:
                rows = artifact.run(f"""
                    SELECT {dimension} AS value,
                           COUNT(DISTINCT document_locator_key) AS locator_count,
                           COUNT(DISTINCT source_cik) AS cik_count
                    FROM {artifact.relation}
                    GROUP BY value ORDER BY locator_count DESC
                """)
        return [
            {
                "value": "none" if r[0] is None else str(r[0]),
                "locator_count": int(r[1]),
                "cik_count": int(r[2]),
            }
            for r in rows
        ]

    def check_floor_feasibility(
        self, floors: dict[str, dict[str, int]]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Check whether candidate inventory can satisfy each floor."""
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for dim, reqs in floors.items():
            counts_map = {
                row["value"]: row["locator_count"] for row in self.value_counts(dim)
            }
            report[dim] = {}
            for val, required in reqs.items():
                available = counts_map.get(str(val).lower(), 0)
                report[dim][val] = {
                    "required": required,
                    "available": available,
                    "feasible": available >= required,
                    "deficit": max(0, required - available),
                }
        return report

    def check_composite_feasibility(
        self, composites: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Evaluate feasibility of composite strata filters."""
        results = []
        with self._open_locator() as artifact:
            for comp in composites:
                filters = comp.get("filters", {})
                min_req = int(comp.get("min", 1))
                clauses = []
                for k, v in filters.items():
                    val_str = str(v).replace("'", "''")
                    clauses.append(f"{k} = '{val_str}'")
                where_clause = " AND ".join(clauses) if clauses else "1 = 1"
                count = artifact.run(f"""
                    SELECT COUNT(*) FROM {artifact.relation} WHERE {where_clause}
                """)[0][0]
                results.append(
                    {
                        "filters": filters,
                        "required": min_req,
                        "available": int(count),
                        "feasible": int(count) >= min_req,
                    }
                )
        return results


__all__ = ["InventoryStatistics"]
