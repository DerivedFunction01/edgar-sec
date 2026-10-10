"""Incremental fixture response decompression and integrity verification."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import BinaryIO

import zstandard

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
    ResponseBodyRef,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import open_fixture


class _NullWriter:
    def write(self, chunk: bytes) -> int:
        return len(chunk)


class _HashingReader:
    def __init__(self, source: BinaryIO, digest: object) -> None:
        self.source = source
        self.digest = digest
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.source.read(size)
        self.bytes_read += len(chunk)
        self.digest.update(chunk)
        return chunk


def _write_all(destination: BinaryIO, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        written = destination.write(remaining)
        if written is None or written <= 0:
            raise FixtureStoreError("replay destination did not accept response bytes")
        remaining = remaining[written:]


def _stream_body(
    blob: BinaryIO,
    destination: BinaryIO,
    *,
    byte_size: int,
    response_sha256: str,
    stored_byte_size: int,
    stored_sha256: str,
) -> None:
    stored_hash = hashlib.sha256()
    response_hash = hashlib.sha256()
    response_count = 0
    hashing_reader = _HashingReader(blob, stored_hash)
    reader = zstandard.ZstdDecompressor().stream_reader(
        hashing_reader, read_size=DEFAULT_IO_CHUNK_SIZE, closefd=False
    )
    try:
        while chunk := reader.read(DEFAULT_IO_CHUNK_SIZE):
            response_count += len(chunk)
            if response_count > byte_size:
                raise FixtureStoreError(
                    "decompressed response exceeds recorded byte size"
                )
            response_hash.update(chunk)
            _write_all(destination, chunk)
    except zstandard.ZstdError as exc:
        raise FixtureStoreError("invalid Zstandard response body") from exc
    finally:
        reader.close()
    if (
        hashing_reader.bytes_read != stored_byte_size
        or stored_hash.hexdigest() != stored_sha256
    ):
        raise FixtureStoreError("stored response size or SHA-256 mismatch")
    if response_count != byte_size or response_hash.hexdigest() != response_sha256:
        raise FixtureStoreError("response size or SHA-256 mismatch")


def verify_response_row(
    connection: sqlite3.Connection, row: tuple[object, ...]
) -> None:
    body_id, digest, size, codec, stored_digest, stored_size = row
    if codec != "zstd":
        raise FixtureStoreError("unsupported fixture response codec")
    blob = connection.blobopen(
        "response_bodies", "compressed_body", body_id, readonly=True
    )
    try:
        if len(blob) != stored_size:
            raise FixtureStoreError("stored response byte size mismatch")
        _stream_body(
            blob,
            _NullWriter(),
            byte_size=size,
            response_sha256=digest,
            stored_byte_size=stored_size,
            stored_sha256=stored_digest,
        )
    finally:
        blob.close()


def replay_fixture_response(
    paths: AcquisitionPaths,
    fixture_id: str,
    response_sha256: str,
    destination: BinaryIO,
) -> ResponseBodyRef:
    """Stream one verified response body to a caller-managed binary destination."""
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            "SELECT body_id, response_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
            "FROM response_bodies WHERE response_sha256 = ?",
            (response_sha256,),
        ).fetchone()
        if row is None:
            raise FixtureStoreError("fixture response body not found")
        body_id, digest, size, codec, stored_digest, stored_size = row
        if codec != "zstd":
            raise FixtureStoreError("unsupported fixture response codec")
        blob = connection.blobopen(
            "response_bodies", "compressed_body", body_id, readonly=True
        )
        try:
            if len(blob) != stored_size:
                raise FixtureStoreError("stored response byte size mismatch")
            _stream_body(
                blob,
                destination,
                byte_size=size,
                response_sha256=digest,
                stored_byte_size=stored_size,
                stored_sha256=stored_digest,
            )
        finally:
            blob.close()
        return ResponseBodyRef(digest, size, stored_digest, stored_size, True)
    finally:
        connection.close()
