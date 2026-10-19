from __future__ import annotations

import logging

import importlib.metadata
import json
import pathlib
import statistics
import subprocess
import tempfile
import time
from typing import Any

import pytest

from edgar_sec.tools.fast_pytest_worker_calibrator import (
    CACHE_EXPIRY_DAYS,
    CACHE_VERSION,
    DEFAULT_GAMMA,
    PROBE_TIMEOUT_SECONDS,
    PYTHON,
    _cache_lock,
    _compatible_cache,
    collect_test_nodeids,
    compute_optimal_workers,
    default_cache_path,
    detect_hardware_topology,
    load_cache,
)
from edgar_sec.tools.profile_storage import load_profiles, write_profile
from edgar_sec.tools.worker_profile_cases import case_work, current_cases
from edgar_sec.tools.worker_profile_inventory import (
    case_file,
    folder_name,
    scope_inventory,
    scope_key,
)
from edgar_sec.tools.worker_profile_search import (
    adaptive_worker_candidates,
    case_inventory_delta,
    choose_fast_workers,
    forecast_worker_seconds,
    material_case_inventory_change,
    next_refinement as _next_refinement,
    ordered_candidates,
    prune_higher_candidates,
    should_prune_baseline,
    upward_regression,
)

logger = logging.getLogger(__name__)
_PROFILE_REPORTS: dict[str, dict[str, float]] = {}
logger.info("pytest_worker_profiles plugin loaded")


def pytest_addoption(parser: Any) -> None:
    parser.addoption("--worker-profile-output", default=None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any):
    outcome = yield
    report = outcome.get_result()
    if report.when in {"setup", "call", "teardown"}:
        durations = getattr(item, "_worker_profile_durations", {})
        durations[report.when] = report.duration
        item._worker_profile_durations = durations


def pytest_sessionstart(session: Any) -> None:
    if not hasattr(session.config, "workerinput"):
        _PROFILE_REPORTS.clear()


def pytest_runtest_logreport(report: Any) -> None:
    if report.when in {"setup", "call", "teardown"}:
        _PROFILE_REPORTS.setdefault(report.nodeid, {})[report.when] = report.duration


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    output_path = session.config.getoption("worker_profile_output")
    if not output_path or exitstatus != 0 or hasattr(session.config, "workerinput"):
        return
    items = {item.nodeid: item for item in session.items}
    nodeids = set(items) | set(_PROFILE_REPORTS)
    cases = []
    for nodeid in sorted(nodeids):
        item = items.get(nodeid)
        durations = _PROFILE_REPORTS.get(nodeid) or getattr(
            item, "_worker_profile_durations", {}
        )
        cases.append(
            {
                "nodeid": nodeid,
                "file": str(item.location[0]) if item else nodeid.split("::", 1)[0],
                "duration": sum(durations.values()),
                "phases": durations,
            }
        )
    from edgar_sec.infra.storage.atomic import atomic_write_json

    atomic_write_json(
        output_path,
        {"count": len(cases), "cases": cases},
        canonical=False,
    )


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


def _run_scope_probe(selectors: list[str], workers: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pytest-worker-probe-") as tmpdir:
        output = pathlib.Path(tmpdir) / "profile.json"
        cmd = [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "--no-summary",
            "-p",
            "no:cacheprovider",
            "-p",
            "edgar_sec.tools.pytest_worker_profiles",
            "--worker-profile-output",
            str(output),
        ]
        if workers >= 2:
            cmd.extend(["-n", str(workers)])
        cmd.extend(selectors)
        started = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"worker probe timed out at n={workers}") from exc
        elapsed = time.perf_counter() - started
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError(
                f"worker probe failed at n={workers}: "
                f"{result.stderr[-1000:]} {result.stdout[-1000:]}"
            )
        timing = json.loads(output.read_text(encoding="utf-8"))
    if not timing.get("count"):
        raise RuntimeError(f"worker probe collected no tests: {timing!r}")
    return {"workers": workers, "wall_seconds": elapsed, "cases": timing["cases"]}


