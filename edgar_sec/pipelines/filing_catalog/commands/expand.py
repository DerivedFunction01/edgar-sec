"""Policy plan expansion command."""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.filing_catalog.expansion import (
    ParentPlanError,
    expand,
)
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

from .common import emit_progress, resolve_artifacts


def cmd_expand(args: argparse.Namespace) -> int:
    """Scale a policy plan while retaining every parent locator."""
    try:
        plan = expand(
            args.parent_plan,
            args.target_units,
            artifacts_root=resolve_artifacts(args.artifacts),
            progress=emit_progress,
        )
    except (
        PlanConflictError,
        ParentPlanError,
        ValueError,
        OSError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    render_output(
        [
            KeyValueRow("plan_id", plan.get("plan_id", "")),
            KeyValueRow("parent_plan_id", plan.get("parent_plan_id", "")),
            KeyValueRow("target_units", str(plan.get("target_units", 0))),
            KeyValueRow("selected_rows", str(plan.get("selected_rows", 0))),
        ],
        title=f"Plan Expanded ({plan.get('plan_id', '')[:8]})",
    )
    return 0
