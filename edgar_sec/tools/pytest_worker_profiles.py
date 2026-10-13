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
from edgar_sec.tools.worker_profile_inventory import (
    case_file,
    folder_name,
    scope_inventory,
    scope_key,
)
from edgar_sec.tools.worker_profile_search import (
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


def _case_work(cases: dict[str, dict[str, Any]]) -> float:
    return sum(max(0.0, float(case.get("duration") or 0.0)) for case in cases.values())


def _case_estimate(
    test_file: pathlib.Path, cases: dict[str, dict[str, Any]]
) -> float | None:
    same_file = [
        float(case["duration"])
        for case in cases.values()
        if case.get("file") == test_file.as_posix() and case.get("duration") is not None
    ]
    if same_file:
        return statistics.median(same_file)
    same_folder = [
        float(case["duration"])
        for case in cases.values()
        if case.get("duration") is not None
        and case.get("folder") == folder_name(test_file)
    ]
    return statistics.median(same_folder) if same_folder else None


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


def adaptive_worker_candidates(
    seeds: list[int], ceiling: int, measured: set[int] | None = None
) -> list[int]:
    measured = set(measured or ())
    candidates = [*seeds, 4, 8, 16, 32, ceiling]
    return sorted(
        {worker for worker in candidates if worker == 0 or 2 <= worker <= ceiling}
        - measured
    )


def _next_refinement(best: int, measured: set[int], ceiling: int) -> int | None:
    lower = max((worker for worker in measured if worker < best), default=0)
    upper = min((worker for worker in measured if worker > best), default=ceiling + 1)
    gaps = [(best - lower, (best + lower) // 2), (upper - best, (best + upper) // 2)]
    for gap, candidate in sorted(gaps, reverse=True):
        if gap > 2 and 2 <= candidate <= ceiling and candidate not in measured:
            return candidate
    return None


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
        if call_seconds is not None and previous_call is not None:
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


def _profile_worker(profile: dict[str, Any]) -> int:
    ranked = []
    for raw_worker, records in profile.get("trials", {}).items():
        valid = [
            float(record["wall_seconds"])
            for record in records
            if record.get("status", "ok") == "ok"
            and record.get("wall_seconds") is not None
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
    estimate = _adjusted_recommendation(profile, _case_work(profile.get("cases", {})))
    return estimate if estimate is not None else _profile_worker(profile)


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
        "trials": {},
        "search": {"frontier": [], "best": None, "last_completed": None},
        "collect_seconds": None,
        "updated_at": time.time(),
        "recommendation_direct": True,
    }


def _current_cases(
    nodeids: list[str],
    files: list[pathlib.Path],
    prior: dict[str, Any],
    fingerprints: dict[str, str],
) -> dict[str, dict[str, Any]]:
    old_cases = prior.get("cases", {})
    current = {}
    for nodeid in nodeids:
        test_file = case_file(nodeid, files)
        fingerprint = fingerprints.get(test_file.as_posix(), "")
        old = old_cases.get(nodeid)
        if old and old.get("fingerprint") == fingerprint:
            current[nodeid] = dict(old)
            continue
        duration = _case_estimate(test_file, old_cases)
        current[nodeid] = {
            "file": test_file.as_posix(),
            "folder": folder_name(test_file),
            "fingerprint": fingerprint,
            "duration": duration,
            "estimated": duration is not None,
            "observed_at": None,
        }
    return current


def _adjusted_recommendation(profile: dict[str, Any], work: float) -> int | None:
    if work <= 0:
        return None
    forecasts: dict[int, list[float]] = {}
    for raw_worker, records in profile.get("trials", {}).items():
        for record in records:
            if (
                record.get("status", "ok") == "ok"
                and record.get("wall_seconds") is not None
            ):
                base_work = float(
                    record.get("item_work") or profile.get("base_item_work") or 0
                )
                if base_work <= 0:
                    continue
                shared = float(record.get("shared_seconds") or 0)
                forecasts.setdefault(int(raw_worker), []).append(
                    shared
                    + max(0.0, float(record["wall_seconds"]) - shared)
                    * work
                    / base_work
                )
    trials = {
        str(worker): [{"wall_seconds": statistics.median(values)}]
        for worker, values in forecasts.items()
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

        return auto_worker_count(available_memory_bytes())
    except Exception:
        return max(1, detect_hardware_topology()[0])


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
    files, inventory_fingerprint, fingerprints = scope_inventory(selectors)
    nodeids, collection_seconds = collect_test_nodeids(selectors)
    cases = _current_cases(nodeids, files, prior or case_seed or {}, fingerprints)
    profile = _new_profile(selectors, key, inventory_fingerprint, cases)
    if prior:
        profile["trials"] = prior.get("trials", {})
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
                item_work = _case_work(profile["cases"])
                record = {
                    "wall_seconds": trial["wall_seconds"],
                    "item_work": item_work,
                    "shared_seconds": max(0.0, trial["wall_seconds"] - item_work),
                    "inventory_fingerprint": inventory_fingerprint,
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
                    "at": time.time(),
                }
            except RuntimeError as exc:
                failure = exc
                record = {
                    "status": "failed",
                    "error": str(exc),
                    "inventory_fingerprint": inventory_fingerprint,
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
    profile["base_item_work"] = _case_work(profile["cases"])
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
    files, fingerprint, fingerprints = scope_inventory(selectors)
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
        cases = _current_cases(nodeids, files, profile, fingerprints)
        estimate = _adjusted_recommendation(profile, _case_work(cases))
        coverage = sum(
            not case.get("estimated", False) for case in cases.values()
        ) / max(1, len(cases))
        if (
            estimate is not None
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
            _, folder_fingerprint, _ = scope_inventory(folder_selectors)
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
) -> None:
    if not profile_output.is_file():
        return
    try:
        report = json.loads(profile_output.read_text(encoding="utf-8"))
        if not report.get("count"):
            return
    except (OSError, json.JSONDecodeError, TypeError):
        return
    cache_path = cache_path or default_cache_path(pathlib.Path.cwd())
    files, fingerprint, fingerprints = scope_inventory(selectors)
    key = scope_key(selectors)
    cache = load_cache(cache_path) or {}
    profile = (load_profiles(cache_path).get(key)) or _new_profile(
        selectors, key, fingerprint, {}
    )
    profile["inventory_fingerprint"] = fingerprint
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
            "item_work": _case_work(profile["cases"]),
            "shared_seconds": max(0.0, elapsed - _case_work(profile["cases"])),
            "inventory_fingerprint": fingerprint,
            "status": "ok",
            "source": "normal",
            "at": time.time(),
        }
    )
    recommendation = _adjusted_recommendation(profile, _case_work(profile["cases"]))
    profile["selected_workers"] = (
        recommendation if recommendation is not None else _profile_worker(profile)
    )
    profile["base_item_work"] = _case_work(profile["cases"])
    profile["recommendation_direct"] = all(
        trial.get("inventory_fingerprint") == fingerprint
        for records in profile["trials"].values()
        for trial in records
        if trial.get("status", "ok") == "ok"
    )
    profile["updated_at"] = time.time()
    _write_profile(cache_path, key, profile)