def _merge_case_timings(
    profile: dict[str, Any],
    cases: list[dict[str, Any]],
    files: list[pathlib.Path],
    fingerprints: dict[str, str],
) -> None:
    records = profile.setdefault("cases", {})
    for item in cases:
        nodeid = item["nodeid"]
        test_file = case_file(nodeid, files)
        previous = records.get(nodeid, {})
        call_seconds = item.get("phases", {}).get("call")
        previous_call = previous.get("call_seconds")
        if (
            previous.get("fingerprint") == fingerprints.get(test_file.as_posix(), "")
            and call_seconds is not None
            and previous_call is not None
        ):
            call_seconds = min(float(call_seconds), float(previous_call))
        records[nodeid] = {
            "file": test_file.as_posix(),
            "folder": folder_name(test_file),
            "fingerprint": fingerprints.get(test_file.as_posix(), ""),
            "duration": float(item["duration"]),
            "call_seconds": call_seconds,
            "phase_durations": item.get("phases", {}),
            "estimated": False,
            "observed_at": time.time(),
        }


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


def choose_fast_workers_for_scope(
    profile: dict[str, Any] | None,
    selectors: list[str],
    ceiling: int,
    inventory_fingerprint: str,
    context_fingerprint: str,
    files: list[pathlib.Path],
    fingerprints: dict[str, str],
) -> tuple[int, str, str]:
    working = dict(profile or {})
    has_compatible_history = any(
        record.get("context_fingerprint") == context_fingerprint
        for records in working.get("trials", {}).values()
        for record in records
    )
    if (
        working
        and has_compatible_history
        and working.get("inventory_fingerprint") != inventory_fingerprint
    ):
        nodeids, _ = collect_test_nodeids(selectors)
        working["cases"] = current_cases(nodeids, files, working, fingerprints)
    return choose_fast_workers(
        working,
        selectors,
        ceiling,
        inventory_fingerprint=inventory_fingerprint,
        context_fingerprint=context_fingerprint,
    )


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


def select_workers(
    selectors: list[str],
    *,
    cache_path: pathlib.Path | None = None,
    recalculate: bool = False,
) -> int:
    cache_path = cache_path or default_cache_path(pathlib.Path.cwd())
    cache = load_cache(cache_path) or {}
    profiles = cache.get("profiles") or load_profiles(cache_path)
    key = scope_key(selectors)
    files, fingerprint, fingerprints, context_fingerprint = scope_inventory(selectors)
    profile = profiles.get(key)
    now = time.time()
    fresh = bool(
        profile
        and profile.get("selected_workers") is not None
        and now - float(profile.get("updated_at", 0)) <= CACHE_EXPIRY_DAYS * 86400
    )
    if (
        fresh
        and profile.get("inventory_fingerprint") == fingerprint
        and not recalculate
    ):
        return int(profile.get("selected_workers", 0))
    if fresh and profile and not recalculate:
        nodeids, _ = collect_test_nodeids(selectors)
        cases = current_cases(nodeids, files, profile, fingerprints)
        current_inventory = {
            nodeid: case_file(nodeid, files).as_posix() for nodeid in nodeids
        }
        inventory_delta = case_inventory_delta(
            profile.get("probe_baseline_cases", {}), current_inventory
        )
        material_inventory_change = material_case_inventory_change(inventory_delta)
        estimate = _adjusted_recommendation(
            {**profile, "context_fingerprint": context_fingerprint}, case_work(cases)
        )
        coverage = sum(
            not case.get("estimated", False) for case in cases.values()
        ) / max(1, len(cases))
        if (
            estimate is not None
            and not material_inventory_change
            and coverage >= 0.8
            and all(case.get("duration") is not None for case in cases.values())
        ):
            profile = dict(profile)
            profile.update(
                cases=cases,
                inventory_fingerprint=fingerprint,
                selected_workers=estimate,
                recommendation_direct=False,
                updated_at=now,
            )
            _write_profile(cache_path, key, profile)
            return estimate
    if key == "suite:tests":
        folders: dict[str, list[pathlib.Path]] = {}
        for test_file in files:
            folders.setdefault(folder_name(test_file), []).append(test_file)
        folder_workers = []
        for folder, folder_files in sorted(folders.items()):
            folder_selectors = (
                [f"tests/{folder}"]
                if folder != "_root"
                else [path.as_posix() for path in folder_files]
            )
            folder_key = scope_key(folder_selectors)
            folder_profile = profiles.get(folder_key)
            expired = (
                not folder_profile
                or now - float(folder_profile.get("updated_at", 0))
                > CACHE_EXPIRY_DAYS * 86400
            )
            _, folder_fingerprint, _, _ = scope_inventory(folder_selectors)
            if (
                recalculate
                or expired
                or folder_profile.get("inventory_fingerprint") != folder_fingerprint
            ):
                folder_profile = _calibrate_scope(
                    folder_selectors,
                    cache,
                    cache_path,
                    prior=folder_profile,
                    force=recalculate,
                )
                profiles[folder_key] = folder_profile
            folder_workers.append(int(folder_profile.get("selected_workers", 0)))
        profile = _calibrate_scope(
            selectors,
            cache,
            cache_path,
            prior=profile,
            extra_seeds=folder_workers,
            force=recalculate,
        )
        return int(profile["selected_workers"])
    component_workers = []
    if key.startswith(("mixed:", "ids:")):
        grouped: dict[str, list[pathlib.Path]] = {}
        for test_file in files:
            grouped.setdefault(folder_name(test_file), []).append(test_file)
        for folder, folder_files in grouped.items():
            folder_selectors = (
                [f"tests/{folder}"]
                if folder != "_root"
                else [path.as_posix() for path in folder_files]
            )
            component = profiles.get(scope_key(folder_selectors))
            if component and component.get("selected_workers") is not None:
                component_workers.append(int(component["selected_workers"]))
    case_seed = None
    if key.startswith("file:") and files:
        folder = folder_name(files[0])
        folder_profile = profiles.get(scope_key([f"tests/{folder}"]))
        if folder_profile:
            case_seed = folder_profile
            if folder_profile.get("selected_workers") is not None:
                component_workers.append(int(folder_profile["selected_workers"]))
    profile = _calibrate_scope(
        selectors,
        cache,
        cache_path,
        prior=profile,
        extra_seeds=component_workers,
        case_seed=case_seed,
        force=recalculate,
    )
    return int(profile["selected_workers"])


