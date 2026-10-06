"""Per-run output paths for inert parser-review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.pipelines.document_inventory.paths import (
    REVIEW_CASES_DIR,
    REVIEW_MANIFEST_FILE,
    InventoryPaths,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import IndexResponseKey

SOURCE_PREVIEW_FILE = "source.inert.html"
OBSERVATIONS_FILE = "observations.json"
ENTRIES_FILE = "entries.csv"


@dataclass(frozen=True, slots=True)
class ReviewArtifactPaths:
    root: Path

    @property
    def cases_root(self) -> Path:
        return self.root / REVIEW_CASES_DIR

    @property
    def manifest_path(self) -> Path:
        return self.root / REVIEW_MANIFEST_FILE

    @property
    def review_id(self) -> str:
        return self.root.name

    @classmethod
    def under_inventory_root(
        cls, paths: InventoryPaths, review_id: str
    ) -> ReviewArtifactPaths:
        return cls(paths.review_run_root(review_id))

    def case_root(self, accession: AccessionNumber, key: IndexResponseKey) -> Path:
        key_digest = sha256_text(f"{key.request_url}\n{key.response_sha256}")[:16]
        return self.cases_root / f"{accession}--{key_digest}"

    def case_staging_root(self) -> Path:
        return self.root / ".staging"


__all__ = [
    "ENTRIES_FILE",
    "OBSERVATIONS_FILE",
    "ReviewArtifactPaths",
    "SOURCE_PREVIEW_FILE",
]
