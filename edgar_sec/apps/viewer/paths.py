"""Filename and suffix constants for the apps/viewer pipeline.

:no-path-tree:
"""

from __future__ import annotations

DATABASE_SUFFIXES = {".db", ".sqlite", ".duckdb"}
DATA_SUFFIXES = {".parquet", ".db", ".sqlite"}

__all__ = ["DATABASE_SUFFIXES", "DATA_SUFFIXES"]