def record_normal_run(
    selectors: list[str],
    workers: int,
    elapsed: float,
    profile_output: pathlib.Path,
    cache_path: pathlib.Path | None = None,
    *,
    source: str = "normal",
    status: str = "ok",
) -> None:
    report = None
    if profile_output.is_file():
        try:
            report = json.loads(profile_output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            report = None
    if status == "ok" and (not report or not report.get("count")):
        return
    cache_path = cache_path or default_cache_path(pathlib.Path.cwd())
    files, fingerprint, fingerprints, context_fingerprint = scope_inventory(selectors)
    key = scope_key(selectors)
    profile = (load_profiles(cache_path).get(key)) or _new_profile(
        selectors, key, fingerprint, {}
    )
    if report or not profile.get("inventory_fingerprint"):
        profile["inventory_fingerprint"] = fingerprint
    profile["context_fingerprint"] = context_fingerprint
    if report:
        active_nodeids = {item["nodeid"] for item in report["cases"]}
        profile["cases"] = {
            nodeid: case
            for nodeid, case in profile.get("cases", {}).items()
            if nodeid in active_nodeids
        }
        _merge_case_timings(profile, report["cases"], files, fingerprints)
    worker = workers if workers >= 2 else 0
    profile.setdefault("trials", {}).setdefault(str(worker), []).append(
        {
            "wall_seconds": elapsed,
            "item_work": case_work(profile["cases"]) if report else None,
            "shared_seconds": (
                max(0.0, elapsed - case_work(profile["cases"])) if report else None
            ),
            "inventory_fingerprint": fingerprint,
            "context_fingerprint": context_fingerprint,
            "status": status,
            "source": source,
            "at": time.time(),
        }
    )
    if status != "ok":
        profile["updated_at"] = time.time()
        _write_profile(cache_path, key, profile)
        return
    recommendation = _adjusted_recommendation(profile, case_work(profile["cases"]))
    profile["selected_workers"] = (
        recommendation
        if recommendation is not None
        else _profile_worker(profile, context_fingerprint)
    )
    profile["base_item_work"] = case_work(profile["cases"])
    profile["recommendation_direct"] = all(
        trial.get("inventory_fingerprint") == fingerprint
        for records in profile["trials"].values()
        for trial in records
        if trial.get("status", "ok") == "ok"
    )
    profile["updated_at"] = time.time()
    _write_profile(cache_path, key, profile)
