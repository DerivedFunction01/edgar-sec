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
from .staging import DuckDBStaging


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class FinalizedDataset:
    """A read-only DuckDB handle over a finalized Parquet artifact or multi-part snapshot."""

    def __init__(
        self,
        source: str | os.PathLike[str] | dict,
        *,
        artifacts_root: str | os.PathLike[str] | None = None,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | os.PathLike[str] | None = None,
    ) -> None:
        self._artifacts_root = (
            Path(artifacts_root).resolve() if artifacts_root is not None else None
        )
        self._con = connect(
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
            preserve_insertion_order=False,
        )
        self.manifest: dict | None = None
        self.snapshot_id: str | None = None
        self.parent_snapshot_id: str | None = None
        self.resolved_part_paths: list[str] = []
        self._single_path: str | None = None
        self._sha256: str | None = None

        if isinstance(source, dict):
            if (
                "phase" in source
                and "dataset" in source
                and "resolved_parts" not in source
                and "artifact_path" not in source
            ):
                from defs.runtime.artifacts import resolve_snapshot_manifest

                manifest_dict, _ = resolve_snapshot_manifest(
                    phase=source["phase"],
                    dataset=source["dataset"],
                    artifacts_root=self._artifacts_root or ".",
                )
                self.manifest = manifest_dict
                self._init_from_manifest(manifest_dict)
            else:
                self.manifest = source
                self._init_from_manifest(source)
        else:
            path_obj = Path(source).expanduser().resolve()
            if path_obj.is_file() and path_obj.suffix.lower() == ".parquet":
                self._single_path = str(path_obj)
                self.resolved_part_paths = [str(path_obj)]
                self._sha256 = file_sha256(str(path_obj))
            elif path_obj.is_file() and path_obj.suffix.lower() == ".json":
                from defs.storage import load_json

                manifest = load_json(path_obj)
                self.manifest = manifest
                if self._artifacts_root is None:
                    # Infer artifacts_root by looking for manifests/ in ancestors
                    for parent in path_obj.parents:
                        if (
                            parent / "manifests"
                        ).is_dir() or parent.name == "manifests":
                            self._artifacts_root = (
                                parent.parent if parent.name == "manifests" else parent
                            )
                            break
                    if self._artifacts_root is None:
                        self._artifacts_root = path_obj.parent
                self._init_from_manifest(manifest)
            elif path_obj.is_dir():
                manifest_candidate = path_obj / "snapshot.manifest.json"
                if not manifest_candidate.is_file():
                    manifest_candidate = path_obj / "snapshot.json"
                if not manifest_candidate.is_file():
                    raise StorageError(
                        f"no snapshot manifest found in directory: {path_obj}"
                    )
                from defs.storage import load_json

                manifest = load_json(manifest_candidate)
                self.manifest = manifest
                if self._artifacts_root is None:
                    for parent in manifest_candidate.parents:
                        if (
                            parent / "manifests"
                        ).is_dir() or parent.name == "manifests":
                            self._artifacts_root = (
                                parent.parent if parent.name == "manifests" else parent
                            )
                            break
                    if self._artifacts_root is None:
                        self._artifacts_root = path_obj.parent
                self._init_from_manifest(manifest)
            else:
                raise StorageError(
                    f"source must be a Parquet file, snapshot manifest JSON, or snapshot directory: {source}"
                )

    def _resolve_rel(self, path_str: str) -> str:
        if os.path.isabs(path_str):
            return path_str
        if self._artifacts_root is not None:
            return str((self._artifacts_root / path_str).resolve())
        return os.path.abspath(path_str)

    def _init_from_manifest(self, manifest: dict) -> None:
        self.snapshot_id = manifest.get("snapshot_id")
        self.parent_snapshot_id = manifest.get("parent_snapshot_id")
        resolved = manifest.get("resolved_parts", [])
        if not resolved and "artifact_path" in manifest:
            # Single-artifact manifest
            single = self._resolve_rel(manifest["artifact_path"])
            self._single_path = single
            self.resolved_part_paths = [single]
            self._sha256 = manifest.get("artifact_sha256") or file_sha256(single)
            return
        if not resolved:
            raise StorageError("snapshot manifest contains no resolved parts")
        self.resolved_part_paths = [
            self._resolve_rel(p["path"]) for p in resolved if "path" in p
        ]
        for p in self.resolved_part_paths:
            if not os.path.isfile(p):
                raise StorageError(f"snapshot part file does not exist: {p}")
        self._sha256 = manifest.get("artifact_sha256") or manifest.get(
            "full_artifact_sha256"
        )

    @property
    def path(self) -> str:
        """Compatibility property for single-part consumers."""
        if self._single_path is not None:
            return self._single_path
        if len(self.resolved_part_paths) == 1:
            return self.resolved_part_paths[0]
        raise StorageError(
            "multi-part snapshot has no single file path; use resolved_part_paths or relation"
        )

    @property
    def columns(self) -> list[str]:
        if not self.resolved_part_paths:
            raise StorageError("dataset has no active parts")
        return parquet_column_names(self.resolved_part_paths[0])

    @property
    def sha256(self) -> str:
        if self._sha256 is not None:
            return self._sha256
        if self._single_path is not None:
            self._sha256 = file_sha256(self._single_path)
            return self._sha256
        # Hash of ordered part hashes
        import hashlib

        h = hashlib.sha256()
        for p in sorted(self.resolved_part_paths):
            h.update(file_sha256(p).encode())
        self._sha256 = h.hexdigest()
        return self._sha256

    @property
    def relation(self) -> str:
        """Return the safely quoted DuckDB SQL relation for queries."""
        if not self.resolved_part_paths:
            raise StorageError("dataset has no resolved parts")
        if self.manifest and self.manifest.get("replacement_key_parts"):
            parent_parts = [
                self._resolve_rel(p["path"])
                for p in self.manifest.get("resolved_parts", [])
                if p not in self.manifest.get("added_parts", [])
            ]
            replacement_keys = [
                self._resolve_rel(k["path"])
                for k in self.manifest.get("replacement_key_parts", [])
            ]
            added_parts = [
                self._resolve_rel(p["path"])
                for p in self.manifest.get("added_parts", [])
            ]
            if parent_parts and replacement_keys and added_parts:
                parent_sql = (
                    f"read_parquet([{', '.join(_quote(p) for p in parent_parts)}])"
                )
                keys_sql = (
                    f"read_parquet([{', '.join(_quote(k) for k in replacement_keys)}])"
                )
                added_sql = (
                    f"read_parquet([{', '.join(_quote(a) for a in added_parts)}])"
                )
                return (
                    f"(\n"
                    f"  SELECT parent.* FROM {parent_sql} AS parent\n"
                    f"  ANTI JOIN (SELECT cik FROM {keys_sql}) AS keys\n"
                    f"  ON parent.cik = keys.cik\n"
                    f"  UNION ALL\n"
                    f"  SELECT * FROM {added_sql}\n"
                    f")"
                )
        quoted_parts = ", ".join(_quote(p) for p in self.resolved_part_paths)
        return f"read_parquet([{quoted_parts}])"

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
            raise StorageError(f"dataset query failed: {exc}") from exc

    def count(self) -> int:
        return int(self.run(f"SELECT count(*) FROM {self.relation}")[0][0])

    def distinct_values(self, column: str) -> set[str]:
        """Return distinct values for a validated scalar column."""
        if column not in self.columns:
            raise StorageError(f"column not present in finalized dataset: {column}")
        try:
            rows = self._con.execute(
                f"SELECT DISTINCT {_identifier(column)} FROM {self.relation} "
                f"WHERE {_identifier(column)} IS NOT NULL"
            ).fetchall()
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to read distinct values for {column}: {exc}"
            ) from exc
        return {str(row[0]) for row in rows}

    def key_overlap_count(
        self, other_source: str | os.PathLike[str] | FinalizedDataset, column: str
    ) -> int:
        """Count shared scalar keys with another finalized dataset or Parquet file."""
        if isinstance(other_source, FinalizedDataset):
            other_rel = other_source.relation
            if column not in self.columns or column not in other_source.columns:
                raise StorageError(
                    f"column not present in both finalized datasets: {column}"
                )
        else:
            other_path = os.path.abspath(os.fspath(other_source))
            if column not in self.columns or column not in parquet_column_names(
                other_path
            ):
                raise StorageError(
                    f"column not present in both finalized datasets: {column}"
                )
            other_rel = f"read_parquet({_quote(other_path)})"
        try:
            return int(
                self._con.execute(
                    "SELECT count(*) FROM ("
                    f"SELECT {_identifier(column)} FROM {self.relation} "
                    "INTERSECT "
                    f"SELECT {_identifier(column)} FROM {other_rel})"
                ).fetchone()[0]
            )
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to compare finalized dataset keys: {exc}"
            ) from exc

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


