"""Lazy, root-confined filesystem tree for the artifact explorer."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from edgar_sec.apps.viewer.paths import DATABASE_SUFFIXES
from edgar_sec.apps.viewer.loaders import run_all
from edgar_sec.apps.viewer.model import (
    ArtifactSummary,
    DatasetError,
    artifact_id,
    artifact_path,
    decode_artifact_id,
    file_size,
    mtime_iso,
)

__all__ = [
    "MAX_TEXT_BYTES",
    "ROOT_NODE_ID",
    "TreeEntry",
    "read_text_file",
    "tree_children",
]

ROOT_NODE_ID = "root"
MAX_TEXT_BYTES = 64 * 1024

_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
}


@dataclass(frozen=True)
class TreeEntry:
    id: str
    name: str
    relative_path: str
    node_type: str
    format: str | None
    has_children: bool
    size_bytes: int
    mtime: str | None
    revision: str
    kind: str | None = None
    phase: str | None = None
    run_id: str | None = None
    source_paths: tuple[str, ...] = ()
    table: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise DatasetError("path escapes the artifacts root") from exc


def _text_like(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            sample = stream.read(4096)
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _file_format(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in DATABASE_SUFFIXES:
        return "duckdb" if suffix == ".duckdb" else "sqlite"
    if suffix in _FORMAT_BY_SUFFIX:
        return _FORMAT_BY_SUFFIX[suffix]
    if _text_like(path):
        return "text"
    return None


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _physical_entry(root: Path, path: Path) -> TreeEntry | None:
    if path.is_symlink() or path.name.startswith("."):
        return None
    relative = _relative(root, path)
    if path.is_dir():
        stat = path.stat()
        return TreeEntry(
            id=artifact_id(relative),
            name=path.name,
            relative_path=relative,
            node_type="directory",
            format=None,
            has_children=True,
            size_bytes=0,
            mtime=mtime_iso(path),
            revision=f"dir:{stat.st_mtime_ns}",
        )
    if not path.is_file():
        return None
    fmt = _file_format(path)
    if fmt is None:
        return None
    is_database = fmt in {"sqlite", "duckdb"}
    return TreeEntry(
        id=artifact_id(relative),
        name=path.name,
        relative_path=relative,
        node_type="database" if is_database else "file",
        format=fmt,
        has_children=is_database,
        size_bytes=file_size(path),
        mtime=mtime_iso(path),
        revision=f"{file_size(path)}:{_mtime_ns(path)}",
    )


def _virtual_entry(summary: ArtifactSummary) -> TreeEntry:
    return TreeEntry(
        id=summary.id,
        name=f"{Path(summary.relative_path).name} · {summary.kind}",
        relative_path=summary.relative_path,
        node_type="dataset",
        format=summary.format,
        has_children=False,
        size_bytes=summary.size_bytes,
        mtime=summary.mtime,
        revision=summary.revision,
        kind=summary.kind,
        phase=summary.phase,
        run_id=summary.run_id,
        source_paths=summary.source_paths,
        table=summary.table,
    )


def _database_tables(path: Path, fmt: str) -> list[tuple[str, str]]:
    """Return ``(schema, table)`` pairs through a budgeted in-memory connection."""
    from edgar_sec.infra.storage.duckdb import connect

    quoted_path = "'" + str(path.resolve()).replace("'", "''") + "'"
    conn = connect()
    try:
        if fmt == "sqlite":
            rows = conn.execute(
                f"SELECT name FROM sqlite_scan({quoted_path}, 'sqlite_master') "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [("", str(row[0])) for row in rows]
        conn.execute(f"ATTACH {quoted_path} AS viewer_database (READ_ONLY)")
        rows = conn.execute(
            "SELECT table_schema, table_name "
            "FROM information_schema.tables "
            "WHERE table_catalog='viewer_database' "
            "AND table_type='BASE TABLE' "
            "AND table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name"
        ).fetchall()
        return [(str(schema), str(table)) for schema, table in rows]
    except Exception as exc:
        raise DatasetError(f"cannot list tables in {path.name}: {exc}") from exc
    finally:
        conn.close()


def _database_children(root: Path, database: TreeEntry) -> list[TreeEntry]:
    path = artifact_path(database.id, root)
    result = []
    for schema, table in _database_tables(path, database.format or "sqlite"):
        token = f"{schema}::{table}" if schema else table
        result.append(
            TreeEntry(
                id=artifact_id(database.relative_path, token),
                name=f"{schema}.{table}" if schema else table,
                relative_path=database.relative_path,
                node_type="table",
                format=database.format,
                has_children=False,
                size_bytes=database.size_bytes,
                mtime=database.mtime,
                revision=database.revision,
                table=token,
            )
        )
    return result


def tree_children(root: Path, parent_id: str | None = None) -> list[dict]:
    """List a directory's direct entries or a database's table children."""
    resolved_root = Path(root).resolve()
    logical = run_all(resolved_root, include_sqlite=False)

    if parent_id is not None:
        virtual = next((item for item in logical if item.id == parent_id), None)
        if virtual is not None:
            return []
        _relative_part, table = _split_id(parent_id)
        if table is not None:
            return []
        parent = artifact_path(parent_id, resolved_root)
        if parent.is_file():
            entry = _physical_entry(resolved_root, parent)
            if entry is None or entry.node_type != "database":
                return []
            return [
                child.to_dict() for child in _database_children(resolved_root, entry)
            ]
        if not parent.is_dir():
            raise DatasetError("tree node is not a directory or database")
        parent_relative = _relative(resolved_root, parent)
    else:
        parent = resolved_root
        parent_relative = "."

    entries: list[TreeEntry] = []
    try:
        with os.scandir(parent) as iterator:
            for item in iterator:
                if item.name.startswith(".") or item.is_symlink():
                    continue
                entry = _physical_entry(resolved_root, Path(item.path))
                if entry is not None:
                    entries.append(entry)
    except OSError as exc:
        raise DatasetError(f"cannot list directory: {exc}") from exc

    for summary in logical:
        if Path(summary.relative_path).parent.as_posix() == parent_relative:
            entries.append(_virtual_entry(summary))

    entries.sort(
        key=lambda item: (
            0 if item.node_type == "directory" else 1,
            item.name.casefold(),
            item.node_type,
        )
    )
    return [entry.to_dict() for entry in entries]


def read_text_file(
    root: Path, file_id: str, *, offset: int = 0, limit: int = MAX_TEXT_BYTES
) -> dict:
    """Read one bounded UTF-8 text page from a supported file node."""
    if offset < 0 or not 1 <= limit <= MAX_TEXT_BYTES:
        raise DatasetError("invalid text page bounds")
    path = artifact_path(file_id, Path(root))
    if not path.is_file() or _file_format(path) != "text":
        raise DatasetError("file is not a supported text document")
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(limit + 1)
    except OSError as exc:
        raise DatasetError(f"cannot read text file: {exc}") from exc
    has_more = len(data) > limit
    if has_more:
        data = data[:limit]
    return {
        "relative_path": _relative(Path(root).resolve(), path),
        "text": data.decode("utf-8", errors="replace"),
        "offset": offset,
        "next_offset": offset + len(data) if has_more else None,
        "has_more": has_more,
        "size_bytes": file_size(path),
    }


def _split_id(node_id: str) -> tuple[str, str | None]:
    return decode_artifact_id(node_id)
