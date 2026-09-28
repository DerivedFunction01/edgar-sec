"""Unit tests for foundation.runtime.memory."""

from __future__ import annotations

import hashlib

from edgar_sec.foundation.runtime.memory import reclaim, sha256_text


def test_reclaim_does_not_crash() -> None:
    reclaim()


def test_sha256_text_matches_hashlib() -> None:
    short_text = "test string"
    assert (
        sha256_text(short_text)
        == hashlib.sha256(short_text.encode("utf-8")).hexdigest()
    )


def test_sha256_text_streams_across_chunk_boundary() -> None:
    long_text = "A" * (2 * 1024 * 1024 + 50)
    assert (
        sha256_text(long_text) == hashlib.sha256(long_text.encode("utf-8")).hexdigest()
    )
