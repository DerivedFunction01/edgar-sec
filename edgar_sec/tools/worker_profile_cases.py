from __future__ import annotations

import pathlib
import statistics
from typing import Any

from edgar_sec.tools.worker_profile_inventory import case_file, folder_name


def case_work(cases: dict[str, dict[str, Any]]) -> float:
    return sum(max(0.0, float(case.get("duration") or 0.0)) for case in cases.values())


def case_estimate(
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


def current_cases(
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
        duration = case_estimate(test_file, old_cases)
        current[nodeid] = {
            "file": test_file.as_posix(),
            "folder": folder_name(test_file),
            "fingerprint": fingerprint,
            "duration": duration,
            "estimated": duration is not None,
            "observed_at": None,
        }
    return current
