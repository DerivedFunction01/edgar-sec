"""Universal root envelope for discovered execution and cohort plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PlanEnvelope(Mapping[str, Any]):
    """Minimal root envelope wrapping a discovered plan manifest.

    Requires only a non-empty plan_id; all raw manifest fields remain accessible.
    """

    plan_id: str
    manifest_path: Path
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.plan_id or not self.plan_id.strip():
            raise ValueError("PlanEnvelope requires a non-empty plan_id")

    @property
    def plan_dir(self) -> Path:
        """Directory holding the plan bundle."""
        return self.manifest_path.parent

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def __iter__(self):
        return iter(self.raw)

    def __len__(self) -> int:
        return len(self.raw)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def unit_count(self) -> int | None:
        """Target units / rows count. Default is None; specialized by pipeline."""
        return None

    def describe(self) -> str:
        """Human-readable descriptor for selection menus. Default shows plan_id."""
        return self.plan_id
