"""List profiles and published document-target plans."""

from __future__ import annotations

import argparse
import json

from edgar_sec.foundation.runtime.render import Grid, render_output
from edgar_sec.pipelines.document_planning.discovery import discover_document_plans
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.profiles import discover_profiles


def cmd_status(args: argparse.Namespace) -> int:
    paths = resolve_document_planning_paths(artifacts_root=args.artifacts or None)
    profiles = [
        {
            "profile_id": item.profile_id,
            "valid": item.valid,
            "version": item.profile.version if item.profile else None,
            "digest": item.profile.digest if item.profile else None,
            "error": item.error,
        }
        for item in discover_profiles(paths.profiles_root)
    ]
    plans = [
        {
            "plan_id": item.plan_id,
            "manifest_valid": item.plan is not None,
            "profile_id": item.plan.manifest.get("profile_id") if item.plan else None,
            "target_row_count": (
                item.plan.manifest.get("target_row_count") if item.plan else None
            ),
            "error": item.error,
        }
        for item in discover_document_plans(paths)
    ]
    result = {"profiles": profiles, "plans": plans}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        render_output(
            [
                Grid(
                    headers=("Profile", "Version", "Status"),
                    rows=tuple(
                        (
                            str(profile["profile_id"]),
                            f"v{profile['version'] or '?'}",
                            (
                                "valid"
                                if profile["valid"]
                                else f"invalid: {profile['error']}"
                            ),
                        )
                        for profile in profiles
                    ),
                )
            ],
            title="document-planning profiles",
        )
        render_output(
            [
                Grid(
                    headers=("Plan", "Rows", "Status"),
                    rows=tuple(
                        (
                            str(plan["plan_id"]),
                            str(plan["target_row_count"]),
                            (
                                "manifest-valid"
                                if plan["manifest_valid"]
                                else f"invalid: {plan['error']}"
                            ),
                        )
                        for plan in plans
                    ),
                )
            ],
            title="published target plans",
        )
    return 0


__all__ = ["cmd_status"]
