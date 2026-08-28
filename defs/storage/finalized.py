"""Generic read-only query and publication facade for finalized artifacts.

This module deliberately contains no SEC or phase-specific semantics.  A
phase supplies a validated DuckDB query and optional scalar functions; this
facade owns artifact opening, parameter binding, footer inspection, and
atomic Parquet publication.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Self

import duckdb

from .artifacts import file_sha256, parquet_column_names
from .duckdb_merge import connect
from .errors import StorageError


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class FinalizedArtifact:
    """A read-only DuckDB handle over one finalized Parquet artifact."""

    def __init__(self, path: str | os.PathLike[str], *, threads: int | None = None):
        self.path = os.path.abspath(os.fspath(path))
        if (
            not os.path.isfile(self.path)
            or Path(self.path).suffix.lower() != ".parquet"
        ):
            raise StorageError("finalized artifact must be an existing Parquet file")
        self._con = connect(threads=threads)

    @property
    def columns(self) -> list[str]:
        return parquet_column_names(self.path)

    @property
    def sha256(self) -> str:
        return file_sha256(self.path)

    @property
    def relation(self) -> str:
        """Return the safely quoted source relation for composed queries."""
        return f"read_parquet({_quote(self.path)})"

    def register_function(
        self,
        name: str,
        function: Callable[..., Any],
        *,
        parameters: list[type],
        return_type: type,
    ) -> None:
        self._con.create_function(
            name,
            function,
            parameters=parameters,
            return_type=return_type,
            null_handling="special",
        )

    def run(self, query: str, parameters: Iterable[Any] = ()) -> list[tuple]:
        """Execute a phase-supplied parameterized read query."""
        try:
            return self._con.execute(query, list(parameters)).fetchall()
        except duckdb.Error as exc:
            raise StorageError(f"finalized artifact query failed: {exc}") from exc

    def count(self) -> int:
        return int(self.run(f"SELECT count(*) FROM {self.relation}")[0][0])

    def copy_query(
        self,
        query: str,
        output_path: str | os.PathLike[str],
        parameters: Iterable[Any] = (),
    ) -> int:
        """Atomically publish the result of a parameterized SELECT as Parquet."""
        output = os.path.abspath(os.fspath(output_path))
        if os.path.exists(output):
            raise StorageError(f"immutable artifact already exists: {output}")
        os.makedirs(os.path.dirname(output), exist_ok=True)
        temporary = output + ".tmp"
        try:
            self._con.execute(
                f"COPY ({query}) TO {_quote(temporary)} (FORMAT PARQUET, COMPRESSION 'zstd')",
                list(parameters),
            )
            os.replace(temporary, output)
            return int(
                self._con.execute(
                    f"SELECT count(*) FROM read_parquet({_quote(output)})"
                ).fetchone()[0]
            )
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to publish Parquet artifact {output}: {exc}"
            ) from exc
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["FinalizedArtifact"]
