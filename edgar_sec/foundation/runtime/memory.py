"""Shared memory reclaim for long-lived processes.

Python garbage collection frees large C-backed objects (HTML trees, decompressed
payloads, Arrow tables) to the C allocator, but glibc only returns freed pages
to the operating system on malloc_trim. Batch workers and brokers therefore
call reclaim() at bounded intervals to keep resident memory near the live
working set instead of the high-water mark.

Streaming text hashing lives in :mod:`edgar_sec.foundation.hashing`: this module
used to carry a second ``sha256_text`` with different behaviour from the
``hashing`` one, which is exactly the shape of defect AGENTS.md §1.1 bans.
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

    Safe to call from any thread and on any platform: trimming is a no-op
    when glibc (or an equivalent malloc_trim) is unavailable.
    """
    gc.collect()
    _malloc_trim()


__all__ = ["reclaim"]
