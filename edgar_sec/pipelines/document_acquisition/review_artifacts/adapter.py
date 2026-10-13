from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.review.adapter import ReviewArtifactAdapter
from edgar_sec.infra.storage.review.diff import diff_json
from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.pipelines.document_acquisition.commands.review import (
    cmd_review_artifacts,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_cases,
    list_fixtures,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    OBSERVATIONS_FILE,
)


def _get_cli_dep(name: str, fallback: Any) -> Any:
    module = sys.modules.get("edgar_sec.pipelines.document_acquisition.cli")
    if module is not None and hasattr(module, name):
        return getattr(module, name)
    return fallback


class AcquisitionReviewAdapter(ReviewArtifactAdapter):
    dataset_name = "document_acquisition"

    def list_fixtures(self, artifacts_root: Path | str) -> list[dict[str, Any]]:
        root = (
            Path(artifacts_root) if artifacts_root else resolve_paths().artifacts_root
        )
        paths = resolve_acquisition_paths(artifacts_root=root)
        return [
            {
                "fixture_id": fixture_id,
                "case_count": len(list_fixture_cases(paths, fixture_id=fixture_id)),
            }
            for fixture_id in list_fixtures(paths)
        ]

    def build_review_artifacts(
        self,
        fixture_id: str,
        output_dir: Path,
        limit: int | None = None,
        workers: int | None = None,
        accessions: Sequence[str] | None = None,
        artifacts_root: Path | str = "",
        capture_id: str | None = None,
        target_id: str | None = None,
        json_output: bool = False,
        no_progress: bool = False,
    ) -> int:
        args = argparse.Namespace(
            fixture=fixture_id,
            output=str(output_dir),
            limit=limit,
            workers=workers,
            accessions=list(accessions) if accessions else None,
            capture_id=capture_id,
            target_id=target_id,
            artifacts_root=str(artifacts_root),
            json=json_output,
            no_progress=no_progress,
        )
        command = _get_cli_dep("cmd_review_artifacts", cmd_review_artifacts)
        return int(command(args))

    def compare_case(
        self,
        case_id: str,
        base_case_dir: Path | None,
        new_case_dir: Path | None,
    ) -> CaseDiff:
        if base_case_dir is None:
            return CaseDiff(case_id, "added", details="case added in new review")
        if new_case_dir is None:
            return CaseDiff(case_id, "removed", details="case removed in new review")

        base_file = base_case_dir / OBSERVATIONS_FILE
        new_file = new_case_dir / OBSERVATIONS_FILE
        base = (
            json.loads(base_file.read_text(encoding="utf-8"))
            if base_file.is_file()
            else {}
        )
        new = (
            json.loads(new_file.read_text(encoding="utf-8"))
            if new_file.is_file()
            else {}
        )
        added, removed, patch = diff_json(base, new, label=OBSERVATIONS_FILE)
        if added == 0 and removed == 0:
            return CaseDiff(case_id, "unchanged")
        return CaseDiff(
            case_id=case_id,
            status="changed",
            added_count=added,
            removed_count=removed,
            details=OBSERVATIONS_FILE,
            patch=patch,
        )
