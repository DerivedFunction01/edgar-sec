"""Pipeline review and fixture adapter protocol definition."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import CaseDiff


@runtime_checkable
class ReviewAdapter(Protocol):
    """Pipeline bridge for fixture lifecycle and case comparison."""

    @property
    def dataset_name(self) -> str:
        """Name of the dataset this adapter manages."""
        ...

    def list_fixtures(self, artifacts_root: Path | str) -> list[dict[str, Any]]:
        """Discover and return available fixtures for this dataset."""
        ...

    def create_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit: int | None = None,
        artifacts_root: Path | str = "",
    ) -> int:
        """Capture and persist a new fixture from a catalog plan."""
        ...

    def fill_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit: int | None = None,
        artifacts_root: Path | str = "",
    ) -> int:
        """Extend an existing fixture with additional targets."""
        ...

    def build_review_artifacts(
        self,
        fixture_id: str,
        output_dir: Path,
        limit: int | None = None,
        workers: int | None = None,
        accessions: Sequence[str] | None = None,
        artifacts_root: Path | str = "",
    ) -> int:
        """Render raw previews and structured review artifacts."""
        ...

    def compare_case(
        self,
        case_id: str,
        base_case_dir: Path | None,
        new_case_dir: Path | None,
    ) -> CaseDiff:
        """Compute an objective comparison verdict for one case."""
        ...
