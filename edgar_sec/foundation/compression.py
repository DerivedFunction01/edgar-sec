"""zstd frame compression for the BLOB payloads stored elsewhere in the tree.

The codec objects are thread-local because a ``ZstdCompressor`` carries window
and history state and is not safe to share across threads. A process that
compresses on many threads pays one small allocator per thread, which is the
right trade against sharing mutable compression state.
"""

from __future__ import annotations

import threading

import zstandard as zstd

_thread_local = threading.local()


def _get_compressor() -> zstd.ZstdCompressor:
    compressor = getattr(_thread_local, "compressor", None)
    if compressor is None:
        compressor = zstd.ZstdCompressor()
        _thread_local.compressor = compressor
    return compressor


def _get_decompressor() -> zstd.ZstdDecompressor:
    decompressor = getattr(_thread_local, "decompressor", None)
    if decompressor is None:
        decompressor = zstd.ZstdDecompressor()
        _thread_local.decompressor = decompressor
    return decompressor


def compress_payload(payload: bytes) -> bytes:
    """Compress one raw payload into a single zstd frame."""
    return _get_compressor().compress(payload)


def decompress_payload(blob: bytes) -> bytes:
    """Decompress one zstd frame back into its raw bytes.

    Raises ``zstandard.ZstdError`` when ``blob`` is not a frame, which is the
    signal a caller sniffing a possibly-uncompressed column branches on.
    """
    return _get_decompressor().decompress(blob)


__all__ = ["compress_payload", "decompress_payload"]
