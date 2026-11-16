"""Infra review-adapter bridge for the CLI lane's review surface."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.pipelines.table_classification.fixture_store.discovery import (
    discover_fixtures,
)
from edgar_sec.pipelines.table_classification.fixture_store.models import (
    DATASET,
    FixtureOperationError,
)

from .builder import build_review_artifacts, read_case_classifications


class ClassificationReviewAdapter:
    """ReviewAdapter-shaped bridge: fixtures in, review runs out."""

    @property
    def dataset_name(self) -> str:
        """The dataset this adapter manages."""
        return DATASET

    def build_review_artifacts(
        self,
        fixture_id: str,
        output_dir: Path,
        limit: int | None = None,
        workers: int | None = None,
        accessions: Sequence[str] | None = None,
        artifacts_root: Path | str = "",
        json_output: bool = False,
        no_progress: bool = False,
    ) -> int:
        """Render one review run from a fixture's stored products."""
        result = build_review_artifacts(
            artifacts_root,
            fixture_id,
            output_dir,
            accessions=tuple(accessions) if accessions else None,
            limit=limit,
        )
        return result.exit_code

    def compare_case(
        self,
        case_id: str,
        base_case_dir: Path | None,
        new_case_dir: Path | None,
    ) -> CaseDiff:
        """Compare one case's classification rows across two runs."""
        base = read_case_classifications(base_case_dir) if base_case_dir else None
        new = read_case_classifications(new_case_dir) if new_case_dir else None
        if base is None and new is None:
            return CaseDiff(case_id=case_id, status="missing")
        if base is None:
            return CaseDiff(case_id=case_id, status="added", added_count=len(new or ()))
        if new is None:
            return CaseDiff(
                case_id=case_id, status="removed", removed_count=len(base or ())
            )
        base_keys = [(row["table_index"], row["family"], row["tier"]) for row in base]
        new_keys = [(row["table_index"], row["family"], row["tier"]) for row in new]
        if base_keys == new_keys:
            return CaseDiff(case_id=case_id, status="unchanged")
        added = len([key for key in new_keys if key not in base_keys])
        removed = len([key for key in base_keys if key not in new_keys])
        return CaseDiff(
            case_id=case_id, status="changed", added_count=added, removed_count=removed
        )

    def list_fixtures(self, artifacts_root: Path | str) -> list[dict[str, Any]]:
        """Discover product fixtures with their pins and stamps."""
        return [
            {
                "fixture_id": item.fixture_id,
                "plan_id": item.plan_pin.plan_id,
                "case_count": item.case_count,
                "stamps": item.stamps.as_record(),
            }
            for item in discover_fixtures(artifacts_root)
        ]

    def create_fixture(self, *args: object, **kwargs: object) -> int:
        """Refuse: capture needs live products, not a catalog plan."""
        raise FixtureOperationError(
            "classification fixtures capture computed products via "
            "fixture_store.capture_results with a plan pin and stamps"
        )

    def fill_fixture(self, *args: object, **kwargs: object) -> int:
        """Refuse: extension is a further capture_results call."""
        raise FixtureOperationError(
            "extend a classification fixture with a further "
            "fixture_store.capture_results call under the same pin and stamps"
        )
