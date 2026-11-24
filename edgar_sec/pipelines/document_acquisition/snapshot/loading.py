"""Run-state loading and terminality validation for publishing."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .errors import RunNotPublishableError


_TERMINAL_TARGET_OUTCOMES = frozenset(
    {"acquired", "skipped", "not_filed", "required_missing", "failed", "ambiguous"}
)


_FAILED_TARGET_OUTCOMES = frozenset({"failed", "required_missing", "ambiguous"})


_TERMINAL_OPERATION_STATUSES = frozenset(
    {
        "available",
        "succeeded",
        "not_requested",
        "unsupported",
        "blocked",
        "failed",
        "not_selected",
    }
)


def _load_run_db(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    if not db_path.is_file():
        raise RunNotPublishableError("run state database is missing")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        state_queries = {
            "target_state": "SELECT * FROM target_state",
            "attempts": "SELECT * FROM attempts",
            "target_slot_resolutions": "SELECT * FROM target_slot_resolutions",
            "operation_state": "SELECT * FROM operation_state",
            "operation_attempts": "SELECT * FROM operation_attempts",
        }
        data: dict[str, list[dict[str, Any]]] = {}
        for table, query in state_queries.items():
            try:
                cur.execute(query)
                data[table] = [dict(row) for row in cur.fetchall()]
            except sqlite3.OperationalError:
                data[table] = []
        return data
    finally:
        con.close()


def _validate_run_terminality(
    work_targets: list[dict[str, Any]],
    db_data: dict[str, list[dict[str, Any]]],
    allow_errors: bool,
) -> None:
    state_by_target = {row["target_id"]: row for row in db_data.get("target_state", [])}
    for target in work_targets:
        target_id = target["target_id"]
        if not target.get("executable", True):
            continue
        state = state_by_target.get(target_id)
        if state is None:
            raise RunNotPublishableError(f"target {target_id} has no state outcome")
        outcome = state.get("outcome")
        if outcome not in _TERMINAL_TARGET_OUTCOMES:
            raise RunNotPublishableError(f"target {target_id} is incomplete: {outcome}")
        if not allow_errors and outcome in _FAILED_TARGET_OUTCOMES:
            raise RunNotPublishableError(
                f"target {target_id} has error outcome {outcome}; allow_errors required"
            )

    for op in db_data.get("operation_state", []):
        status = op.get("status")
        if status not in _TERMINAL_OPERATION_STATUSES:
            raise RunNotPublishableError(
                f"operation {op.get('operation_id')} is not terminal: {status}"
            )
        if not allow_errors and status == "failed":
            raise RunNotPublishableError(
                f"operation {op.get('operation_id')} failed; allow_errors required"
            )
