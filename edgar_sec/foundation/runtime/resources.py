"""Machine-derived resource defaults for disk-backed and concurrent processing.

Available memory is probed cgroups v2, then cgroups v1, then psutil, then
``/proc/meminfo`` MemAvailable, so a container limit is never mistaken for host memory.
Limits and worker counts are always derived here, never from a raw CPU count.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
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
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (ValueError, OSError, AttributeError):
        return 8 * 1024 * _MEBIBYTE


def read_cgroup_v2_available_bytes() -> int | None:
    """Read available memory from cgroup v2 controller if active."""
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
    """Read available memory from cgroup v1 controller if active."""
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
    """Read MemAvailable from /proc/meminfo."""
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
    """Return cgroup-aware available memory, never preferring MemTotal over real limits."""
    v2 = read_cgroup_v2_available_bytes()
    if v2 is not None:
        return v2
    v1 = read_cgroup_v1_available_bytes()
    if v1 is not None:
        return v1
    if psutil is not None:
        try:
            return max(0, int(psutil.virtual_memory().available))
        except (AttributeError, OSError, TypeError):
            pass
    proc = read_proc_mem_available_bytes()
    if proc is not None:
        return max(0, proc)
    return max(0, _physical_memory_bytes())


def default_cpu_cores() -> int:
    if psutil is not None:
        threads = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    else:
        threads = os.cpu_count()
    return max(1, threads or 1)


def default_threads() -> int:
    """Machine-derived thread count, clamped to at least one."""
    return default_cpu_cores()


def default_memory_limit(fraction: float = DEFAULT_MEMORY_FRACTION) -> str:
    """Machine-derived memory limit from a fraction of physical memory (e.g. '4096MiB')."""
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
    """Compute safely usable memory bytes accounting for OS headroom and reserves."""
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
    cpu_cores: int | None = None,
) -> int:
    """Derive worker count that fits strictly within memory limits without risking OOM."""
    if worker_memory_mib < 1:
        raise ValueError("worker_memory_mib must be >= 1")
    budget = usable_memory_bytes(
        available, safety_fraction=safety_fraction, reserve_bytes=reserve_bytes
    )
    mem_workers = max(1, budget // (worker_memory_mib * _MEBIBYTE))
    cores = (
        cpu_cores if cpu_cores is not None and cpu_cores >= 1 else default_cpu_cores()
    )
    return max(1, min(cores, mem_workers))


@dataclass(frozen=True, slots=True)
class RuntimeResourceProfile:
    """Derived machine resources used by execution engines, workers, and DuckDB."""

    cpu_cores: int
    workers: int
    threads: int
    memory_limit: str
    temp_directory: str
    available_memory_bytes: int
    worker_memory_mib: int
    worker_memory_safety: float

    @property
    def worker_threads(self) -> int:
        return self.threads

    @property
    def memory_limit_str(self) -> str:
        return self.memory_limit

    @property
    def memory_limit_mb(self) -> int:
        """Extracted integer MiB memory limit."""
        digits = "".join(c for c in self.memory_limit if c.isdigit())
        return int(digits) if digits else 4096

    @property
    def temp_dir(self) -> Path:
        """Temporary spill directory as a Path."""
        return Path(self.temp_directory)


def derive_resources(
    requested_threads: int | None = None,
    requested_memory_limit: str | None = None,
    worker_memory_mib: int = DEFAULT_WORKER_MEMORY_MIB,
    worker_memory_safety: float = DEFAULT_WORKER_MEMORY_SAFETY,
    memory_fraction: float = DEFAULT_MEMORY_FRACTION,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeResourceProfile:
    """Derive scalable runtime resources from the settings registry and system probes."""
    from .settings import resolve_settings

    overrides = dict(cli_overrides or {})
    if requested_threads is not None and requested_threads > 0:
        overrides["runtime.threads"] = requested_threads
        overrides["runtime.workers"] = requested_threads
    if requested_memory_limit:
        overrides["runtime.memory_limit"] = requested_memory_limit
    if worker_memory_mib != DEFAULT_WORKER_MEMORY_MIB:
        overrides["runtime.worker_memory_mib"] = worker_memory_mib
    if worker_memory_safety != DEFAULT_WORKER_MEMORY_SAFETY:
        overrides["runtime.worker_memory_safety"] = worker_memory_safety
    if memory_fraction != DEFAULT_MEMORY_FRACTION:
        overrides["runtime.memory_fraction"] = memory_fraction

    resolved = resolve_settings(
        include=["runtime"],
        env=env,
        cli_overrides=overrides,
    )
    temp_dir = Path(str(resolved["runtime.temp_directory"])).resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)

    return RuntimeResourceProfile(
        cpu_cores=default_cpu_cores(),
        workers=int(resolved["runtime.workers"]),
        threads=int(resolved["runtime.threads"]),
        memory_limit=str(resolved["runtime.memory_limit"]),
        temp_directory=str(temp_dir),
        available_memory_bytes=available_memory_bytes(),
        worker_memory_mib=int(resolved["runtime.worker_memory_mib"]),
        worker_memory_safety=float(resolved["runtime.worker_memory_safety"]),
    )


__all__ = [
    "DEFAULT_MEMORY_FRACTION",
    "DEFAULT_WORKER_MEMORY_MIB",
    "DEFAULT_WORKER_MEMORY_SAFETY",
    "MIN_MEMORY_MIB",
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
