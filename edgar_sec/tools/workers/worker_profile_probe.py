from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import time
from typing import Any

from edgar_sec.tools.workers.fast_pytest_worker_calibrator import (
    PROBE_TIMEOUT_SECONDS,
    PYTHON,
)
from edgar_sec.tools.workers.worker_profile_inventory import case_file, folder_name


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
            "edgar_sec.tools.workers.pytest_worker_profiles",
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
