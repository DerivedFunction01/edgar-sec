"""Immutable records persisted by the cohort catalog."""

from __future__ import annotations

import json
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

    def to_manifest(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "name": self.name,
            "description": self.description,
            "manifest_schema_ver": self.manifest_schema_ver,
            "origin_kind": self.origin_kind,
            "origin": json.loads(self.origin_json),
            "roster_id": self.roster_id,
            "row_count": self.row_count,
            "distinct_cik_count": self.distinct_cik_count,
            "dataset_sha256": self.dataset_sha256,
            "dataset_path": self.dataset_path,
            "pinned": self.pinned,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": list(self.tags),
        }


__all__ = ["CohortRecord"]