class FinalizedArtifact(FinalizedDataset):
    """A read-only DuckDB handle over one finalized Parquet artifact (backwards-compatible)."""

    def __init__(
        self,
        path: str | os.PathLike[str] | dict,
        *,
        artifacts_root: str | os.PathLike[str] | None = None,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | os.PathLike[str] | None = None,
    ):
        super().__init__(
            path,
            artifacts_root=artifacts_root,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
        )

    def copy_union(
        self,
        other_path: str | os.PathLike[str],
        output_path: str | os.PathLike[str],
        *,
        order_by: str | None = None,
    ) -> int:
        """Atomically publish this artifact unioned with another artifact."""
        output = os.path.abspath(os.fspath(output_path))
        if os.path.exists(output):
            raise StorageError(f"immutable artifact already exists: {output}")
        other = os.path.abspath(os.fspath(other_path))
        if parquet_column_names(other) != self.columns:
            raise StorageError(
                "cannot union finalized artifacts with different schemas"
            )
        sources = f"read_parquet([{_quote(self.path)}, {_quote(other)}])"
        order = f" ORDER BY {_identifier(order_by)}" if order_by else ""
        query = f"SELECT * FROM {sources}{order}"
        os.makedirs(os.path.dirname(output), exist_ok=True)
        temporary = output + ".tmp"
        try:
            self._con.execute(
                f"COPY ({query}) TO {_quote(temporary)} "
                "(FORMAT PARQUET, COMPRESSION 'zstd')"
            )
            count = int(
                self._con.execute(
                    f"SELECT count(*) FROM read_parquet({_quote(temporary)})"
                ).fetchone()[0]
            )
            os.replace(temporary, output)
            return count
        except duckdb.Error as exc:
            raise StorageError(
                f"failed to publish finalized artifact union: {exc}"
            ) from exc
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)


__all__ = ["DuckDBStaging", "FinalizedArtifact", "FinalizedDataset"]
