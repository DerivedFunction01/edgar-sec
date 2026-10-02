"""Tests for the zstd frame codec shared by every BLOB-storing consumer."""

from __future__ import annotations

import threading

import pytest
import zstandard as zstd

from edgar_sec.foundation.compression import (
    compress_payload,
    decompress_payload,
)

#: The frame magic the viewer's BLOB sniffing depends on
#: (``apps/viewer/datasets.py``): a column value that does not start with it is
#: treated as stored uncompressed and never routed here.
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"a", id="single-byte"),
        pytest.param(bytes(range(256)), id="all-byte-values"),
        pytest.param(b"<html><body>ACME</body></html>" * 4, id="repeated-html"),
    ],
)
def test_round_trip_is_byte_exact(payload: bytes) -> None:
    assert decompress_payload(compress_payload(payload)) == payload


def test_repetitive_payload_compresses_below_its_original_size() -> None:
    payload = b"repeat " * 500
    blob = compress_payload(payload)
    assert len(blob) < len(payload)
    assert decompress_payload(blob) == payload


def test_output_carries_the_zstd_frame_magic() -> None:
    assert compress_payload(b"anything").startswith(ZSTD_FRAME_MAGIC)


def test_decompressing_a_non_frame_raises() -> None:
    """A caller that sniffs a possibly-uncompressed column branches on this.

    The viewer treats a ``ZstdError`` as "this cell claims to be compressed and
    is not", so the raise is part of the contract rather than an accident.
    """
    with pytest.raises(zstd.ZstdError):
        decompress_payload(b"this is not a zstd frame at all")


def test_concurrent_compression_and_decompression_stay_correct() -> None:
    """The codecs are thread-local; sharing one would corrupt the window state."""
    results: dict[int, bytes] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def _round_trip(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            payload = f"document-{index}-".encode() * (index + 1)
            results[index] = decompress_payload(compress_payload(payload))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=_round_trip, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert results == {i: f"document-{i}-".encode() * (i + 1) for i in range(8)}
