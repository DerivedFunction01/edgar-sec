"""Catalog plan envelope specialization."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.plan.envelope import PlanEnvelope


@dataclass(frozen=True, slots=True)
class CatalogPlanEnvelope(PlanEnvelope):
    """Filing catalog plan specialization."""

    @property
    def catalog_id(self) -> str:
        return str(self.raw.get("catalog_id") or "")

    @property
    def scope(self) -> str:
        return str(self.raw.get("scope") or "unknown")

    @property
    def selected_rows(self) -> int | None:
        val = self.raw.get("selected_rows") or self.raw.get("active_targets_count")
        return int(val) if val is not None else None

    @property
    def unit_count(self) -> int | None:
        return self.selected_rows

    @property
    def unique_locators_count(self) -> int | None:
        val = self.raw.get("unique_locators_count")
        return int(val) if val is not None else None

    @property
    def target_units(self) -> int | None:
        val = self.raw.get("target_units")
        return int(val) if val is not None else None

    @property
    def parent_plan_id(self) -> str | None:
        val = self.raw.get("parent_plan_id")
        return str(val) if val else None

    def describe(self) -> str:
        parts = [f"catalog {self.catalog_id}", self.scope]
        if self.selected_rows is not None:
            parts.append(f"{self.selected_rows:,} rows")
        if self.parent_plan_id:
            parts.append(f"expanded from {self.parent_plan_id}")
        return f"{self.plan_id}  " + "  ".join(parts)
