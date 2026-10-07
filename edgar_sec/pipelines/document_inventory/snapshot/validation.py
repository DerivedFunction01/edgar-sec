"""Validate complete immutable snapshot artifacts before publication or reuse."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile

from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_path_list
from edgar_sec.infra.storage.dag.doctor import _resolve_part_path
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.parquet import read_parquet_key_bounds
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.errors import (
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.models import SnapshotMetadata
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.document_inventory.snapshot.specs import INVENTORY_RELATIONS
from edgar_sec.domain.document_inventory.schemas import (
    ENTRY_SCHEMA_VERSION,
)

_RELATIONS = {spec.name: spec.schema for spec in INVENTORY_RELATIONS}
_RELATION_PKS = {spec.name: spec.primary_key for spec in INVENTORY_RELATIONS}
_RELATION_ENTITY_KEYS = {
    spec.name: (spec.entity_key or spec.primary_key[0]) for spec in INVENTORY_RELATIONS
}


def _artifact_path(
    paths: InventoryPaths,
    owner_snapshot_id: str,
    value: object,
    *,
    staged_root: Path | None,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValidationFailedError("snapshot artifact path is invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
        raise ValidationFailedError("snapshot artifact path escapes its root")
    if relative.parts[0] in _RELATIONS:
        source_root = (
            staged_root
            if staged_root is not None
            else paths.snapshot_root(owner_snapshot_id)
        )
        resolved = (source_root / relative).resolve()
        try:
            resolved.relative_to(source_root.resolve())
        except ValueError as exc:
            raise ValidationFailedError(
                "snapshot artifact path escapes its owner"
            ) from exc
        return resolved
    source_id = relative.parts[0]
    try:
        source_root = paths.snapshot_root(source_id)
    except ValueError as exc:
        raise ValidationFailedError("snapshot artifact owner is invalid") from exc
    if source_id == owner_snapshot_id and staged_root is not None:
        source_root = staged_root
    resolved = (source_root / Path(*relative.parts[1:])).resolve()
    try:
        resolved.relative_to(source_root.resolve())
    except ValueError as exc:
        raise ValidationFailedError("snapshot artifact path escapes its owner") from exc
    return resolved


def _validate_parquet(
    path: Path, schema: pa.Schema, row_count: int, digest: str, row_groups: int | None
) -> pq.ParquetFile:
    if (
        not isinstance(row_count, int)
        or isinstance(row_count, bool)
        or row_count < 0
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or (
            row_groups is not None
            and (
                not isinstance(row_groups, int)
                or isinstance(row_groups, bool)
                or row_groups < 0
            )
        )
    ):
        raise ValidationFailedError("snapshot artifact metadata is invalid")
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException, pq.ParquetException) as exc:
        raise ValidationFailedError(f"snapshot Parquet is unreadable: {path}") from exc
    actual = parquet.schema_arrow
    if actual.names != schema.names or any(
        actual.field(name).type != field.type
        for name, field in zip(schema.names, schema, strict=True)
    ):
        raise ValidationFailedError(f"snapshot schema mismatch: {path}")
    if parquet.metadata.num_rows != row_count:
        raise ValidationFailedError(f"snapshot row count mismatch: {path}")
    if row_groups is not None and parquet.metadata.num_row_groups != row_groups:
        raise ValidationFailedError(f"snapshot row-group count mismatch: {path}")
    if file_sha256(path) != digest:
        raise ValidationFailedError(f"snapshot digest mismatch: {path}")
    return parquet


def _part_files(
    paths: InventoryPaths,
    snapshot_id: str,
    records: object,
    relation: str,
    schema: pa.Schema,
    *,
    staged_root: Path | None,
    local_files: set[Path],
) -> list[Path]:
    if not isinstance(records, list):
        raise ValidationFailedError("snapshot relation parts must be a list")
    result = []
    years = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValidationFailedError("snapshot part descriptor must be an object")
        path = _artifact_path(
            paths, snapshot_id, record.get("path"), staged_root=staged_root
        )
        relative = Path(record["path"])
        valid_path = (
            len(relative.parts) == 3
            and relative.parts[1] == relation
            and bool(re.fullmatch(r"part-\d{5}\.parquet", relative.parts[2]))
        ) or (
            len(relative.parts) == 2
            and relative.parts[0] == relation
            and bool(re.fullmatch(r"part-\d{5}\.parquet", relative.parts[1]))
        )
        if not valid_path:
            raise ValidationFailedError(
                f"snapshot partition path is invalid: {record['path']!r}"
            )
        if not path.is_file():
            raise ValidationFailedError(f"snapshot part is missing: {path}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValidationFailedError(f"snapshot part is unreadable: {path}") from exc
        if size != record.get("byte_size"):
            raise ValidationFailedError(f"snapshot part size mismatch: {path}")
        if not isinstance(record.get("byte_size"), int) or isinstance(
            record.get("byte_size"), bool
        ):
            raise ValidationFailedError(f"snapshot part size is invalid: {path}")
        parquet = _validate_parquet(
            path,
            schema,
            record.get("row_count"),
            record.get("sha256"),
            record.get("row_group_count"),
        )
        if parquet.metadata.num_rows < 1 or parquet.metadata.num_row_groups < 1:
            raise ValidationFailedError(f"snapshot part has no row groups: {path}")
        key_column = _RELATION_ENTITY_KEYS[relation]
        key_min, key_max = read_parquet_key_bounds(path, key_column)
        if (key_min, key_max) != (record.get("key_min"), record.get("key_max")):
            raise ValidationFailedError(f"snapshot part key range mismatch: {path}")
        if Path(record["path"]).parts[0] in (snapshot_id, relation):
            local_files.add(path)
        result.append(path)
    return result


def _create_view(
    con, name: str, files: list[Path], schema: pa.Schema, pk: tuple[str, ...]
) -> None:
    if files:
        for p in files:
            file_sql = sql_path_list([str(p)])
            pk_cols = ", ".join(sql_identifier(c) for c in pk)
            query = (
                f"SELECT count(*) FROM (SELECT {pk_cols} FROM read_parquet({file_sql}) "
                f"GROUP BY {pk_cols} HAVING count(*) > 1)"
            )
            if int(con.execute(query).fetchone()[0]):
                raise ValidationFailedError(f"duplicate {name} primary key in {p.name}")
        pk_cols = ", ".join(sql_identifier(c) for c in pk)
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS "
            f"WITH ranked AS ("
            f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk_cols} ORDER BY file_row_number DESC) AS _rnk "
            f"  FROM read_parquet({sql_path_list([str(p) for p in files])}, file_row_number=true, hive_partitioning=false)"
            f") SELECT * EXCLUDE(_rnk, file_row_number) FROM ranked WHERE _rnk = 1"
        )
    else:
        empty_name = f"empty_{name}"
        con.register(empty_name, pa.Table.from_batches([], schema=schema))
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS "
            f"SELECT * FROM {sql_identifier(empty_name)}"
        )


def _count(con, query: str) -> int:
    return int(con.execute(query).fetchone()[0])


def _validate_sorted(
    con: duckdb.DuckDBPyConnection, path: Path, columns: list[str]
) -> None:
    source = sql_path_list([str(path)])
    cols_expr = ", ".join(sql_identifier(c) for c in columns)
    prev_cols = ", ".join(
        f"lag({sql_identifier(c)}) OVER (ORDER BY file_row_number) AS p_{c}"
        for c in columns
    )
    prev_tuple = ", ".join(f"p_{c}" for c in columns)
    query = (
        f"SELECT count(*) FROM ("
        f"SELECT {cols_expr}, {prev_cols} "
        f"FROM read_parquet({source}, file_row_number=true, hive_partitioning=false)"
        f") WHERE ({prev_tuple}) >= ({cols_expr}) AND p_{columns[0]} IS NOT NULL"
    )
    if int(con.execute(query).fetchone()[0]):
        raise ValidationFailedError(f"snapshot rows are not sorted: {path}")


def _validate_relations(
    relation_files: dict[str, list[Path]],
    profile: RuntimeResourceProfile | None,
    active_files: dict[str, list[Path]] | None = None,
) -> None:
    views = active_files or relation_files
    con = connect(profile)
    try:
        for name, schema in _RELATIONS.items():
            _create_view(con, name, views[name], schema, _RELATION_PKS[name])
        checks = (
            (
                "duplicate accession keys",
                "SELECT count(*) FROM (SELECT accession FROM accessions GROUP BY accession HAVING count(*) > 1)",
            ),
            (
                "duplicate entry ids",
                "SELECT count(*) FROM (SELECT entry_id FROM entries GROUP BY entry_id HAVING count(*) > 1)",
            ),
            (
                "duplicate source edges",
                "SELECT count(*) FROM (SELECT accession, source_cik FROM accession_sources GROUP BY accession, source_cik HAVING count(*) > 1)",
            ),
            (
                "orphan entries",
                "SELECT count(*) FROM entries e ANTI JOIN accessions a USING(accession)",
            ),
            (
                "orphan source edges",
                "SELECT count(*) FROM accession_sources s ANTI JOIN accessions a USING(accession)",
            ),
            (
                "invalid accession rows",
                "SELECT count(*) FROM accessions WHERE accession IS NULL OR NOT regexp_full_match(accession, '[0-9]{10}-[0-9]{2}-[0-9]{6}') OR filing_cik IS NULL OR filing_cik != substr(accession, 1, 10) OR NOT regexp_full_match(filing_cik, '[0-9]{10}') OR form IS NULL OR form = '' OR try_cast(filing_date AS DATE) IS NULL OR (report_date IS NOT NULL AND try_cast(report_date AS DATE) IS NULL) OR index_url IS NULL OR index_url = '' OR index_sha256 IS NULL OR NOT regexp_full_match(index_sha256, '[0-9a-f]{64}') OR (bundle_size IS NOT NULL AND bundle_size < 0) OR first_indexed_by IS NULL OR first_indexed_by = ''",
            ),
            (
                "invalid entry rows",
                "SELECT count(*) FROM entries WHERE entry_id IS NULL OR entry_id = '' OR accession IS NULL OR table_kind NOT IN ('document_format', 'data_file') OR row_ordinal < 0 OR (byte_size IS NOT NULL AND byte_size < 0)",
            ),
            (
                "invalid source rows",
                "SELECT count(*) FROM accession_sources WHERE accession IS NULL OR source_cik IS NULL OR NOT regexp_full_match(source_cik, '[0-9]{10}') OR first_seen_by IS NULL OR first_seen_by = ''",
            ),
        )
        for label, query in checks:
            if _count(con, query):
                raise ValidationFailedError(label)
        for path in relation_files["accessions"]:
            _validate_sorted(con, path, ["form", "filing_date", "accession"])
        for path in relation_files["accession_sources"]:
            _validate_sorted(con, path, ["source_cik", "accession"])
        for path in relation_files["entries"]:
            source = sql_path_list([str(path)])
            ordering = (
                "SELECT count(*) FROM (SELECT form, filing_date, accession, row_ordinal, "
                "table_kind, entry_id, lag(form) OVER (ORDER BY file_row_number) AS p_form, "
                "lag(filing_date) OVER (ORDER BY file_row_number) AS p_date, "
                "lag(accession) OVER (ORDER BY file_row_number) AS p_accession, "
                "lag(row_ordinal) OVER (ORDER BY file_row_number) AS p_ordinal, "
                "lag(table_kind) OVER (ORDER BY file_row_number) AS p_kind, "
                "lag(entry_id) OVER (ORDER BY file_row_number) AS p_id FROM "
                f"read_parquet({source}, file_row_number=true, hive_partitioning=false) e "
                "JOIN accessions a USING(accession)) WHERE (p_form, p_date, p_accession, "
                "p_ordinal, p_kind, p_id) >= (form, filing_date, accession, row_ordinal, "
                "table_kind, entry_id) AND p_form IS NOT NULL"
            )
            if _count(con, ordering):
                raise ValidationFailedError(f"entry part rows are not sorted: {path}")
    finally:
        con.close()


def validate_snapshot(
    paths: InventoryPaths,
    snapshot_id: str,
    *,
    manifest_path: Path | None = None,
    staged_root: Path | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> SnapshotMetadata:
    """Validate every declared part, digest, and relation invariant."""
    path = manifest_path or paths.snapshot_manifest_path(snapshot_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailedError("snapshot manifest is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("snapshot_id") != snapshot_id:
        raise ValidationFailedError("snapshot manifest identity mismatch")
    schema_ver = payload.get("schema_version") or payload.get(
        "schema_versions", {}
    ).get("accessions")
    if schema_ver != SNAPSHOT_RELATION_VERSION:
        raise ValidationFailedError("snapshot relation version mismatch")
    raw_entry_ver = payload.get("entry_schema_version") or payload.get(
        "schema_versions", {}
    ).get("entries")
    if int(raw_entry_ver or 0) != ENTRY_SCHEMA_VERSION:
        raise ValidationFailedError("snapshot entry schema version mismatch")

    local_files: set[Path] = set()
    relation_files = {
        name: _part_files(
            paths,
            snapshot_id,
            payload.get(name) or payload.get("relations", {}).get(name),
            name,
            schema,
            staged_root=staged_root,
            local_files=local_files,
        )
        for name, schema in _RELATIONS.items()
    }
    local_root = staged_root or paths.snapshot_root(snapshot_id)
    observed = {p.resolve() for p in local_root.rglob("*.parquet")}
    if observed != local_files:
        raise ValidationFailedError(
            "snapshot contains undeclared or missing Parquet artifacts"
        )
    active_files = dict(relation_files)
    parents = payload.get("parents")
    parent_id = None
    if parents and isinstance(parents, list) and len(parents) > 0:
        first_parent = parents[0]
        parent_id = (
            first_parent.get("snapshot_id")
            if isinstance(first_parent, dict)
            else getattr(first_parent, "snapshot_id", None)
        )
    elif payload.get("parent_snapshot_id"):
        parent_id = payload["parent_snapshot_id"]

    if parent_id and paths.snapshot_manifest_path(parent_id).is_file():
        parent_lineage = walk_lineage(paths.snapshots_root, parent_id)
        for name in _RELATIONS:
            ancestor_files = []
            for node in parent_lineage.nodes:
                for part in node.relations.get(name, ()):
                    p = _resolve_part_path(
                        paths.snapshots_root, node.snapshot_id, part.path
                    )
                    if p.is_file():
                        ancestor_files.append(p)
            active_files[name] = ancestor_files + relation_files[name]

    _validate_relations(relation_files, profile, active_files=active_files)
    return SnapshotMetadata.from_manifest(payload)


__all__ = ["validate_snapshot"]
