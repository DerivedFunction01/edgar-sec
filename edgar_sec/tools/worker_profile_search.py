from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

WORKER_REGRESSION_TOLERANCE = 0.25
ESTIMATED_CASES_PER_TEST_FILE = 16


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
    profile: dict[str, Any], inventory_fingerprint: str | None
) -> tuple[int, int, float, float] | None:
    medians = {}
    for raw_worker, records in profile.get("trials", {}).items():
        values = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
            and (
                inventory_fingerprint is None
                or record.get("inventory_fingerprint") == inventory_fingerprint
            )
        ]
        if values:
            medians[int(raw_worker)] = statistics.median(values)
    for worker in sorted(value for value in medians if value >= 2):
        lower = [value for value in medians if value < worker]
        if not lower:
            continue
        baseline_worker = min(lower, key=lambda value: medians[value])
        baseline_seconds = medians[baseline_worker]
        if medians[worker] > baseline_seconds * (1 + WORKER_REGRESSION_TOLERANCE):
            return worker, baseline_worker, baseline_seconds, medians[worker]
    return None


def selector_size_hint(selectors: list[str]) -> int:
    nodeid_count = 0
    other_count = 0
    files = set()
    for selector in selectors:
        if "::" in selector:
            nodeid_count += 1
            continue
        path = Path(selector)
        if path.is_file() and path.name.startswith("test_"):
            files.add(path)
        elif path.is_dir():
            files.update(path.rglob("test_*.py"))
        else:
            other_count += 1
    return nodeid_count + other_count + len(files) * ESTIMATED_CASES_PER_TEST_FILE


def _successful_worker_medians(profile: dict[str, Any]) -> dict[int, float]:
    medians = {}
    for raw_worker, records in profile.get("trials", {}).items():
        values = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
        ]
        if values:
            medians[int(raw_worker)] = statistics.median(values)
    return medians


def choose_fast_workers(
    profile: dict[str, Any] | None,
    selectors: list[str],
    ceiling: int,
) -> tuple[int, str, str]:
    profile = profile or {}
    if ceiling < 2:
        return 0, "resource_default", "resource ceiling allows serial execution only"

    item_count = selector_size_hint(selectors)
    start = 0 if item_count < 256 else min(4, ceiling)
    tiers = sorted(
        {
            worker
            for worker in (start, 2, 4, 8, 12, 16, 20, 24, 32, ceiling)
            if start <= worker <= ceiling and worker != 1
        }
    )
    attempted = {
        int(worker)
        for worker, records in profile.get("trials", {}).items()
        if any(record.get("status", "ok") in {"ok", "pruned"} for record in records)
    }
    medians = _successful_worker_medians(profile)
    regression = upward_regression(profile, None)
    if regression is not None:
        boundary, baseline, baseline_seconds, candidate_seconds = regression
        tiers = [worker for worker in tiers if worker <= boundary]
        reason = (
            f"stopped above n={boundary}: {candidate_seconds:.3g}s exceeded "
            f"n={baseline} baseline {baseline_seconds:.3g}s by over "
            f"{WORKER_REGRESSION_TOLERANCE:.0%}"
        )
    else:
        reason = f"fast policy; selector size hint={item_count}"
        prior_workers = [worker for worker in attempted if worker >= start]
        if prior_workers:
            highest = max(prior_workers)
            next_higher = min(
                (worker for worker in tiers if worker > highest), default=None
            )
            if next_higher is not None and next_higher - highest > 4:
                midpoint = (highest + next_higher) // 2
                if midpoint <= ceiling:
                    tiers.append(midpoint)
                    tiers.sort()

    next_worker = next((worker for worker in tiers if worker not in attempted), None)
    if next_worker is not None:
        source = "fast_baseline" if not medians else "fast_exploration"
        return next_worker, source, reason
    if medians:
        workers = min(medians, key=medians.get)
        return workers if workers >= 2 else 0, "observed_history", reason
    return start if start >= 2 else 0, "fast_policy", reason


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
