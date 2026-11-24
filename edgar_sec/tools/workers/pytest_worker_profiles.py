from __future__ import annotations

import json
import logging
import pathlib
import time
from typing import Any

import pytest

from edgar_sec.tools.workers.fast_pytest_worker_calibrator import (
    CACHE_EXPIRY_DAYS,
    collect_test_nodeids,
    default_cache_path,
    load_cache,
)
from edgar_sec.tools.workers.profile_storage import load_profiles
from edgar_sec.tools.workers.worker_profile_calibration import (
    _calibrate_scope,
    _new_profile,
    _write_profile,
)
from edgar_sec.tools.workers.worker_profile_cases import case_work, current_cases
from edgar_sec.tools.workers.worker_profile_inventory import (
    case_file,
    folder_name,
    scope_inventory,
    scope_key,
)
from edgar_sec.tools.workers.worker_profile_probe import _merge_case_timings
from edgar_sec.tools.workers.worker_profile_recommend import (
    _adjusted_recommendation,
    _profile_worker,
)
from edgar_sec.tools.workers.worker_profile_search import (
    case_inventory_delta,
    choose_fast_workers,
    material_case_inventory_change,
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
