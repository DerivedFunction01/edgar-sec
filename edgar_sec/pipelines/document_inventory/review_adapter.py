"""Inventory review adapter implementing ReviewAdapter for index page reviews."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Any

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.review.adapter import ReviewAdapter
from edgar_sec.infra.storage.review.diff import diff_dataset, diff_json
from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.pipelines.document_inventory.commands.fixture import (
    cmd_fixture_create,
    cmd_fixture_fill,
    cmd_fixture_list,
)
from edgar_sec.pipelines.document_inventory.commands.review import (
    cmd_review_artifacts,
)
from edgar_sec.pipelines.document_inventory.discovery import discover_fixtures
from edgar_sec.pipelines.document_inventory.review_artifacts.paths import (
    ENTRIES_FILE,
    OBSERVATIONS_FILE,
)


def _get_cli_dep(name: str, fallback: Any) -> Any:
    mod = sys.modules.get("edgar_sec.pipelines.document_inventory.cli")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return fallback


class InventoryReviewAdapter(ReviewAdapter):
    """Bridge connecting document inventory to the shared review harness."""

    dataset_name: str = "document_inventory"

    def list_fixtures(self, artifacts_root: Path | str) -> list[dict[str, Any]]:
        root = (
            Path(artifacts_root) if artifacts_root else resolve_paths().artifacts_root
        )
        return discover_fixtures(root)

    def cmd_list_fixtures(self, args: argparse.Namespace) -> int:
        fn = _get_cli_dep("cmd_fixture_list", cmd_fixture_list)
        return int(fn(args))

    def create_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit: int | None = None,
        artifacts_root: Path | str = "",
        *,
        json: bool = False,
    ) -> int:
        args = argparse.Namespace(
            fixture=fixture_id,
            catalog_plan=catalog_plan,
            limit=limit,
            artifacts=str(artifacts_root),
            json=json,
        )
        fn = _get_cli_dep("cmd_fixture_create", cmd_fixture_create)
        return int(fn(args))

    def fill_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit: int | None = None,
        artifacts_root: Path | str = "",
        *,
        json: bool = False,
    ) -> int:
        args = argparse.Namespace(
            fixture=fixture_id,
            catalog_plan=catalog_plan,
            limit=limit,
            artifacts=str(artifacts_root),
            json=json,
        )
        fn = _get_cli_dep("cmd_fixture_fill", cmd_fixture_fill)
        return int(fn(args))

    def build_review_artifacts(
        self,
        fixture_id: str,
        output_dir: Path,
        limit: int | None = None,
        workers: int | None = None,
        accessions: Sequence[str] | None = None,
        artifacts_root: Path | str = "",
    ) -> int:
        args = argparse.Namespace(
            fixture=fixture_id,
            output=str(output_dir),
            limit=limit,
            workers=workers,
            accession=list(accessions) if accessions else None,
            artifacts=str(artifacts_root),
            json=False,
        )
        return cmd_review_artifacts(args)

    def compare_case(
        self,
        case_id: str,
        base_case_dir: Path | None,
        new_case_dir: Path | None,
    ) -> CaseDiff:
        if base_case_dir is None:
            return CaseDiff(case_id, "added", details="case added in new run")
        if new_case_dir is None:
            return CaseDiff(case_id, "removed", details="case removed in new run")

        base_entries = base_case_dir / ENTRIES_FILE
        new_entries = new_case_dir / ENTRIES_FILE
        entries_add, entries_rem, entries_patch = diff_dataset(
            base_entries, new_entries
        )

        base_obs_file = base_case_dir / OBSERVATIONS_FILE
        new_obs_file = new_case_dir / OBSERVATIONS_FILE
        obs_add, obs_rem, obs_patch = 0, 0, ""
        if base_obs_file.is_file() and new_obs_file.is_file():
            base_obs = json.loads(base_obs_file.read_text(encoding="utf-8"))
            new_obs = json.loads(new_obs_file.read_text(encoding="utf-8"))
            obs_add, obs_rem, obs_patch = diff_json(
                base_obs, new_obs, label=OBSERVATIONS_FILE
            )

        total_add = entries_add + obs_add
        total_rem = entries_rem + obs_rem
        if total_add == 0 and total_rem == 0:
            return CaseDiff(case_id, "unchanged")

        detail_parts = []
        if entries_add or entries_rem:
            detail_parts.append(f"{ENTRIES_FILE} (+{entries_add}/-{entries_rem})")
        if obs_add or obs_rem:
            detail_parts.append(f"{OBSERVATIONS_FILE} (+{obs_add}/-{obs_rem})")

        combined_patch = (
            entries_patch + ("\n" if entries_patch and obs_patch else "") + obs_patch
        )
        return CaseDiff(
            case_id=case_id,
            status="changed",
            added_count=total_add,
            removed_count=total_rem,
            details=", ".join(detail_parts),
            patch=combined_patch,
        )
