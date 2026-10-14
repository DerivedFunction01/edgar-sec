"""XBRL review adapter implementing ReviewArtifactAdapter protocol."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.review.adapter import ReviewArtifactAdapter
from edgar_sec.infra.storage.review.diff import diff_json
from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.pipelines.xbrl_review.paths import resolve_xbrl_review_paths
from edgar_sec.pipelines.xbrl_review.review import execute_review_generation

SOLVED_NODES_FILE = "solved_nodes.json"
QUARANTINE_FILE = "epistemic_quarantine.json"
HYPOTHESES_FILE = "hypotheses.json"


class XbrlReviewAdapter(ReviewArtifactAdapter):
    """Adapter connecting XBRL semantic engine to shared review harness."""

    dataset_name: str = "xbrl"

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
        paths = resolve_xbrl_review_paths(
            artifacts_root=artifacts_root if artifacts_root else None
        )
        cohort_p = (
            paths.default_seed_cohort_path
            if fixture_id in ("seed", "default", "")
            else (
                paths.default_sp100_cohort_path
                if fixture_id == "sp100"
                else Path(fixture_id)
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

        run = execute_review_generation(
            filings,
            run_id=output_dir.name,
            output_root=output_dir.parent,
        )
        return run.total_filings

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
            b_file = base_case_dir / fname
            n_file = new_case_dir / fname
            b_data = (
                json.loads(b_file.read_text(encoding="utf-8"))
                if b_file.is_file()
                else []
            )
            n_data = (
                json.loads(n_file.read_text(encoding="utf-8"))
                if n_file.is_file()
                else []
            )
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
