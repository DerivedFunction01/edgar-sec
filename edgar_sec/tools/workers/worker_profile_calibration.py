from __future__ import annotations

import importlib.metadata
import pathlib
import time
from typing import Any

from edgar_sec.tools.workers.fast_pytest_worker_calibrator import (
    _cache_lock,
    collect_test_nodeids,
    detect_hardware_topology,
)
from edgar_sec.tools.workers.profile_storage import write_profile
from edgar_sec.tools.workers.worker_profile_cases import case_work, current_cases
from edgar_sec.tools.workers.worker_profile_inventory import (
    scope_inventory,
    scope_key,
)
from edgar_sec.tools.workers.worker_profile_probe import (
    _merge_case_timings,
    _run_scope_probe,
)
from edgar_sec.tools.workers.worker_profile_recommend import (
    _best_wall_seconds,
    _model_candidate,
    _recommended_worker,
    _seed_workers,
)
from edgar_sec.tools.workers.worker_profile_search import (
    adaptive_worker_candidates,
    next_refinement as _next_refinement,
    ordered_candidates,
    prune_higher_candidates,
    should_prune_baseline,
    upward_regression,
)


def _write_profile(cache_path: pathlib.Path, key: str, profile: dict[str, Any]) -> None:
    with _cache_lock(cache_path):
        write_profile(cache_path, key, profile)


def _new_profile(
    selectors: list[str], key: str, fingerprint: str, cases: dict[str, Any]
) -> dict[str, Any]:
    return {
        "scope_key": key,
        "selectors": selectors,
        "inventory_fingerprint": fingerprint,
        "cases": cases,
        "probe_baseline_cases": {},
        "trials": {},
        "search": {"frontier": [], "best": None, "last_completed": None},
        "collect_seconds": None,
        "updated_at": time.time(),
        "recommendation_direct": True,
    }


def _resource_ceiling() -> int:
    try:
        importlib.metadata.version("pytest-xdist")
    except importlib.metadata.PackageNotFoundError:
        return 1
    try:
        from edgar_sec.foundation.runtime.resources import (
            auto_worker_count,
            available_memory_bytes,
        )

        logical_cores = detect_hardware_topology()[1]
        return auto_worker_count(available_memory_bytes(), cpu_cores=logical_cores)
    except Exception:
        return max(1, detect_hardware_topology()[1])


