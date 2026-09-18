from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_http_cache_json_ttl import migrate


def _old_cache(path: Path) -> None:
    conn = sqlite3.connect(path / "responses.sqlite")
    conn.execute(
        """
        CREATE TABLE url_responses (
            url_sha256 TEXT PRIMARY KEY NOT NULL,
            url TEXT NOT NULL,
            payload BLOB NOT NULL,
            payload_sha256 TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            content_kind TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    rows = [
        (
            "json-hash",
            "https://data.sec.gov/submissions/CIK0000000001.json",
            b"json",
            "payload-1",
            4,
            "json",
            "2026-01-01T00:00:00Z",
        ),
        (
            "html-hash",
            "https://www.sec.gov/Archives/edgar/data/1/doc.htm",
            b"html",
            "payload-2",
            4,
            "bytes",
            "2026-01-01T00:00:00Z",
        ),
    ]
    conn.executemany("INSERT INTO url_responses VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_migration_adds_json_expiry_and_preserves_static_forever(
    tmp_path: Path,
) -> None:
    _old_cache(tmp_path)

    result = migrate(tmp_path, ttl_s=90 * 24 * 60 * 60)
    assert result == {"added_column": 1, "json_rows": 1, "static_rows": 1, "rows": 2}

    with sqlite3.connect(tmp_path / "responses.sqlite") as conn:
        rows = dict(conn.execute("SELECT url, expires_at FROM url_responses"))
    assert rows["https://data.sec.gov/submissions/CIK0000000001.json"] == (
        "2026-04-01T00:00:00Z"
    )
    assert rows["https://www.sec.gov/Archives/edgar/data/1/doc.htm"] is None

    second = migrate(tmp_path, ttl_s=90 * 24 * 60 * 60)
    assert second["added_column"] == 0
    assert second["rows"] == 2


def test_migration_rejects_malformed_json_timestamp(tmp_path: Path) -> None:
    _old_cache(tmp_path)
    with sqlite3.connect(tmp_path / "responses.sqlite") as conn:
        conn.execute(
            "UPDATE url_responses SET fetched_at = 'not-a-timestamp' WHERE url LIKE '%.json'"
        )
        conn.commit()

    try:
        migrate(tmp_path)
    except RuntimeError as exc:
        assert "malformed fetched_at" in str(exc)
    else:
        raise AssertionError("migration accepted malformed timestamp")
