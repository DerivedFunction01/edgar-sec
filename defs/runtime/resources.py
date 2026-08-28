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


def _physical_memory_bytes() -> int:
    """Return available memory, with a portable operating-system fallback."""
    if psutil is not None:
        return int(psutil.virtual_memory().available)
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, value, unit = line.split()
            if name == "MemTotal:":
                return int(value) * (1024 if unit == "kB" else 1)
    except (OSError, ValueError):
        pass
    pages = os.sysconf("SC_PHYS_PAGES")
    page_size = os.sysconf("SC_PAGE_SIZE")
    return int(pages * page_size)


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


@dataclass(frozen=True)
class RuntimeResourceProfile:
    """Derived machine resources used by execution engines and stages."""

    cpu_cores: int
    workers: int
    threads: int
    memory_limit: str
    temp_directory: str


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
    return RuntimeResourceProfile(
        cpu_cores=default_cpu_cores(),
        workers=int(values["runtime.workers"]),
        threads=int(values["runtime.threads"]),
        memory_limit=str(values["runtime.memory_limit"]),
        temp_directory=str(Path(str(values["runtime.temp_directory"])).resolve()),
    )


__all__ = [
    "RuntimeResourceProfile",
    "default_cpu_cores",
    "default_memory_limit",
    "default_threads",
    "derive_resources",
]
