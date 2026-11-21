"""Exclusive lock-file creation shared by the pipeline run locks."""

from __future__ import annotations

import os
from pathlib import Path

from edgar_sec.infra.storage.atomic import _fsync_dir


def create_lock_file(path: Path, payload: bytes) -> None:
    """Create a lock file exclusively, write its payload, and fsync it home."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_dir(str(path.parent))


__all__ = ["create_lock_file"]
