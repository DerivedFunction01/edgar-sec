from __future__ import annotations

import statistics
import time
from collections import defaultdict
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


def adaptive_worker_candidates(
    seeds: list[int], ceiling: int, measured: set[int] | None = None
) -> list[int]:
    measured = set(measured or ())
    candidates = [*seeds, 4, 8, 16, 32, ceiling]
    return sorted(
        {worker for worker in candidates if worker == 0 or 2 <= worker <= ceiling}
        - measured
    )


def next_refinement(best: int, measured: set[int], ceiling: int) -> int | None:
    lower = max((worker for worker in measured if worker < best), default=0)
    upper = min((worker for worker in measured if worker > best), default=ceiling + 1)
    gaps = [(best - lower, (best + lower) // 2), (upper - best, (best + upper) // 2)]
    for gap, candidate in sorted(gaps, reverse=True):
        if gap > 2 and 2 <= candidate <= ceiling and candidate not in measured:
            return candidate
    return None


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


def _successful_worker_medians(
    profile: dict[str, Any], inventory_fingerprint: str | None = None
) -> dict[int, float]:
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
    return medians


def choose_fast_workers(
    profile: dict[str, Any] | None,
    selectors: list[str],
    ceiling: int,
    inventory_fingerprint: str | None = None,
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
        if any(
            record.get("status", "ok") in {"ok", "pruned"}
            and (
                inventory_fingerprint is None
                or record.get("inventory_fingerprint") == inventory_fingerprint
            )
            for record in records
        )
    }
    medians = _successful_worker_medians(profile, inventory_fingerprint)
    regression = upward_regression(profile, inventory_fingerprint)
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


def case_inventory_delta(
    baseline: dict[str, str], current: dict[str, str]
) -> dict[str, dict[str, int]]:
    old_items = {(file, nodeid) for nodeid, file in baseline.items()}
    new_items = {(file, nodeid) for nodeid, file in current.items()}
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"baseline": 0, "current": 0, "added": 0, "removed": 0}
    )
    for file, _ in old_items:
        counts[file]["baseline"] += 1
    for file, _ in new_items:
        counts[file]["current"] += 1
    for file, _ in new_items - old_items:
        counts[file]["added"] += 1
    for file, _ in old_items - new_items:
        counts[file]["removed"] += 1
    return dict(sorted(counts.items()))


def material_case_inventory_change(
    delta: dict[str, dict[str, int]],
) -> bool:
    for counts in delta.values():
        churn = counts["added"] + counts["removed"]
        if churn >= 3 or churn / max(1, counts["baseline"]) >= 0.2:
            return True
    return False


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
