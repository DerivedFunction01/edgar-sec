"""Shared memory reclaim helpers for long-lived acquisition processes.

Python garbage collection frees large C-backed objects (selectolax/lexbor
trees, decompressed payloads) to the C allocator, but glibc only returns
freed pages to the operating system on :func:`malloc_trim`. Acquisition
workers and the SEC broker therefore call :func:`reclaim` at bounded
intervals to keep resident memory near the live working set instead of the
per-document high-water mark.
"""

from __future__ import annotations

import ctypes
import gc
import hashlib

_LIBC = None
_TRIM_DISABLED = False

_SHA256_CHUNK_CHARS = 1 << 20


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
    when glibc (or an equivalent ``malloc_trim``) is unavailable.
    """
    gc.collect()
    _malloc_trim()


def sha256_text(text: str) -> str:
    """Hash a string without materializing a second full-size bytes copy.

    Encodes in bounded chunks; UTF-8 chunk encodings concatenate to exactly
    the bytes a whole-string encode would produce, so the digest is
    identical to ``hashlib.sha256(text.encode("utf-8")).hexdigest()``.
    """
    digest = hashlib.sha256()
    if len(text) <= _SHA256_CHUNK_CHARS:
        digest.update(text.encode("utf-8"))
        return digest.hexdigest()
    for start in range(0, len(text), _SHA256_CHUNK_CHARS):
        digest.update(text[start : start + _SHA256_CHUNK_CHARS].encode("utf-8"))
    return digest.hexdigest()


__all__ = ["reclaim", "sha256_text"]
