"""Catalog planning command."""

from __future__ import annotations

import argparse
import sys

from edgar_sec.engine.selection.policy import SelectionPolicy
from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.filing_catalog.discovery import auto_policy
from edgar_sec.pipelines.filing_catalog.planner import (
    SCOPE_POLICY,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    plan as build_plan,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    plan_policy as build_policy_plan,
)
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

from .common import emit_progress, resolve_artifacts


def _load_policy(args: argparse.Namespace) -> SelectionPolicy:
    """Resolve selection policy for policy scope planning."""
    if args.policy and args.auto_policy:
        raise ValueError("pass either --policy or --auto-policy, not both")
    if args.policy:
        return SelectionPolicy.from_path(args.policy)
    if args.auto_policy:
        return auto_policy(args.catalog, resolve_artifacts(args.artifacts))
    raise ValueError("--scope policy requires --policy PATH or --auto-policy")


def cmd_plan(args: argparse.Namespace) -> int:
    """Publish a deterministic or policy-driven target plan."""
    artifacts = resolve_artifacts(args.artifacts)
    try:
        if args.scope == SCOPE_POLICY:
            if args.cohort:
                raise ValueError("--cohort is only valid for deterministic scope")
            policy = _load_policy(args)
            plan = build_policy_plan(
                args.catalog,
                policy,
                artifacts,
                seed_cohort=args.seed_cohort or None,
                progress=emit_progress,
            )
        else:
            if args.seed_cohort:
                raise ValueError("--seed-cohort is only valid for policy scope")
            plan = build_plan(
                args.catalog,
                artifacts,
                forms=tuple(args.forms) if args.forms else None,
                document_suffixes=(tuple(args.suffixes) if args.suffixes else None),
                dates=args.dates,
                limit=args.limit,
                cohort=args.cohort or None,
                progress=emit_progress,
            )
    except (PlanConflictError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    render_output(
        [
            KeyValueRow("plan_id", plan.get("plan_id", "")),
            KeyValueRow("catalog_id", plan.get("catalog_id", "")),
            KeyValueRow("scope", plan.get("scope", "")),
            KeyValueRow("selected_rows", str(plan.get("selected_rows", 0))),
            KeyValueRow("form_count", str(len(plan.get("forms", ())))),
        ],
        title=f"Plan Published ({plan.get('plan_id', '')[:8]})",
    )
    return 0