def _calibrate_scope(
    selectors: list[str],
    cache: dict[str, Any],
    cache_path: pathlib.Path,
    *,
    prior: dict[str, Any] | None = None,
    extra_seeds: list[int] | None = None,
    case_seed: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    key = scope_key(selectors)
    files, inventory_fingerprint, fingerprints, context_fingerprint = scope_inventory(
        selectors
    )
    nodeids, collection_seconds = collect_test_nodeids(selectors)
    cases = current_cases(nodeids, files, prior or case_seed or {}, fingerprints)
    profile = _new_profile(selectors, key, inventory_fingerprint, cases)
    profile["context_fingerprint"] = context_fingerprint
    if prior:
        profile["trials"] = prior.get("trials", {})
        profile["probe_baseline_cases"] = prior.get("probe_baseline_cases", {})
    profile["collect_seconds"] = collection_seconds
    ceiling = _resource_ceiling()
    model = _model_candidate(cache, len(nodeids), ceiling)
    old_best = prior.get("selected_workers") if prior else None
    seeds = _seed_workers(
        cache,
        len(nodeids),
        ceiling,
        [*(extra_seeds or []), *([int(old_best)] if old_best is not None else [])],
    )
    resolved = {
        int(worker)
        for worker, records in profile["trials"].items()
        if not force
        and any(
            record.get("inventory_fingerprint") == inventory_fingerprint
            and record.get("status") in {"ok", "timeout", "failed", "pruned"}
            for record in records
        )
    }
    measured = {
        int(worker)
        for worker, records in profile["trials"].items()
        if not force
        and any(
            record.get("inventory_fingerprint") == inventory_fingerprint
            and record.get("status", "ok") == "ok"
            for record in records
        )
    }
    candidates = adaptive_worker_candidates(seeds, ceiling, resolved)
    candidates = ordered_candidates(candidates)
    regression = upward_regression(profile, inventory_fingerprint)
    upward_pruned = regression is not None
    if regression is not None:
        candidates = prune_higher_candidates(
            profile, candidates, inventory_fingerprint, regression
        )
    profile["search"]["frontier"] = list(candidates)
    repeated_best = False
    while candidates:
        worker = candidates.pop(0)
        prune, lower_bound = should_prune_baseline(
            worker,
            profile["cases"],
            _best_wall_seconds(profile, inventory_fingerprint),
        )
        if prune:
            print(
                f"==> worker calibration probe n={worker} pruned; "
                f"{len(candidates)} candidate(s) remaining"
            )
            record = {
                "status": "pruned",
                "reason": "optimistic_call_work_exceeds_best",
                "lower_bound_seconds": lower_bound,
                "inventory_fingerprint": inventory_fingerprint,
                "context_fingerprint": context_fingerprint,
                "source": "lower_bound",
                "search_order": sum(map(len, profile["trials"].values())),
                "at": time.time(),
            }
            profile["trials"].setdefault(str(worker), []).append(record)
            resolved.add(worker)
            profile["search"].update(
                last_completed=worker,
                best=_recommended_worker(profile),
                frontier=list(candidates),
            )
            profile["updated_at"] = time.time()
            _write_profile(cache_path, key, profile)
            if not candidates:
                if upward_pruned:
                    break
                if not repeated_best:
                    repeated_best = True
                    best = _recommended_worker(profile)
                    candidates.extend(
                        sorted(measured, key=lambda value: abs(value - best))[:3]
                    )
                    profile["search"]["frontier"] = list(candidates)
                    _write_profile(cache_path, key, profile)
                else:
                    refinement = _next_refinement(
                        _recommended_worker(profile), measured, ceiling
                    )
                    if refinement is not None:
                        candidates.append(refinement)
                        profile["search"]["frontier"] = [refinement]
                        _write_profile(cache_path, key, profile)
            continue
        for _ in range(2 if worker == model else 1):
            print(
                f"==> worker calibration probe n={worker}; "
                f"{len(candidates)} candidate(s) remaining"
            )
            failure = None
            try:
                trial = _run_scope_probe(selectors, worker)
                _merge_case_timings(profile, trial["cases"], files, fingerprints)
                item_work = case_work(profile["cases"])
                record = {
                    "wall_seconds": trial["wall_seconds"],
                    "item_work": item_work,
                    "shared_seconds": max(0.0, trial["wall_seconds"] - item_work),
                    "inventory_fingerprint": inventory_fingerprint,
                    "context_fingerprint": context_fingerprint,
                    "status": "ok",
                    "source": "seed" if worker in seeds else "coarse",
                    "repeat": len(profile["trials"].get(str(worker), [])) > 0,
                    "search_order": sum(map(len, profile["trials"].values())),
                    "at": time.time(),
                }
            except TimeoutError as exc:
                record = {
                    "status": "timeout",
                    "error": str(exc),
                    "inventory_fingerprint": inventory_fingerprint,
                    "context_fingerprint": context_fingerprint,
                    "at": time.time(),
                }
            except RuntimeError as exc:
                failure = exc
                record = {
                    "status": "failed",
                    "error": str(exc),
                    "inventory_fingerprint": inventory_fingerprint,
                    "context_fingerprint": context_fingerprint,
                    "at": time.time(),
                }
            profile["trials"].setdefault(str(worker), []).append(record)
            resolved.add(worker)
            if record["status"] == "ok":
                measured.add(worker)
            profile["search"].update(
                last_completed=worker,
                best=_recommended_worker(profile),
                frontier=list(candidates),
            )
            profile["updated_at"] = time.time()
            _write_profile(cache_path, key, profile)
            print(
                f"==> worker calibration probe n={worker} complete; "
                f"{len(candidates)} candidate(s) remaining"
            )
            if failure is not None:
                raise RuntimeError(f"worker probe failed at n={worker}") from failure
            regression = upward_regression(profile, inventory_fingerprint)
            if regression is not None:
                candidates = prune_higher_candidates(
                    profile, candidates, inventory_fingerprint, regression
                )
                upward_pruned = True
                profile["search"]["frontier"] = list(candidates)
                profile["updated_at"] = time.time()
                _write_profile(cache_path, key, profile)
                break
        if not upward_pruned and worker >= 3:
            next_index = next(
                (
                    index
                    for index, candidate in enumerate(candidates)
                    if candidate > worker
                ),
                None,
            )
            if next_index is not None:
                next_worker = candidates[next_index]
                midpoint = (worker + next_worker) // 2
                if (
                    next_worker - worker > 4
                    and midpoint not in resolved
                    and midpoint not in measured
                    and midpoint not in candidates
                ):
                    candidates.insert(next_index, midpoint)
                    profile["search"]["frontier"] = list(candidates)
                    _write_profile(cache_path, key, profile)
        if not candidates:
            if upward_pruned:
                break
            if not repeated_best:
                repeated_best = True
                best = _recommended_worker(profile)
                candidates.extend(
                    sorted(measured, key=lambda value: abs(value - best))[:3]
                )
                profile["search"]["frontier"] = list(candidates)
                _write_profile(cache_path, key, profile)
                continue
            refinement = _next_refinement(
                _recommended_worker(profile), measured, ceiling
            )
            if refinement is not None:
                candidates.append(refinement)
                profile["search"]["frontier"] = [refinement]
                _write_profile(cache_path, key, profile)
    profile["selected_workers"] = _recommended_worker(profile)
    profile["base_item_work"] = case_work(profile["cases"])
    contributing_trials = [
        record
        for records in profile["trials"].values()
        for record in records
        if record.get("status", "ok") == "ok"
    ]
    profile["recommendation_direct"] = bool(contributing_trials) and all(
        record.get("inventory_fingerprint") == inventory_fingerprint
        for record in contributing_trials
    )
    if any(
        record.get("status", "ok") == "ok"
        and record.get("inventory_fingerprint") == inventory_fingerprint
        for records in profile["trials"].values()
        for record in records
    ):
        profile["probe_baseline_cases"] = {
            nodeid: case_file(nodeid, files).as_posix() for nodeid in nodeids
        }
    profile["updated_at"] = time.time()
    _write_profile(cache_path, key, profile)
    return profile
