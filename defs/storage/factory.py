"""Factories for shared storage backend composition."""

from __future__ import annotations

from .jsonl import JsonlChunkBackend
from .parquet import ParquetBackend


def make_chunk_backend(storage_format: str, root: str):
    """Build the immutable chunk backend for a supported file format."""
    if storage_format == "parquet":
        return ParquetBackend(root)
    if storage_format == "jsonl":
        return JsonlChunkBackend(root)
    raise ValueError("storage_format must be 'parquet' or 'jsonl'")


__all__ = ["make_chunk_backend"]
