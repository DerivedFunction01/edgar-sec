"""Contract tests for shared memory reclaim helpers."""

import hashlib

from defs.runtime.memory import reclaim, sha256_text


def test_sha256_text_matches_whole_string_encode():
    samples = [
        "",
        "short text",
        "ünïcodé ✓ 一二三 \x00 nulls",
        "a" * 5_000,
        ("chunk-boundary " * 100_000),  # > 1 MiB, exercises chunked path
    ]
    for text in samples:
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert sha256_text(text) == expected


def test_sha256_text_chunk_boundaries_preserve_multibyte_characters():
    # One multi-byte character per 512 KiB forces chunk boundaries to fall
    # between code points; digests must still match a whole-string encode.
    text = ("一二三" * 200_000) + "é"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert sha256_text(text) == expected


def test_reclaim_is_safe_and_repeatable():
    reclaim()  # must not raise on any platform
    reclaim()
