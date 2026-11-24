"""Facade capacity and cache-budget derivation from the runtime resource profile."""

from __future__ import annotations

from edgar_sec.foundation.runtime.resources import (
    MEBIBYTE,
    RuntimeResourceProfile,
    derive_resources,
)

# Mean retained bytes per live facade, from the facade memory profile.
_RETAINED_BYTES_PER_FACADE = int(6.9 * MEBIBYTE)


def derive_facade_capacity(resources: RuntimeResourceProfile | None = None) -> int:
    """Facade count one worker memory share holds at the measured per-facade cost."""
    profile = resources if resources is not None else derive_resources()
    budget_bytes = profile.worker_memory_mib * MEBIBYTE
    return max(1, budget_bytes // _RETAINED_BYTES_PER_FACADE)


def derive_content_cache_budget(
    resources: RuntimeResourceProfile | None = None,
) -> int:
    """Content-cache byte budget: a settings fraction of one worker memory share."""
    from edgar_sec.foundation.runtime.settings import resolve_settings

    profile = resources if resources is not None else derive_resources()
    fraction = float(
        resolve_settings(include=["client"])["client.content_cache_fraction"]
    )
    return max(1, int(profile.worker_memory_mib * MEBIBYTE * fraction))


def derive_content_disk_budget() -> int:
    """Disk-tier byte budget for spilled derivations, from the settings seam."""
    from edgar_sec.foundation.runtime.settings import resolve_settings

    return int(resolve_settings(include=["client"])["client.content_disk_budget_bytes"])


__all__ = [
    "derive_content_cache_budget",
    "derive_content_disk_budget",
    "derive_facade_capacity",
]
