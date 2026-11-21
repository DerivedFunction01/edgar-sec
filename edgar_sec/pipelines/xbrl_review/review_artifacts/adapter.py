"""XBRL review adapter implementing the review artifact protocol."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.infra.storage.review.adapter import ReviewArtifactAdapter
from edgar_sec.infra.storage.review.diff import diff_json
from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_seed_cohort_path,
    canonical_vintage_cohort_path,
)
from edgar_sec.pipelines.xbrl_review.discovery import (
    default_sp100_cohort_path,
    discover_cohorts,
)
from edgar_sec.pipelines.xbrl_review.paths import (
    HYPOTHESES_FILE,
    QUARANTINE_FILE,
    SOLVED_NODES_FILE,
)
from edgar_sec.pipelines.xbrl_review.review import execute_review_generation


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return pq.read_table(path).to_pylist()


def _cohort_case_count(path: Any) -> int:
    if not isinstance(path, Path) or not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        filings = raw.get("filings", [])
        return len(filings) if isinstance(filings, list) else 0
    return 0


class XbrlReviewAdapter(ReviewArtifactAdapter):
    """Adapter connecting XBRL semantic engine to shared review harness."""

    dataset_name: str = "xbrl"

    def list_fixtures(self, artifacts_root: Path | str) -> list[dict[str, Any]]:
        """Discover available cohorts as JSON-safe fixture dicts."""
        fixtures: list[dict[str, Any]] = []
        for cohort in discover_cohorts(artifacts_root=artifacts_root):
            entry: dict[str, Any] = {
                key: (str(value) if isinstance(value, Path) else value)
                for key, value in cohort.items()
            }
            entry["fixture_id"] = cohort.get("cohort_id", "")
            entry["case_count"] = _cohort_case_count(cohort.get("path"))
            fixtures.append(entry)
        return fixtures

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
        """Render structured review artifacts for selected cohort filings."""
        try:
            cohort_p = (
                canonical_seed_cohort_path()
                if fixture_id in ("seed", "default", "")
                else (
                    canonical_vintage_cohort_path()
                    if fixture_id == "vintage"
                    else (
                        default_sp100_cohort_path()
                        if fixture_id == "sp100"
                        else Path(fixture_id)
                    )
                )
            )
            raw = json.loads(cohort_p.read_text(encoding="utf-8"))
            filings: list[dict[str, Any]] = (
                raw if isinstance(raw, list) else raw.get("filings", [])
            )
            if accessions:
                acc_set = set(accessions)
                filings = [f for f in filings if f.get("accession") in acc_set]
            if limit is not None:
                filings = filings[:limit]

            execute_review_generation(
                filings,
                run_id=output_dir.name,
                output_root=output_dir.parent,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    def compare_case(
        self,
        case_id: str,
        base_case_dir: Path | None,
        new_case_dir: Path | None,
    ) -> CaseDiff:
        """Compute an objective comparison verdict for one filing case."""
        if base_case_dir is None:
            return CaseDiff(case_id, "added", details="case added in new review run")
        if new_case_dir is None:
            return CaseDiff(
                case_id, "removed", details="case removed in new review run"
            )

        total_added, total_removed = 0, 0
        patches: list[str] = []

        for fname in (SOLVED_NODES_FILE, QUARANTINE_FILE, HYPOTHESES_FILE):
            b_data = _read_records(base_case_dir / fname)
            n_data = _read_records(new_case_dir / fname)
            add, rem, patch = diff_json(b_data, n_data, label=fname)
            total_added += add
            total_removed += rem
            if patch:
                patches.append(patch)

        if total_added == 0 and total_removed == 0:
            return CaseDiff(case_id, "unchanged")

        return CaseDiff(
            case_id=case_id,
            status="changed",
            added_count=total_added,
            removed_count=total_removed,
            details=f"nodes(+{total_added}/-{total_removed})",
            patch="\n".join(patches),
        )


__all__ = ["XbrlReviewAdapter"]
