from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
from collections.abc import Iterable
from typing import Any

from edgar_sec.infra.storage.duckdb import connect

SCHEMA_VERSION = 1


def default_store_path(repo_root: pathlib.Path) -> pathlib.Path:
    from edgar_sec.foundation.checks.lineage import default_cache_path

    return default_cache_path(repo_root).parent / "pytest_workers.duckdb"


def _schema(con: Any) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"
    )
    row = con.execute(
        "SELECT value FROM schema_metadata WHERE key = 'version'"
    ).fetchone()
    if row and int(row[0]) != SCHEMA_VERSION:
        raise RuntimeError(f"unsupported pytest profile schema version: {row[0]}")
    con.execute(
        "INSERT OR REPLACE INTO schema_metadata VALUES ('version', ?)",
        [str(SCHEMA_VERSION)],
    )
    con.execute("""CREATE TABLE IF NOT EXISTS profile_metadata (
        scope_key VARCHAR PRIMARY KEY, selectors VARCHAR[], inventory_fingerprint VARCHAR,
        selected_workers INTEGER, recommendation_direct BOOLEAN, base_item_work DOUBLE,
        collect_seconds DOUBLE, updated_at DOUBLE, search_frontier INTEGER[], search_best INTEGER,
        search_last_completed INTEGER
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS case_observations (
        scope_key VARCHAR, nodeid VARCHAR, file VARCHAR, folder VARCHAR, fingerprint VARCHAR,
        duration DOUBLE, call_seconds DOUBLE, setup_seconds DOUBLE, teardown_seconds DOUBLE,
        estimated BOOLEAN, observed_at DOUBLE, PRIMARY KEY (scope_key, nodeid)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS probe_baseline_cases (
        scope_key VARCHAR, nodeid VARCHAR, file VARCHAR,
        PRIMARY KEY (scope_key, nodeid)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS worker_trials (
        scope_key VARCHAR, worker_count INTEGER, wall_seconds DOUBLE, item_work DOUBLE,
        shared_seconds DOUBLE, inventory_fingerprint VARCHAR, status VARCHAR, reason VARCHAR,
        source VARCHAR, repeat BOOLEAN, search_order INTEGER, observed_at DOUBLE
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS machine_calibration (
        machine_key VARCHAR PRIMARY KEY, physical_cores INTEGER, logical_cores INTEGER,
        n_max INTEGER, gamma DOUBLE, c_w DOUBLE, work_total DOUBLE, n_crossover INTEGER,
        smt_beneficial BOOLEAN, hardware_cap INTEGER, recommended_full_suite_workers INTEGER,
        timestamp DOUBLE, raw_probes JSON
    )""")


def open_store(path: pathlib.Path):
    con = connect(database=path)
    _schema(con)
    return con


def _array(values: Iterable[Any]) -> list[Any]:
    return list(values)


