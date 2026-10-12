"""Read-only SQL console over the current snapshot lineage."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.runtime.paths import validate_path_component
from edgar_sec.foundation.sql.guard import SqlGuardError, validate_read_only
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.infra.storage.dag.resolution import compile_virtual_views
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_identifier,
)

__all__ = [
    "QueryPage",
    "SnapshotQueryError",
    "SnapshotQuerySession",
    "run_snapshot_console",
    "validate_snapshot_query",
]

_EXTERNAL_TABLE_FUNCTIONS = (
    "delta_scan",
    "glob",
    "iceberg_scan",
    "mysql_scan",
    "parquet_scan",
    "postgres_scan",
    "query",
    "query_table",
    "read_blob",
    "read_avro",
    "read_arrow",
    "read_arrow_ipc",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_ndjson_auto",
    "read_orc",
    "read_parquet",
    "read_text",
    "read_xlsx",
    "st_read",
    "sqlite_scan",
)
_EXTERNAL_FUNCTION_RE = re.compile(
    rf"\b(?:{build_alternation(_EXTERNAL_TABLE_FUNCTIONS)})\s*\(",
    re.IGNORECASE,
)
_FROM_JOIN = build_alternation(("FROM", "JOIN"))
_SAFE_TABLE_FUNCTIONS = frozenset(
    {"generate_series", "json_each", "json_tree", "range", "unnest"}
)
_TABLE_FUNCTION_RE = re.compile(
    rf"\b(?:{_FROM_JOIN})\s+(?:LATERAL\s+)?([A-Za-z_][A-Za-z_0-9.]*)\s*\(",
    re.IGNORECASE,
)
_FROM_LITERAL_RE = re.compile(
    rf"\b(?:{_FROM_JOIN})\s+'",
    re.IGNORECASE,
)
_SELECT_START_RE = re.compile(r"^\s*(?:SELECT|WITH)\b", re.IGNORECASE)


class SnapshotQueryError(RuntimeError):
    """Raised when the current snapshot cannot be opened for querying."""


@dataclass(frozen=True, slots=True)
class QueryPage:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    has_more: bool


def _sql_masks(query: str) -> tuple[str, str]:
    code: list[str] = []
    literals: list[str] = []
    index = 0
    while index < len(query):
        if query[index : index + 2] in {"--", "/*"}:
            end = (
                query.find("\n", index)
                if query[index : index + 2] == "--"
                else query.find("*/", index + 2)
            )
            index = (
                len(query)
                if end == -1
                else end + (1 if query[index : index + 2] == "--" else 2)
            )
            code.append(" ")
            literals.append(" ")
            continue
        char = query[index]
        if char in {"'", '"'}:
            quote = char
            start = index
            index += 1
            while index < len(query):
                if query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            code.append(" " * (index - start))
            literals.append("''" if quote == "'" else '""')
            continue
        code.append(char)
        literals.append(char)
        index += 1
    return "".join(code), "".join(literals)


def validate_snapshot_query(query: str) -> str:
    normalized = validate_read_only(query)
    code, literals = _sql_masks(normalized)
    table_functions = {
        match.group(1).casefold() for match in _TABLE_FUNCTION_RE.finditer(code)
    }
    unsafe_table_function = table_functions - _SAFE_TABLE_FUNCTIONS
    if (
        _EXTERNAL_FUNCTION_RE.search(code)
        or _FROM_LITERAL_RE.search(literals)
        or unsafe_table_function
    ):
        raise SqlGuardError(
            "queries may read only snapshot relations and session tables"
        )
    return normalized


class SnapshotQuerySession:
    def __init__(
        self,
        snapshots_root: Path | str,
        specs: Sequence[RelationSpec],
        *,
        page_size: int,
        connection_factory: Callable[[], duckdb.DuckDBPyConnection] = connect,
    ) -> None:
        if not specs:
            raise ValueError("snapshot queries require relation specs")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.snapshots_root = Path(snapshots_root).resolve()
        self.paths = DAGPaths(self.snapshots_root)
        self.specs = tuple(specs)
        self.page_size = page_size
        catalog = DAGCatalog(self.snapshots_root, read_only=True)
        pointer = catalog.read_pointer("main")
        if pointer is None:
            raise SnapshotQueryError("no current snapshot is published")
        self.snapshot_id = str(pointer["snapshot_id"])
        self.lineage = walk_lineage(
            self.snapshots_root, self.snapshot_id, read_only=True
        )
        self.connection = connection_factory()
        try:
            self.relation_names = compile_virtual_views(
                self.connection, self.specs, self.lineage, self.snapshots_root
            )
        except Exception:
            self.connection.close()
            raise
        self._cursor: duckdb.DuckDBPyConnection | None = None
        self._pending_row: tuple[Any, ...] | None = None
        self._columns: tuple[str, ...] = ()
        self._last_select: str | None = None
        self._temporary_tables: set[str] = set()

    @property
    def saved_queries_root(self) -> Path:
        return self.paths.saved_queries_root

    def execute(self, query: str) -> QueryPage:
        self._last_select = None
        self._cursor = None
        self._pending_row = None
        normalized = validate_snapshot_query(query)
        cursor = self.connection.execute(normalized)
        description = cursor.description or ()
        self._cursor = cursor
        self._columns = tuple(str(item[0]) for item in description)
        self._pending_row = None
        self._last_select = normalized if _SELECT_START_RE.match(normalized) else None
        return self._fetch_page()

    def next_page(self) -> QueryPage:
        if self._cursor is None:
            return QueryPage((), (), False)
        return self._fetch_page()

    def preflight(self, query: str) -> QueryPage:
        normalized = validate_snapshot_query(query)
        if not _SELECT_START_RE.match(normalized):
            raise ValueError("preflight accepts SELECT or WITH queries only")
        cursor = self.connection.execute(f"EXPLAIN {normalized}")
        description = cursor.description or ()
        self._cursor = cursor
        self._columns = tuple(str(item[0]) for item in description)
        self._pending_row = None
        return self._fetch_page()

    def save_query(self, name: str, query: str) -> Path:
        safe_name = validate_path_component(name, "saved query name")
        normalized = validate_snapshot_query(query)
        path = self.saved_queries_root / f"{safe_name}.sql"
        if path.is_symlink():
            raise ValueError("saved query path cannot be a symlink")
        atomic_write_text(path, normalized + "\n")
        return path

    def load_query(self, name: str) -> str:
        path = self._query_path(name)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"saved query not found: {name}")
        return path.read_text(encoding="utf-8")

    def list_queries(self) -> tuple[str, ...]:
        if not self.saved_queries_root.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem
                for path in self.saved_queries_root.glob("*.sql")
                if path.is_file() and not path.is_symlink()
            )
        )

    def delete_query(self, name: str) -> bool:
        path = self._query_path(name)
        if path.is_symlink():
            raise ValueError("saved query path cannot be a symlink")
        if not path.is_file():
            return False
        path.unlink()
        return True

    def materialize(self, name: str) -> str:
        if self._last_select is None:
            raise ValueError("run a SELECT or WITH query before materializing")
        safe_name = validate_path_component(name, "temporary table name")
        table = f"console_{safe_name}"
        self.connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {sql_identifier(table)} AS {self._last_select}"
        )
        self._temporary_tables.add(table)
        return table

    def export_parquet(self, destination: Path | str) -> int:
        if self._last_select is None:
            raise ValueError("run a SELECT or WITH query before exporting")
        path = Path(destination).expanduser().resolve()
        if path.suffix.lower() != ".parquet":
            raise ValueError("snapshot console exports must use a .parquet destination")
        try:
            path.relative_to(self.snapshots_root)
        except ValueError:
            pass
        else:
            raise ValueError("exports cannot be written inside the snapshot repository")
        return copy_query_to_parquet(self.connection, self._last_select, path)

    def close(self) -> None:
        self.connection.close()
        self._cursor = None

    def _query_path(self, name: str) -> Path:
        safe_name = validate_path_component(name, "saved query name")
        return self.saved_queries_root / f"{safe_name}.sql"

    def _fetch_page(self) -> QueryPage:
        if self._cursor is None:
            return QueryPage((), (), False)
        rows: list[tuple[Any, ...]] = []
        if self._pending_row is not None:
            rows.append(self._pending_row)
            self._pending_row = None
        rows.extend(self._cursor.fetchmany(self.page_size + 1 - len(rows)))
        has_more = len(rows) > self.page_size
        if has_more:
            self._pending_row = rows.pop()
        return QueryPage(self._columns, tuple(rows), has_more)

    def __enter__(self) -> SnapshotQuerySession:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _format_value(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 240 else text[:237] + "..."


def _show_page(page: QueryPage, output_fn: Callable[[str], Any]) -> None:
    remaining = 12_000
    if page.columns:
        header = " | ".join(page.columns)
        output_fn(header[:remaining])
        remaining -= len(header)
        if remaining <= 0 and page.rows:
            output_fn("Preview output truncated")
            return
    for row in page.rows:
        rendered = " | ".join(_format_value(value) for value in row)
        if len(rendered) > remaining:
            output_fn(rendered[:remaining])
            output_fn("Preview output truncated")
            break
        output_fn(rendered)
        remaining -= len(rendered)
    output_fn(f"{len(page.rows)} row(s){' (more available)' if page.has_more else ''}")


def _show_help(output_fn: Callable[[str], Any]) -> None:
    output_fn("SQL: enter one SELECT/WITH/DESCRIBE/SHOW/EXPLAIN query per line")
    output_fn(":tables | :schema NAME | :save NAME | :run NAME | :preflight NAME")
    output_fn(":queries | :delete NAME | :more | :materialize NAME")
    output_fn(":export FILE.parquet | :quit")


def _run_command(
    session: SnapshotQuerySession,
    command: str,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], Any],
) -> bool:
    try:
        parts = shlex.split(command[1:])
    except ValueError as exc:
        output_fn(f"Command error: {exc}")
        return True
    if not parts:
        return True
    action, *args = parts
    try:
        if action in {"quit", "q"}:
            return False
        if action == "help":
            _show_help(output_fn)
        elif action == "tables":
            names = [f"active_{name}" for name in session.relation_names]
            names.extend(sorted(session._temporary_tables))
            output_fn("\n".join(names) if names else "No relations")
        elif action == "schema" and len(args) == 1:
            table = args[0]
            allowed = {f"active_{name}" for name in session.relation_names}
            allowed.update(session._temporary_tables)
            if table not in allowed:
                raise ValueError(f"unknown relation: {table}")
            _show_page(session.execute(f"DESCRIBE {sql_identifier(table)}"), output_fn)
        elif action == "save" and len(args) == 1:
            lines = []
            while True:
                line = input_fn("sql> ")
                if not line.strip():
                    break
                lines.append(line)
            path = session.save_query(args[0], "\n".join(lines))
            output_fn(f"Saved {path.name}")
        elif action == "run" and len(args) == 1:
            _show_page(session.execute(session.load_query(args[0])), output_fn)
        elif action == "preflight" and len(args) == 1:
            _show_page(session.preflight(session.load_query(args[0])), output_fn)
        elif action == "queries":
            names = session.list_queries()
            output_fn("\n".join(names) if names else "No saved queries")
        elif action == "delete" and len(args) == 1:
            output_fn(
                "Deleted" if session.delete_query(args[0]) else "Saved query not found"
            )
        elif action == "more" and not args:
            _show_page(session.next_page(), output_fn)
        elif action == "materialize" and len(args) == 1:
            output_fn(f"Created temporary table {session.materialize(args[0])}")
        elif action == "export" and len(args) == 1:
            count = session.export_parquet(args[0])
            output_fn(f"Exported {count} row(s) to {Path(args[0]).expanduser()}")
        else:
            output_fn("Unknown command or arguments; use :help")
    except Exception as exc:
        output_fn(f"Console error: {exc}")
    return True


def run_snapshot_console(
    snapshots_root: Path | str,
    specs: Sequence[RelationSpec],
    *,
    page_size: int,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], Any] = print,
) -> None:
    prompt = input if input_fn is None else input_fn
    with SnapshotQuerySession(snapshots_root, specs, page_size=page_size) as session:
        output_fn(f"Current snapshot: {session.snapshot_id}")
        output_fn("Read-only snapshot SQL console; use :help for commands")
        while True:
            try:
                line = prompt("sql> ").strip()
            except (EOFError, KeyboardInterrupt):
                output_fn("")
                break
            if not line:
                continue
            if line.startswith(":"):
                if not _run_command(session, line, prompt, output_fn):
                    break
                continue
            try:
                _show_page(session.execute(line), output_fn)
            except Exception as exc:
                output_fn(f"Query error: {exc}")
