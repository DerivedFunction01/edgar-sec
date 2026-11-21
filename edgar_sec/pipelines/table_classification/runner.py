"""Run machinery: distribute a plan's work items, then merge.

Work distribution is a spawn process pool, one filing per task; each
process opens its own read-only snapshot source.
"""

from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import derive_resources

from .merger import MergeReport, merge_run
from .paths import ClassificationPaths, resolve_classification_paths
from .planner import read_plan
from .worker import SnapshotFilingSource, WorkResult, classify_work_item

__all__ = ["RunError", "RunReport", "resolve_workers", "run_plan"]

_RECLAIM_INTERVAL = 64


class RunError(RuntimeError):
    """A run failed; its outputs were not merged."""


@dataclass(frozen=True, slots=True)
class RunReport:
    """Result of one completed run."""

    plan_id: str
    work_items: int
    merge: MergeReport


def resolve_workers(workers: int | None = None) -> int:
    """Resolve the worker count, deriving it from the machine when unset."""
    if workers is not None and workers > 0:
        return workers
    return max(1, derive_resources().workers)


def _execute(task: tuple[str, str, str]) -> WorkResult:
    artifacts_root, plan_id, work_item_id = task
    paths = resolve_classification_paths(Path(artifacts_root))
    plan = read_plan(paths, plan_id)
    item = next(
        entry for entry in plan.work_items if entry.work_item_id == work_item_id
    )
    source = SnapshotFilingSource(paths.artifacts_root)
    try:
        return classify_work_item(plan, item, source, paths)
    finally:
        source.close()


def run_plan(
    paths: ClassificationPaths, plan_id: str, workers: int | None = None
) -> RunReport:
    """Execute every work item in one plan, then merge the run."""
    plan = read_plan(paths, plan_id)
    count = resolve_workers(workers)
    results: list[WorkResult] = []
    if count == 1 or len(plan.work_items) <= 1:
        source = SnapshotFilingSource(paths.artifacts_root)
        try:
            for index, item in enumerate(plan.work_items):
                results.append(classify_work_item(plan, item, source, paths))
                if (index + 1) % _RECLAIM_INTERVAL == 0:
                    reclaim()
        finally:
            source.close()
    else:
        tasks = [
            (str(paths.artifacts_root), plan_id, item.work_item_id)
            for item in plan.work_items
        ]
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=count, mp_context=context) as pool:
            futures = [pool.submit(_execute, task) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
    if len(results) != len(plan.work_items):
        raise RunError(
            f"run completed {len(results)} of {len(plan.work_items)} work items"
        )
    merge = merge_run(paths, plan)
    return RunReport(plan_id=plan_id, work_items=len(results), merge=merge)
