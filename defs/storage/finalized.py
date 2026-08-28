"""Generic read-only query and publication facade for finalized artifacts.

This module deliberately contains no SEC or phase-specific semantics.  A
phase supplies a validated DuckDB query and optional scalar functions; this
facade owns artifact opening, parameter binding, footer inspection, and
atomic Parquet publication.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Self

import duckdb

from .artifacts import file_sha256, parquet_column_names
from .duckdb_merge import connect
from .errors import StorageError


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class DuckDBStaging:
    """Disk-backed append staging for bounded query materialization.

    The staging database is temporary: callers publish only through
    :meth:`copy_table`, and the context manager removes the database after the
    caller finishes.  This keeps append and export semantics out of phase code.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | os.PathLike[str] | None = None,
        cleanup_root: bool = False,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_directory is not None:
            Path(temp_directory).mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.database_path))
        if threads is not None:
            self._con.execute("SET threads = ?", [max(1, int(threads))])
        if memory_limit is not None:
            self._con.execute("SET memory_limit = ?", [memory_limit])
        if temp_directory is not None:
            self._con.execute(
                "SET temp_directory = ?", [str(Path(temp_directory).resolve())]
            )
        self._con.execute("SET preserve_insertion_order = false")
        self._closed = False
        self._cleanup_root = cleanup_root

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

    def create_table_as(
        self, table: str, query: str, parameters: Iterable[Any] = ()
    ) -> None:
        try:
            self._con.execute(
                f"CREATE TABLE {_identifier(table)} AS {query}",
                list(parameters),
            )
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to create staging table {table}: {exc}"
            ) from exc

    def insert_query(
        self, table: str, query: str, parameters: Iterable[Any] = ()
    ) -> None:
        try:
            self._con.execute(
                f"INSERT INTO {_identifier(table)} {query}", list(parameters)
            )
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to append staging table {table}: {exc}"
            ) from exc

    def count(self, table: str) -> int:
        try:
            return int(
                self._con.execute(
                    f"SELECT count(*) FROM {_identifier(table)}"
                ).fetchone()[0]
            )
        except duckdb.Error as exc:
            raise StorageError(f"failed to count staging table {table}: {exc}") from exc

    def copy_table(self, table: str, output_path: str | os.PathLike[str]) -> int:
        """Atomically export one staged table to Parquet and return its row count."""
        output = os.path.abspath(os.fspath(output_path))
        if os.path.exists(output):
            raise StorageError(f"immutable artifact already exists: {output}")
        os.makedirs(os.path.dirname(output), exist_ok=True)
        temporary = output + ".tmp"
        try:
            count = self.count(table)
            self._con.execute(
                f"COPY (SELECT * FROM {_identifier(table)}) TO {_quote(temporary)} "
                "(FORMAT PARQUET, COMPRESSION 'zstd')"
            )
            os.replace(temporary, output)
            return count
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to export staging table {table} to {output}: {exc}"
            ) from exc
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def close(self) -> None:
        if self._closed:
            return
        self._con.close()
        self._closed = True
        for suffix in ("", ".wal"):
            self.database_path.with_name(self.database_path.name + suffix).unlink(
                missing_ok=True
            )
        if self._cleanup_root:
            shutil.rmtree(self.database_path.parent, ignore_errors=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class FinalizedArtifact:
    """A read-only DuckDB handle over one finalized Parquet artifact."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | os.PathLike[str] | None = None,
    ):
        self.path = os.path.abspath(os.fspath(path))
        if (
            not os.path.isfile(self.path)
            or Path(self.path).suffix.lower() != ".parquet"
        ):
            raise StorageError("finalized artifact must be an existing Parquet file")
        self._con = connect(
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
            preserve_insertion_order=False,
        )

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

    def copy_partitioned_query(
        self,
        query: str,
        output_dir: str | os.PathLike[str],
        partition_by: str,
        parameters: Iterable[Any] = (),
    ) -> list[Path]:
        """Atomically stream query output partitioned by a column into subdirectories."""
        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        try:
            self._con.execute(
                f"COPY ({query}) TO {_quote(str(destination))} "
                f"(FORMAT PARQUET, PARTITION_BY ({_identifier(partition_by)}), COMPRESSION 'zstd', OVERWRITE_OR_IGNORE 1)",
                list(parameters),
            )
            return sorted(destination.glob(f"{partition_by}=*"))
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to export partitioned Parquet to {output_dir}: {exc}"
            ) from exc

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["DuckDBStaging", "FinalizedArtifact"]
