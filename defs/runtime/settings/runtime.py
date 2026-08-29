"""Shared runtime defaults expressed as settings specs.

``defs/runtime/defaults.py`` re-exports these constants as compatibility
aliases; new code resolves through the registry instead of importing names.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..resources import (
    DEFAULT_WORKER_MEMORY_MIB,
    DEFAULT_WORKER_MEMORY_SAFETY,
)
from . import SettingSpec

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PARTITION_COUNT = 1


def _default_threads() -> int:
    from ..resources import default_threads

    return default_threads()


def _default_workers(resolved: dict) -> int:
    from ..resources import auto_worker_count, available_memory_bytes

    return auto_worker_count(
        available_memory_bytes(),
        worker_memory_mib=int(resolved["runtime.worker_memory_mib"]),
        safety_fraction=float(resolved["runtime.worker_memory_safety"]),
    )


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


def _validate_positive_int(value: object) -> None:
    if int(value) < 1:
        raise ValueError("must be >= 1")


SETTING_SPECS = {
    "runtime": {
        "worker_memory_mib": SettingSpec(
            value_type=int,
            default=DEFAULT_WORKER_MEMORY_MIB,
            env=True,
            machine_local=True,
            validate=_validate_positive_int,
            description="peak memory estimate per text-parsing worker (MiB)",
        ),
        "worker_memory_safety": SettingSpec(
            value_type=float,
            default=DEFAULT_WORKER_MEMORY_SAFETY,
            env=True,
            machine_local=True,
            validate=_validate_fraction,
            description="available-memory safety fraction for automatic workers",
        ),
        "workers": SettingSpec(
            value_type=int,
            default=_default_workers,
            env=True,
            cli=True,
            machine_local=True,
            validate=_validate_positive_int,
            description="worker processes; memory-derived when unset",
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
            validate=_validate_positive_int,
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
    "DEFAULT_WORKER_MEMORY_MIB",
    "DEFAULT_WORKER_MEMORY_SAFETY",
    "SETTING_SPECS",
]
