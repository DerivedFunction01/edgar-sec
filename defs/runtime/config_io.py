"""Shared atomic configuration and JSON persistence utilities.

Provides crash-safe, validated JSON configuration read and write operations
used by shared runtime config and phase-owned configurations.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def read_json_config(
    path: str | os.PathLike[str],
    *,
    expected_version: int | None = None,
    payload_key: str = "config",
) -> tuple[int, dict]:
    """Read and validate a versioned JSON configuration file.

    Returns ``(version, payload_dict)``. Raises ``FileNotFoundError`` if
    missing, or ``ValueError`` if invalid JSON / wrong version / malformed envelope.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"config not found at {target}")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"config file is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("config file must be a JSON object")
    version = raw.get("version")
    if not isinstance(version, int):
        raise ValueError("config file missing valid integer 'version'")
    if expected_version is not None and version != expected_version:
        raise ValueError(f"unsupported config version: {version}")
    payload = raw.get(payload_key)
    if not isinstance(payload, dict):
        raise ValueError(f"config file must contain a '{payload_key}' object")
    return version, payload


def write_json_config(
    path: str | os.PathLike[str],
    payload: Mapping[str, object],
    *,
    version: int = 1,
    payload_key: str = "config",
) -> str:
    """Atomically write a versioned JSON configuration file.

    Writes to a temporary file in the target directory, flushes/fsyncs, and
    atomically replaces the target.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": version,
        payload_key: dict(payload),
    }
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return str(target)


__all__ = ["read_json_config", "write_json_config"]
