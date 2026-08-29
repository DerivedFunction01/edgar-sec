"""Backend-neutral readers and atomic serialization primitives for dataset artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from typing import Any

from .errors import MalformedArtifact, SchemaMismatchError
from .models import DatasetSpec


def canonical_json(value: Any) -> str:
    """Serialize data into deterministic, sorted, whitespace-compact JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fsync_directory(path: str) -> None:
    """Best-effort directory sync after an atomic rename on POSIX."""
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        return


def atomic_write_text(path: str | os.PathLike[str], text: str) -> int:
    """Atomically write text content to path with fsync and directory sync."""
    path_str = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path_str))
    os.makedirs(directory, exist_ok=True)
    tmp_path = path_str + ".tmp"
    encoded_size = len(text.encode("utf-8"))
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path_str)
        _fsync_directory(directory)
        return encoded_size
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_json(
    path: str | os.PathLike[str],
    value: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
) -> int:
    """Atomically serialize and write JSON to path with fsync and directory sync."""
    text = (
        json.dumps(value, indent=indent, sort_keys=sort_keys) + "\n"
        if indent is not None
        else canonical_json(value) + "\n"
    )
    return atomic_write_text(path, text)


def load_json(path: str | os.PathLike[str], *, default: Any = ...) -> Any:
    """Safely load and parse a JSON file.

    If default is provided, returns default on missing or malformed files.
    Otherwise raises FileNotFoundError or ValueError.
    """
    from pathlib import Path

    target = Path(path)
    if not target.exists():
        if default is not ...:
            return default
        raise FileNotFoundError(f"JSON file not found: {target}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        if default is not ...:
            return default
        raise ValueError(f"invalid JSON in {target}: {exc}") from exc


def file_sha256(path: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024) -> str:
    """Stream a file through SHA-256 without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def parquet_column_names(path: str | os.PathLike[str]) -> list[str]:
    """Return column names from the Parquet footer (metadata only)."""
    import pyarrow.parquet as pq

    return list(pq.read_schema(os.fspath(path)).names)


def read_records(
    path: str | os.PathLike[str], storage_format: str, *, spec: DatasetSpec
) -> list[dict]:
    """Read and validate one finalized Parquet or JSONL artifact."""
    path_str = os.fspath(path)
    if storage_format == "parquet":
        try:
            import pyarrow.parquet as pq

            if spec.arrow_schema is None:
                raise MalformedArtifact("Parquet artifact requires an Arrow schema")
            records: Iterable[dict] = pq.read_table(
                path_str, schema=spec.arrow_schema
            ).to_pylist()
        except (OSError, ValueError) as exc:
            raise MalformedArtifact(
                f"cannot read Parquet artifact {path_str}: {exc}"
            ) from exc
        except Exception as exc:  # backend-specific read errors
            raise MalformedArtifact(
                f"cannot read Parquet artifact {path_str}: {exc}"
            ) from exc
    elif storage_format == "jsonl":
        records = []
        number = 0
        try:
            with open(path_str, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("record is not an object")
                    records.append(value)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise MalformedArtifact(
                f"cannot read JSONL artifact {path_str} at line {number}: {exc}"
            ) from exc
    else:
        raise ValueError("storage_format must be 'parquet' or 'jsonl'")

    result = [dict(record) for record in records]
    for record in result:
        try:
            spec.validate_record(record)
        except (KeyError, TypeError, ValueError, SchemaMismatchError) as exc:
            raise MalformedArtifact(
                f"artifact schema validation failed for {path_str}: {exc}"
            ) from exc
    return result


def force_reclaim_memory() -> None:
    """Break reference cycles and return freed arenas to the OS (Linux)."""
    import ctypes
    import gc

    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except (AttributeError, OSError):
        pass


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "canonical_json",
    "file_sha256",
    "force_reclaim_memory",
    "load_json",
    "parquet_column_names",
    "read_records",
]