def load_machine(path: pathlib.Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    con = open_store(path)
    try:
        row = con.execute(
            "SELECT * FROM machine_calibration ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        columns = [item[0] for item in con.description]
        result = dict(zip(columns, row))
        if time.time() - float(result["timestamp"]) > 30 * 86400:
            return None
        from edgar_sec.tools.fast_pytest_worker_calibrator import (
            detect_hardware_topology,
        )

        if (
            result["physical_cores"],
            result["logical_cores"],
        ) != detect_hardware_topology():
            return None
        result["raw_probes"] = json.loads(result["raw_probes"] or "{}")
        return result
    finally:
        con.close()


def save_machine(path: pathlib.Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_store(path)
    try:
        con.execute("BEGIN")
        con.execute("DELETE FROM machine_calibration")
        con.execute(
            """INSERT INTO machine_calibration VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                "current",
                result["physical_cores"],
                result["logical_cores"],
                result.get("n_max", 0),
                result.get("gamma", 0.0),
                result.get("c_w", 0.0),
                result.get("work_total", 0.0),
                result.get("n_crossover", 0),
                result.get("smt_beneficial", False),
                result.get("hardware_cap", 1),
                result.get("recommended_full_suite_workers", 0),
                result.get("timestamp", time.time()),
                json.dumps(result.get("raw_probes", {})),
            ],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _profile_from_rows(con: Any, metadata: tuple[Any, ...]) -> dict[str, Any]:
    (
        scope,
        selectors,
        fingerprint,
        selected,
        direct,
        work,
        collect,
        updated,
        frontier,
        best,
        last,
    ) = metadata
    profile = {
        "scope_key": scope,
        "selectors": selectors or [],
        "inventory_fingerprint": fingerprint,
        "selected_workers": selected,
        "recommendation_direct": direct,
        "base_item_work": work,
        "collect_seconds": collect,
        "updated_at": updated,
        "cases": {},
        "trials": {},
        "search": {"frontier": frontier or [], "best": best, "last_completed": last},
    }
    case_rows = con.execute(
        "SELECT nodeid,file,folder,fingerprint,duration,call_seconds,setup_seconds,teardown_seconds,estimated,observed_at FROM case_observations WHERE scope_key = ?",
        [scope],
    ).fetchall()
    for row in case_rows:
        (
            nodeid,
            file,
            folder,
            fp,
            duration,
            call,
            setup,
            teardown,
            estimated,
            observed,
        ) = row
        phases = {
            key: value
            for key, value in (("call", call), ("setup", setup), ("teardown", teardown))
            if value is not None
        }
        profile["cases"][nodeid] = {
            "file": file,
            "folder": folder,
            "fingerprint": fp,
            "duration": duration,
            "call_seconds": call,
            "phase_durations": phases,
            "estimated": estimated,
            "observed_at": observed,
        }
    baseline_rows = con.execute(
        "SELECT nodeid,file FROM probe_baseline_cases WHERE scope_key = ?",
        [scope],
    ).fetchall()
    profile["probe_baseline_cases"] = {nodeid: file for nodeid, file in baseline_rows}
    trial_rows = con.execute(
        "SELECT worker_count,wall_seconds,item_work,shared_seconds,inventory_fingerprint,status,reason,source,repeat,search_order,observed_at FROM worker_trials WHERE scope_key = ? ORDER BY observed_at",
        [scope],
    ).fetchall()
    for row in trial_rows:
        (
            worker,
            wall,
            item,
            shared,
            fp,
            status,
            reason,
            source,
            repeat,
            order,
            observed,
        ) = row
        record = {
            "wall_seconds": wall,
            "item_work": item,
            "shared_seconds": shared,
            "inventory_fingerprint": fp,
            "status": status,
            "source": source,
            "repeat": repeat,
            "search_order": order,
            "at": observed,
        }
        if reason:
            record["reason"] = reason
        profile["trials"].setdefault(str(worker), []).append(record)
    return profile


def load_profiles(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    con = open_store(path)
    try:
        rows = con.execute("SELECT * FROM profile_metadata").fetchall()
        return {row[0]: _profile_from_rows(con, row) for row in rows}
    finally:
        con.close()


def write_profile(path: pathlib.Path, key: str, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_store(path)
    try:
        con.execute("BEGIN")
        con.execute("DELETE FROM case_observations WHERE scope_key = ?", [key])
        cases = profile.get("cases", {})
        if cases:
            rows = []
            for nodeid, case in cases.items():
                phases = case.get("phase_durations", {})
                rows.append(
                    (
                        key,
                        nodeid,
                        case.get("file"),
                        case.get("folder"),
                        case.get("fingerprint", ""),
                        case.get("duration"),
                        case.get("call_seconds", phases.get("call")),
                        phases.get("setup"),
                        phases.get("teardown"),
                        bool(case.get("estimated", False)),
                        case.get("observed_at"),
                    )
                )
            import pyarrow as pa

            con.register(
                "profile_case_rows",
                pa.Table.from_pylist(
                    [
                        dict(
                            zip(
                                (
                                    "scope_key",
                                    "nodeid",
                                    "file",
                                    "folder",
                                    "fingerprint",
                                    "duration",
                                    "call_seconds",
                                    "setup_seconds",
                                    "teardown_seconds",
                                    "estimated",
                                    "observed_at",
                                ),
                                row,
                            )
                        )
                        for row in rows
                    ]
                ),
            )
            con.execute("INSERT INTO case_observations SELECT * FROM profile_case_rows")
            con.unregister("profile_case_rows")
        con.execute("DELETE FROM probe_baseline_cases WHERE scope_key = ?", [key])
        baseline_cases = profile.get("probe_baseline_cases", {})
        if baseline_cases:
            import pyarrow as pa

            con.register(
                "profile_baseline_rows",
                pa.Table.from_pylist(
                    [
                        {"scope_key": key, "nodeid": nodeid, "file": file}
                        for nodeid, file in baseline_cases.items()
                    ]
                ),
            )
            con.execute(
                "INSERT INTO probe_baseline_cases SELECT * FROM profile_baseline_rows"
            )
            con.unregister("profile_baseline_rows")
        con.execute("DELETE FROM worker_trials WHERE scope_key = ?", [key])
        trial_rows = []
        for worker, records in profile.get("trials", {}).items():
            for record in records:
                trial_rows.append(
                    (
                        key,
                        int(worker),
                        record.get("wall_seconds"),
                        record.get("item_work"),
                        record.get("shared_seconds"),
                        record.get("inventory_fingerprint"),
                        record.get("status", "ok"),
                        record.get("reason") or record.get("error"),
                        record.get("source"),
                        bool(record.get("repeat", False)),
                        record.get("search_order"),
                        record.get("at", time.time()),
                    )
                )
        if trial_rows:
            import pyarrow as pa

            columns = (
                "scope_key",
                "worker_count",
                "wall_seconds",
                "item_work",
                "shared_seconds",
                "inventory_fingerprint",
                "status",
                "reason",
                "source",
                "repeat",
                "search_order",
                "observed_at",
            )
            con.register(
                "profile_trial_rows",
                pa.Table.from_pylist([dict(zip(columns, row)) for row in trial_rows]),
            )
            con.execute("INSERT INTO worker_trials SELECT * FROM profile_trial_rows")
            con.unregister("profile_trial_rows")
        search = profile.get("search", {})
        con.execute(
            """INSERT OR REPLACE INTO profile_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                key,
                _array(profile.get("selectors", [])),
                profile.get("inventory_fingerprint"),
                profile.get("selected_workers"),
                profile.get("recommendation_direct", True),
                profile.get("base_item_work"),
                profile.get("collect_seconds"),
                profile.get("updated_at", time.time()),
                _array(search.get("frontier", [])),
                search.get("best"),
                search.get("last_completed"),
            ],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def migrate_json(source: pathlib.Path, destination: pathlib.Path) -> None:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 3
        or not isinstance(raw.get("profiles", {}), dict)
    ):
        raise ValueError("invalid source pytest worker cache")
    temp = pathlib.Path(
        tempfile.mkstemp(
            prefix="pytest-workers-", suffix=".duckdb", dir=destination.parent
        )[1]
    )
    temp.unlink()
    try:
        machine = raw.get("machine_model") or {
            key: raw[key]
            for key in (
                "n_max",
                "physical_cores",
                "logical_cores",
                "gamma",
                "c_w",
                "work_total",
                "n_crossover",
                "smt_beneficial",
                "hardware_cap",
                "recommended_full_suite_workers",
                "raw_probes",
            )
            if key in raw
        }
        if machine:
            save_machine(temp, machine)
        for key, profile in raw.get("profiles", {}).items():
            if (
                not isinstance(profile, dict)
                or not isinstance(profile.get("cases", {}), dict)
                or not isinstance(profile.get("trials", {}), dict)
            ):
                raise ValueError(f"invalid profile: {key}")
            write_profile(temp, key, profile)
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()
