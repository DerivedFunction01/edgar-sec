"""One-shot migration for the SEC HTTP response cache freshness column.

This script upgrades an existing ``responses.sqlite`` without fetching any
URLs. It is rollout tooling, not a runtime migration framework.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from defs.runtime.paths import resolve_paths
from defs.sec_http.cache import DEFAULT_JSON_TTL_S
from defs.sql import (
    AddColumn,
    AlterTable,
    ColumnDef,
    ColumnType,
    Compare,
    ComparisonOp,
    QueryCompiler,
    Select,
    SqlDialect,
    Table,
    UnsafeStatement,
    Update,
    col,
    make_sql_executor,
    param,
)


def _expiry(fetched_at: str, ttl_s: int) -> str:
    parsed = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=ttl_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def migrate(
    cache_dir: str | Path, *, ttl_s: int = DEFAULT_JSON_TTL_S
) -> dict[str, int]:
    db_path = Path(cache_dir) / "responses.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if ttl_s < 0:
        raise ValueError("ttl_s must be non-negative")

    compiler = QueryCompiler(dialect=SqlDialect.SQLITE, allow_unsafe=True)
    executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
    try:
        pragma_result = executor.query(
            compiler.compile(UnsafeStatement("PRAGMA table_info(url_responses);"))
        )
        columns = {row["name"] for row in pragma_result}
        if not columns:
            raise RuntimeError("url_responses table is missing")
        added_column = 0
        if "expires_at" not in columns:
            executor.exec(
                compiler.compile(
                    AlterTable(
                        "url_responses",
                        (AddColumn(ColumnDef("expires_at", ColumnType.TEXT)),),
                    )
                )
            )
            added_column = 1

        json_rows = static_rows = malformed_rows = 0
        rows = executor.query(
            compiler.compile(
                Select(
                    source=Table("url_responses"),
                    projection=(col("url_sha256"), col("url"), col("fetched_at")),
                )
            )
        )
        all_updates: list[dict[str, object]] = []
        processed = 0
        for row in rows:
            url_sha256 = row["url_sha256"]
            url = row["url"]
            fetched_at = row["fetched_at"]
            if urlsplit(url).path.lower().endswith(".json"):
                try:
                    expires_at = None if ttl_s == 0 else _expiry(fetched_at, ttl_s)
                except (TypeError, ValueError):
                    malformed_rows += 1
                    continue
                json_rows += 1
            else:
                expires_at = None
                static_rows += 1
            all_updates.append(
                {
                    "url_sha256": url_sha256,
                    "expires_at": expires_at,
                }
            )
            processed += 1

        if malformed_rows:
            raise RuntimeError(f"found {malformed_rows} malformed fetched_at values")
        if all_updates:
            _execute_updates(executor, compiler, all_updates)
        return {
            "added_column": added_column,
            "json_rows": json_rows,
            "static_rows": static_rows,
            "rows": processed,
        }
    finally:
        executor.close()


def _execute_updates(executor, compiler, updates: list[dict[str, object]]) -> None:
    compiled_updates = [
        compiler.compile(
            Update(
                table="url_responses",
                assignments=(("expires_at", param(u["expires_at"])),),
                where=Compare(
                    col("url_sha256"),
                    ComparisonOp.EQ,
                    param(u["url_sha256"]),
                ),
            )
        )
        for u in updates
    ]
    executor.transaction(compiled_updates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--ttl-days", type=int, default=90)
    args = parser.parse_args(argv)
    cache_dir = args.cache_dir or str(resolve_paths().cache_root)
    result = migrate(cache_dir, ttl_s=args.ttl_days * 24 * 60 * 60)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
