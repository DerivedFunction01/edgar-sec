from __future__ import annotations

import statistics
import time
from typing import Any

WORKER_REGRESSION_TOLERANCE = 0.25


def call_work_lower_bound(
    cases: dict[str, dict[str, Any]], workers: int
) -> float | None:
    if not cases or any(case.get("call_seconds") is None for case in cases.values()):
        return None
    work = sum(float(case["call_seconds"]) for case in cases.values())
    return work / max(1, workers)


def ordered_candidates(candidates: list[int]) -> list[int]:
    return sorted(worker for worker in candidates if worker >= 3) + sorted(
        (worker for worker in candidates if worker < 3), reverse=True
    )


def upward_regression(
    profile: dict[str, Any], inventory_fingerprint: str
) -> tuple[int, int, float, float] | None:
    medians = {}
    for raw_worker, records in profile.get("trials", {}).items():
        values = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
            and record.get("inventory_fingerprint") == inventory_fingerprint
        ]
        if values:
            medians[int(raw_worker)] = statistics.median(values)
    for worker in sorted(value for value in medians if value >= 3):
        lower = [value for value in medians if value < worker]
        if not lower:
            continue
        baseline_worker = min(lower, key=lambda value: medians[value])
        baseline_seconds = medians[baseline_worker]
        if medians[worker] > baseline_seconds * (1 + WORKER_REGRESSION_TOLERANCE):
            return worker, baseline_worker, baseline_seconds, medians[worker]
    return None


def prune_higher_candidates(
    profile: dict[str, Any],
    candidates: list[int],
    inventory_fingerprint: str,
    regression: tuple[int, int, float, float],
) -> list[int]:
    boundary, baseline_worker, baseline_seconds, candidate_seconds = regression
    reason = (
        f"higher_worker_regression_outside_tolerance: n={baseline_worker} "
        f"baseline={baseline_seconds:.6g}s candidate={candidate_seconds:.6g}s"
    )
    pruned = [worker for worker in candidates if worker > boundary]
    if pruned:
        records = profile.setdefault("trials", {})
        for worker in pruned:
            records.setdefault(str(worker), []).append(
                {
                    "status": "pruned",
                    "reason": reason,
                    "inventory_fingerprint": inventory_fingerprint,
                    "source": "upward_regression",
                    "at": time.time(),
                }
            )
    return [worker for worker in candidates if worker <= boundary]


def should_prune_baseline(
    workers: int, cases: dict[str, dict[str, Any]], best_seconds: float | None
) -> tuple[bool, float | None]:
    if workers not in {0, 2} or best_seconds is None:
        return False, None
    lower_bound = call_work_lower_bound(cases, workers)
    if lower_bound is None:
        return False, None
    return lower_bound > best_seconds * 1.25, lower_bound
