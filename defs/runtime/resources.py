"""Machine-derived resource defaults for disk-backed and concurrent processing.

Settings (``runtime.workers``, ``runtime.threads``, ``runtime.memory_limit``,
``runtime.temp_directory``) are declared in ``defs/runtime/settings/runtime.py``
and resolved through the settings registry; this module keeps the machine probes
those specs reference plus the typed :class:`RuntimeResourceProfile` result.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - exercised only before environment setup
    psutil = None

_MEBIBYTE = 1024 * 1024
DEFAULT_MEMORY_FRACTION = 0.6
MIN_MEMORY_MIB = 256
DEFAULT_WORKER_MEMORY_MIB = 512
DEFAULT_WORKER_MEMORY_SAFETY = 0.9

_CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V2_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_V1_MEMORY_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V1_MEMORY_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
_PROC_MEMINFO = Path("/proc/meminfo")


def _physical_memory_bytes() -> int:
    """Return total physical memory for engine memory-limit sizing."""
    if psutil is not None:
        return int(psutil.virtual_memory().total)
    try:
        for line in _PROC_MEMINFO.read_text(encoding="ascii").splitlines():
            name, value, unit = line.split()
            if name == "MemTotal:":
                return int(value) * (1024 if unit == "kB" else 1)
    except (OSError, ValueError):
        pass
    pages = os.sysconf("SC_PHYS_PAGES")
    page_size = os.sysconf("SC_PAGE_SIZE")
    return int(pages * page_size)


def read_cgroup_v2_available_bytes() -> int | None:
    if not (_CGROUP_V2_MEMORY_MAX.exists() and _CGROUP_V2_MEMORY_CURRENT.exists()):
        return None
    try:
        raw_limit = _CGROUP_V2_MEMORY_MAX.read_text(encoding="ascii").strip()
        if raw_limit == "max":
            return None
        limit = int(raw_limit)
        current = int(_CGROUP_V2_MEMORY_CURRENT.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if limit <= 0 or current < 0:
        return None
    return max(0, limit - current)


def read_cgroup_v1_available_bytes() -> int | None:
    if not (_CGROUP_V1_MEMORY_LIMIT.exists() and _CGROUP_V1_MEMORY_USAGE.exists()):
        return None
    try:
        limit = int(_CGROUP_V1_MEMORY_LIMIT.read_text(encoding="ascii").strip())
        usage = int(_CGROUP_V1_MEMORY_USAGE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if limit <= 0 or usage < 0:
        return None
    return max(0, limit - usage)


def read_proc_mem_available_bytes() -> int | None:
    try:
        for line in _PROC_MEMINFO.read_text(encoding="ascii").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "MemAvailable:":
                return int(parts[1]) * (
                    1024 if len(parts) < 3 or parts[2] == "kB" else 1
                )
    except (OSError, ValueError):
        return None
    return None


def available_memory_bytes() -> int:
    """Return cgroup-aware available memory, never preferring MemTotal."""
    value = read_cgroup_v2_available_bytes()
    if value is not None:
        return value
    value = read_cgroup_v1_available_bytes()
    if value is not None:
        return value
    if psutil is not None:
        return max(0, int(psutil.virtual_memory().available))
    value = read_proc_mem_available_bytes()
    if value is not None:
        return max(0, value)
    pages = os.sysconf("SC_PHYS_PAGES")
    page_size = os.sysconf("SC_PAGE_SIZE")
    return max(0, int(pages * page_size))


def default_cpu_cores() -> int:
    """Observed machine CPU core count."""
    if psutil is not None:
        threads = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    else:
        threads = os.cpu_count()
    return max(1, threads or 1)


def default_threads() -> int:
    """Machine-derived thread count, clamped to at least one."""
    return default_cpu_cores()


def default_memory_limit(fraction: float = DEFAULT_MEMORY_FRACTION) -> str:
    """Machine-derived memory limit from a fraction of physical memory."""
    if not 0 < fraction <= 1:
        raise ValueError("memory fraction must be between 0 and 1")
    memory_mib = max(
        MIN_MEMORY_MIB,
        int(_physical_memory_bytes() * fraction / _MEBIBYTE),
    )
    return f"{memory_mib}MiB"


def usable_memory_bytes(
    available: int,
    *,
    safety_fraction: float = DEFAULT_WORKER_MEMORY_SAFETY,
    reserve_bytes: int = 0,
) -> int:
    if not 0 < safety_fraction <= 1:
        raise ValueError("safety_fraction must be between 0 and 1")
    if reserve_bytes < 0:
        raise ValueError("reserve_bytes must be non-negative")
    return max(0, int(available * safety_fraction) - reserve_bytes)


def auto_worker_count(
    available: int,
    *,
    worker_memory_mib: int = DEFAULT_WORKER_MEMORY_MIB,
    safety_fraction: float = DEFAULT_WORKER_MEMORY_SAFETY,
    reserve_bytes: int = 0,
) -> int:
    if worker_memory_mib < 1:
        raise ValueError("worker_memory_mib must be >= 1")
    budget = usable_memory_bytes(
        available, safety_fraction=safety_fraction, reserve_bytes=reserve_bytes
    )
    return max(1, budget // (worker_memory_mib * _MEBIBYTE))


@dataclass(frozen=True)
class RuntimeResourceProfile:
    """Derived machine resources used by execution engines and stages."""

    cpu_cores: int
    workers: int
    threads: int
    memory_limit: str
    temp_directory: str
    available_memory_bytes: int
    worker_memory_mib: int
    worker_memory_safety: float


def derive_resources(
    *,
    env: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> RuntimeResourceProfile:
    """Derive scalable runtime resources from the settings registry.

    The default assumes a normal host: containerized or shared deployments
    override ``RUNTIME_WORKERS``/``RUNTIME_THREADS``/``RUNTIME_MEMORY_LIMIT``
    through the environment or CLI, not project config. An explicit ``env``
    mapping bypasses process/dotenv resolution for deterministic tests.
    """
    from .settings import resolve_settings

    values = resolve_settings(
        include=["runtime"],
        env=env,
        cli_overrides=cli_overrides,
    )
    available = available_memory_bytes()
    return RuntimeResourceProfile(
        cpu_cores=default_cpu_cores(),
        workers=int(values["runtime.workers"]),
        threads=int(values["runtime.threads"]),
        memory_limit=str(values["runtime.memory_limit"]),
        temp_directory=str(Path(str(values["runtime.temp_directory"])).resolve()),
        available_memory_bytes=available,
        worker_memory_mib=int(values["runtime.worker_memory_mib"]),
        worker_memory_safety=float(values["runtime.worker_memory_safety"]),
    )


__all__ = [
    "DEFAULT_WORKER_MEMORY_MIB",
    "DEFAULT_WORKER_MEMORY_SAFETY",
    "RuntimeResourceProfile",
    "auto_worker_count",
    "available_memory_bytes",
    "default_cpu_cores",
    "default_memory_limit",
    "default_threads",
    "derive_resources",
    "read_cgroup_v1_available_bytes",
    "read_cgroup_v2_available_bytes",
    "read_proc_mem_available_bytes",
    "usable_memory_bytes",
]
