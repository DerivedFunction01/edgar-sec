"""Shared byte-buffer sizes for streaming I/O across every layer."""

from __future__ import annotations

# One buffered block size for every layer that streams bytes. It is a transfer
# frame, not a semantic limit and not a row batch.
DEFAULT_IO_CHUNK_SIZE = 64 * 1024

__all__ = ["DEFAULT_IO_CHUNK_SIZE"]
