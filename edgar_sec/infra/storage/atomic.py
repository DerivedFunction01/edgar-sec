"""Atomic filesystem write operations with fsync and directory sync on POSIX."""

from __future__ import annotations

import json
import os
from typing import Any

from edgar_sec.foundation.serialization import canonical_json


def _fsync_dir(dir_path: str) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(dir_path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> int:
    """Atomically write binary data to path with flush, fsync, and replace."""
    path_str = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path_str))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path_str}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path_str)
        _fsync_dir(directory)
        return len(data)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_text(path: str | os.PathLike[str], text: str) -> int:
    """Atomically write text string to path with UTF-8 encoding."""
    encoded = text.encode("utf-8")
    atomic_write_bytes(path, encoded)
    return len(encoded)


def atomic_write_json(
    path: str | os.PathLike[str],
    obj: Any,
    *,
    canonical: bool = True,
    indent: int | None = None,
) -> int:
    """Atomically serialize object to JSON."""
    if canonical:
        text = canonical_json(obj)
    else:
        text = json.dumps(obj, indent=indent, ensure_ascii=False)
    return atomic_write_text(path, text)


__all__ = ["atomic_write_bytes", "atomic_write_json", "atomic_write_text"]
