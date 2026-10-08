"""Unit tests for foundation.hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import (
    _TEXT_CHUNK_CHARS,
    file_sha256,
    sha256_bytes,
    sha256_text,
)
from edgar_sec.infra.storage.duckdb import connect

HELLO_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

# Catalog identity strings are derived inside DuckDB while the oracle is computed in
# Python, so the two must agree byte for byte.
CROSS_BOUNDARY_DIGESTS = [
    "",
    "hello world",
    "0000320193:000032019323000106:aapl-20230930.htm",
    "000032019323000106:0000320193-24-000077.txt",
    "00019617:000001961724000040:jpm-20231231.htm",
    "unicode:café",
]


def test_file_sha256_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert file_sha256(path) == HELLO_SHA256


def test_sha256_bytes_agrees_with_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert sha256_bytes(b"hello world") == file_sha256(path)


def test_file_sha256_streams_large_files(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    payload = b"z" * (1024 * 1024 + 17)
    path.write_bytes(payload)
    assert file_sha256(path) == sha256_bytes(payload)


@pytest.mark.parametrize("text", CROSS_BOUNDARY_DIGESTS)
def test_duckdb_sha256_agrees_with_python(text: str) -> None:
    """Catalog IDs must be identical whether computed in SQL or in Python."""
    with connect() as con:
        duckdb_digest = con.execute("SELECT sha256(?)", [text]).fetchone()[0]
    assert duckdb_digest == sha256_bytes(text.encode("utf-8"))


def test_sha256_text_matches_hashlib() -> None:
    assert sha256_text("test string") == hashlib.sha256(b"test string").hexdigest()


def test_sha256_text_streams_across_the_chunk_boundary() -> None:
    """Digest must be identical whether the input fits one chunk or many."""
    for size in (
        _TEXT_CHUNK_CHARS - 1,
        _TEXT_CHUNK_CHARS,
        _TEXT_CHUNK_CHARS + 1,
        2 * _TEXT_CHUNK_CHARS + 17,
    ):
        text = "A" * size
        assert sha256_text(text) == hashlib.sha256(text.encode()).hexdigest()


def test_sha256_text_chunking_preserves_multibyte_boundaries() -> None:
    """Slicing at a code point must never split a UTF-8 sequence."""
    text = "café" * (_TEXT_CHUNK_CHARS // 2 + 3)
    assert sha256_text(text) == hashlib.sha256(text.encode()).hexdigest()


def test_sha256_text_is_the_only_public_definition() -> None:
    """§1.1: two functions of one name with different behaviour violates the contract."""
    from edgar_sec.foundation.runtime import memory

    assert not hasattr(memory, "sha256_text")


def test_occurrence_id_matches_materialization_sql() -> None:
    """Both spellings must produce the same digest, or a locator-to-occurrence join
    between the catalog and a snapshot matches nothing and fails silently.
    """
    from edgar_sec.domain.document.models import (
        derive_document_locator_key,
        derive_occurrence_id,
    )

    documents = [
        ("0000320193", "0000320193-23-000106", "aapl-20230930.htm"),
        ("0000320193", "000032019323000106", "aapl-20230930.htm"),
        ("0001961704", "000196170424000040", "jpm-20231231.htm"),
        ("4515", "000000620126000014", "aal-20251231.htm"),
        ("0", "000000000000000000", "unknown.htm"),
    ]

    with connect() as con:
        for cik, accession, path in documents:
            # Mirrors `materialization.build_part_unnest_query`, which hashes
            # `replace(accession_number, '-', '')`; a different spelling here would pin
            # parity with a form production never emits.
            row = con.execute(
                """
                SELECT sha256(?1 || ':' || replace(?2, '-', '') || ':' || ?3),
                       sha256(replace(?2, '-', '') || ':' || ?3)
                """,
                [cik, accession, path],
            ).fetchone()
            occurrence_sql, locator_sql = row

            assert derive_occurrence_id(cik, accession, path) == occurrence_sql, (
                f"occurrence_id diverged from SQL for {cik}:{accession}:{path}"
            )
            assert derive_document_locator_key(accession, path) == locator_sql, (
                f"locator key diverged from SQL for {accession}:{path}"
            )


def test_both_accession_spellings_hash_to_one_identity() -> None:
    """Deriving both spellings separately hid this: the cross-boundary test feeds
    one string to both languages and never exercised the runtime pairing.
    """
    from edgar_sec.domain.document.models import (
        DocumentLocator,
        derive_document_locator_key,
        derive_occurrence_id,
    )

    path = "aapl-20230930.htm"
    hyphenated, unhyphenated = "0000320193-23-000106", "000032019323000106"

    assert derive_document_locator_key(hyphenated, path) == (
        derive_document_locator_key(unhyphenated, path)
    )
    assert derive_occurrence_id("320193", hyphenated, path) == (
        derive_occurrence_id("320193", unhyphenated, path)
    )
    assert (
        DocumentLocator.from_parts(hyphenated, path).document_locator_key
        == DocumentLocator.from_parts(unhyphenated, path).document_locator_key
    )


def test_occurrence_id_is_hash_of_parts_not_of_locator_key() -> None:
    """Reintroducing the hash-of-hash form fails this even when the SQL column is
    absent from the fixture.
    """
    from edgar_sec.domain.document.models import (
        derive_document_locator_key,
        derive_occurrence_id,
    )

    cik, accession, path = "0000320193", "0000320193-23-000106", "aapl.htm"
    locator_key = derive_document_locator_key(accession, path)
    assert derive_occurrence_id(cik, accession, path) != sha256_text(
        f"{cik}:{locator_key}"
    )
