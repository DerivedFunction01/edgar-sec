"""Unit tests for foundation.io."""

from __future__ import annotations

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE


def test_the_io_chunk_size_is_a_64_kib_block() -> None:
    assert DEFAULT_IO_CHUNK_SIZE == 64 * 1024
