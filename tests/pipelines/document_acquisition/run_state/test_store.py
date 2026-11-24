import sqlite3

import pytest

from edgar_sec.pipelines.document_acquisition.run_state.mutations import (
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import RunStateError


def test_schema_v1_is_refused_and_foreign_keys_are_enabled(tmp_path) -> None:
    old_database = tmp_path / "old.sqlite"
    with sqlite3.connect(old_database) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(RunStateError, match="schema version"):
        initialize_run_state(old_database, [])

    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO attempts (attempt_id, target_id, attempt_number, outcome, "
            "attempt_kind, source, retryable, requested_url, started_at_utc, "
            "finished_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt",
                "missing",
                1,
                "failed",
                "document_body",
                "live_sec",
                0,
                "https://www.sec.gov/request",
                "start",
                "finish",
            ),
        )
    connection.close()
