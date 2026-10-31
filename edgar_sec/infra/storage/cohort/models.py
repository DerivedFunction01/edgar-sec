"""Immutable records persisted by the cohort catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CohortRecord:
    cohort_id: str
    name: str | None
    description: str
    manifest_schema_ver: str
    origin_kind: str
    origin_json: str
    roster_id: str
    row_count: int
    distinct_cik_count: int
    dataset_sha256: str
    dataset_path: str
    pinned: bool
    created_at: str
    updated_at: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyIndexRecord:
    universe_cohort_id: str
    family_index_id: str
    rules_fingerprint: str
    dataset_path: str
    dataset_sha256: str
    pinned_at: str


__all__ = ["CohortRecord", "FamilyIndexRecord"]
