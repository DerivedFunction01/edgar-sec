"""Shared runtime defaults expressed as settings specs.

``defs/runtime/defaults.py`` re-exports these constants as compatibility
aliases; new code resolves through the registry instead of importing names.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import SettingSpec

DEFAULT_WORKERS = 4
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PARTITION_COUNT = 1


def _default_threads() -> int:
    from ..resources import default_threads

    return default_threads()


def _default_memory_limit(resolved: dict) -> str:
    from ..resources import default_memory_limit

    fraction = resolved.get("runtime.memory_fraction")
    if fraction is None:
        return default_memory_limit()
    return default_memory_limit(float(fraction))


def _default_temp_directory() -> str:
    return str(Path(tempfile.gettempdir()) / "edgar-sec-spill")


def _validate_fraction(value: object) -> None:
    if not 0 < float(value) <= 1:
        raise ValueError("must be between 0 and 1")


SETTING_SPECS = {
    "runtime": {
        "workers": SettingSpec(
            value_type=int,
            default=DEFAULT_WORKERS,
            env=True,
            cli=True,
            machine_local=True,
            description="worker processes for phase chunk execution",
        ),
        "chunk_size": SettingSpec(
            value_type=int,
            default=DEFAULT_CHUNK_SIZE,
            env=True,
            config=True,
            cli=True,
            description="source rows per resumable work unit (chunk)",
        ),
        "partition_count": SettingSpec(
            value_type=int,
            default=DEFAULT_PARTITION_COUNT,
            env=True,
            config=True,
            cli=True,
            description="partitions the run is distributed into",
        ),
        "threads": SettingSpec(
            value_type=int,
            default=_default_threads,
            env=True,
            cli=True,
            machine_local=True,
            description="worker threads for engine staging; machine-derived when unset",
        ),
        "memory_fraction": SettingSpec(
            value_type=float,
            default=0.6,
            env=True,
            machine_local=True,
            validate=_validate_fraction,
            description="fraction of physical memory used to derive the memory limit",
        ),
        "memory_limit": SettingSpec(
            value_type=str,
            default=_default_memory_limit,
            env=True,
            cli=True,
            machine_local=True,
            description="explicit memory limit (e.g. 2GB)",
        ),
        "temp_directory": SettingSpec(
            value_type=str,
            default=_default_temp_directory,
            env=True,
            machine_local=True,
            description="runtime scratch/spill directory; machine-derived when unset",
        ),
    },
}

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_PARTITION_COUNT",
    "DEFAULT_WORKERS",
    "SETTING_SPECS",
]
