"""Data models for review comparison outcomes and metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaseDiff:
    """Objective comparison outcome for one case across two review runs."""

    case_id: str
    status: str
    added_count: int = 0
    removed_count: int = 0
    details: str = ""
    patch: str = ""


@dataclass(frozen=True, slots=True)
class ComponentCount:
    """Aggregated change metrics for one review artifact type."""

    affected_cases: int
    added_total: int
    removed_total: int


@dataclass(frozen=True, slots=True)
class DiffSummary:
    """Aggregated summary of a two-run review comparison."""

    base_run: str
    new_run: str
    total_cases: int
    unchanged_count: int
    changed_count: int
    added_count: int
    removed_count: int
    component_breakdown: tuple[tuple[str, ComponentCount], ...]
    case_diffs: tuple[CaseDiff, ...]
