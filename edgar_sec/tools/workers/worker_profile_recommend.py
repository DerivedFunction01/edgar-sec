from __future__ import annotations

import statistics
from typing import Any

from edgar_sec.tools.workers.fast_pytest_worker_calibrator import (
    DEFAULT_GAMMA,
    compute_optimal_workers,
)
from edgar_sec.tools.workers.worker_profile_cases import case_work
from edgar_sec.tools.workers.worker_profile_search import forecast_worker_seconds


def _model_candidate(cache: dict[str, Any], count: int, ceiling: int) -> int:
    model = cache.get("machine_model", cache)
    try:
        candidate = compute_optimal_workers(
            count,
            int(model["n_max"]),
            float(model["work_total"]),
            float(model["c_w"]),
            int(model["n_crossover"]),
            int(model["hardware_cap"]),
            float(model.get("gamma", DEFAULT_GAMMA)),
        )
    except (KeyError, TypeError, ValueError):
        candidate = ceiling
    return min(ceiling, candidate) if candidate >= 2 else 0


def _seed_workers(
    cache: dict[str, Any], count: int, ceiling: int, prior: list[int]
) -> list[int]:
    seeds = [0, 2, _model_candidate(cache, count, ceiling), *prior]
    return sorted({worker for worker in seeds if worker == 0 or 2 <= worker <= ceiling})


def _profile_worker(
    profile: dict[str, Any], context_fingerprint: str | None = None
) -> int:
    ranked = []
    for raw_worker, records in profile.get("trials", {}).items():
        valid = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
            and (
                context_fingerprint is None
                or record.get("context_fingerprint") == context_fingerprint
            )
        ]
        if valid:
            ranked.append((statistics.median(valid), int(raw_worker)))
    if not ranked:
        return 0
    winner = min(ranked)[1]
    serial = min((entry for entry in ranked if entry[1] == 0), default=None)
    parallel = [entry for entry in ranked if entry[1] >= 2]
    if serial and (not parallel or serial[0] <= min(parallel)[0]):
        return 0
    return winner if winner >= 2 else 0


def _recommended_worker(profile: dict[str, Any]) -> int:
    estimate = _adjusted_recommendation(profile, case_work(profile.get("cases", {})))
    return (
        estimate
        if estimate is not None
        else _profile_worker(profile, profile.get("context_fingerprint"))
    )


def _best_wall_seconds(
    profile: dict[str, Any], inventory_fingerprint: str
) -> float | None:
    medians = []
    for records in profile.get("trials", {}).values():
        values = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
            and record.get("inventory_fingerprint") == inventory_fingerprint
        ]
        if values:
            medians.append(statistics.median(values))
    return min(medians) if medians else None


def _adjusted_recommendation(profile: dict[str, Any], work: float) -> int | None:
    if work <= 0:
        return None
    forecasts = forecast_worker_seconds(
        profile, work, profile.get("context_fingerprint")
    )
    trials = {
        str(worker): [{"wall_seconds": seconds}]
        for worker, seconds in forecasts.items()
    }
    return _profile_worker({"trials": trials}) if trials else None
