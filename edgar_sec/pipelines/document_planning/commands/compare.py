"""Run read-only target-plan or profile-rule comparisons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.review.paths import new_review_run_id
from edgar_sec.pipelines.document_planning.comparison import (
    compare_profiles,
    compare_target_plans,
)
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths


def cmd_compare(args: argparse.Namespace) -> int:
    paths = resolve_document_planning_paths(artifacts_root=args.artifacts or None)
    plan_mode = args.base_plan_id is not None or args.new_plan_id is not None
    profile_mode = args.base_profile_id is not None or args.new_profile_id is not None
    if plan_mode == profile_mode:
        print("comparison failed: select exactly one pair of plans or profiles")
        return 2
    if plan_mode and (not args.base_plan_id or not args.new_plan_id):
        print("comparison failed: both plan IDs are required")
        return 2
    if profile_mode and (not args.base_profile_id or not args.new_profile_id):
        print("comparison failed: both profile IDs are required")
        return 2

    try:
        if plan_mode:
            report = compare_target_plans(args.base_plan_id, args.new_plan_id, paths)
            artifact_name = "target-plan-diff.json"
            review_type = "target_plan_comparison"
        else:
            report = compare_profiles(args.base_profile_id, args.new_profile_id, paths)
            artifact_name = "profile-rule-diff.json"
            review_type = "profile_rule_comparison"
        review_id = (
            validate_safe_id(args.output_id, "review_id")
            if args.output_id
            else f"compare-{new_review_run_id()}"
        )
        destination = (
            Path(args.output).expanduser().resolve()
            if args.output
            else paths.review_paths(review_id).root
        )
        if destination.exists():
            if not destination.is_dir() or any(destination.iterdir()):
                raise ValueError(
                    "review output destination must be a new or empty directory"
                )
        else:
            destination.mkdir(parents=True)
        artifact_path = destination / artifact_name
        manifest_path = destination / "manifest.jsonl"
        atomic_write_json(artifact_path, report)
        manifest = {
            "schema_version": 1,
            "review_id": review_id,
            "review_type": review_type,
            "artifact": artifact_name,
            "artifact_sha256": file_sha256(artifact_path),
        }
        atomic_write_text(manifest_path, json.dumps(manifest, sort_keys=True) + "\n")
    except (OSError, ValueError) as error:
        print(f"comparison failed: {error}")
        return 2

    result = {"output": str(destination), "report": report}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"comparison written to {destination}")
    return 0


__all__ = ["cmd_compare"]
