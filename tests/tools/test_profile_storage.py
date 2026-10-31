from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.tools.profile_storage import (
    SCHEMA_VERSION,
    load_profiles,
    open_store,
    write_profile,
)


def test_profile_roundtrip_preserves_context_fingerprint(tmp_path: Path) -> None:
    cache_path = tmp_path / "workers.duckdb"
    write_profile(
        cache_path,
        "suite:tests",
        {
            "selectors": ["tests"],
            "inventory_fingerprint": "inventory",
            "context_fingerprint": "context",
            "updated_at": 1.0,
            "trials": {
                "4": [
                    {
                        "wall_seconds": 5.0,
                        "item_work": 4.0,
                        "shared_seconds": 1.0,
                        "inventory_fingerprint": "inventory",
                        "context_fingerprint": "context",
                        "status": "ok",
                        "at": 1.0,
                    }
                ]
            },
        },
    )

    profile = load_profiles(cache_path)["suite:tests"]

    assert profile["context_fingerprint"] == "context"
    assert profile["trials"]["4"][0]["context_fingerprint"] == "context"


def test_profile_store_discards_incompatible_cache_schema(tmp_path: Path) -> None:
    cache_path = tmp_path / "workers.duckdb"
    con = connect(database=cache_path)
    con.execute(
        "CREATE TABLE schema_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"
    )
    con.execute("INSERT INTO schema_metadata VALUES ('version', '1')")
    con.execute("CREATE TABLE profile_metadata (scope_key VARCHAR)")
    con.execute("INSERT INTO profile_metadata VALUES ('old-profile')")
    con.close()

    con = open_store(cache_path)
    try:
        version = con.execute(
            "SELECT value FROM schema_metadata WHERE key = 'version'"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in con.execute("PRAGMA table_info('worker_trials')").fetchall()
        }
        old_rows = con.execute("SELECT COUNT(*) FROM profile_metadata").fetchone()[0]
    finally:
        con.close()

    assert int(version) == SCHEMA_VERSION
    assert "context_fingerprint" in columns
    assert old_rows == 0
