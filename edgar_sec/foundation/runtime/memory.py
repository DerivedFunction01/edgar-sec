"""Shared memory reclaim for long-lived processes.

gc alone frees C-backed objects only to the allocator; glibc returns pages to the OS on
malloc_trim, so long-lived workers and brokers call reclaim() at bounded intervals.
"""

from __future__ import annotations

import ctypes
import gc

_LIBC = None
_TRIM_DISABLED = False


def _malloc_trim() -> bool:
    """Return free C heap pages to the OS; False when unsupported."""
    global _LIBC, _TRIM_DISABLED
    if _TRIM_DISABLED:
        return False
    if _LIBC is None:
        try:
            _LIBC = ctypes.CDLL("libc.so.6")
        except OSError:
            _TRIM_DISABLED = True
            return False
    try:
        return bool(_LIBC.malloc_trim(0))
    except Exception:  # noqa: BLE001 - trimming is best-effort, never fatal
        _TRIM_DISABLED = True
        return False


def reclaim() -> None:
    """Collect reference cycles and release free C heap pages to the OS.

    Safe from any thread and platform; trimming is a no-op where malloc_trim is absent.
    """
    gc.collect()
    _malloc_trim()


__all__ = ["reclaim"]
