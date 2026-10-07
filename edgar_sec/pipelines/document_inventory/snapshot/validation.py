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
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.errors import (
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.models import SnapshotMetadata
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    LOOKUP_LAYOUT_VERSION,
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_RELATION_VERSION,
    SNAPSHOT_LOOKUP_SCHEMA,
)
from edgar_sec.domain.document_inventory.schemas import (
    ENTRY_SCHEMA,
    ENTRY_SCHEMA_VERSION,
)

_RELATIONS = {
    "accessions": SNAPSHOT_ACCESSIONS_SCHEMA,
    "entries": ENTRY_SCHEMA,
    "accession_sources": SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
}
_LOOKUPS = ("accession", "filing_cik", "source_cik")
_SHARDS = tuple(f"{number:x}" for number in range(16))


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
        if (
            len(relative.parts) != 4
            or relative.parts[1] != relation
            or not re.fullmatch(r"year=\d{4}", relative.parts[2])
            or not re.fullmatch(r"part-\d{5}\.parquet", relative.parts[3])
            or relative.parts[2][5:] in years
        ):
            raise ValidationFailedError(
                f"snapshot partition path is invalid: {record['path']!r}"
            )
        years.add(relative.parts[2][5:])
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
        key_column = {
            "accessions": "accession",
            "entries": "accession",
            "accession_sources": "source_cik",
        }[relation]
        key_min = key_max = None
        for batch in parquet.iter_batches(batch_size=4096, columns=[key_column]):
            for value in batch.column(0).to_pylist():
                if value is None:
                    continue
                value = str(value)
                key_min = value if key_min is None else min(key_min, value)
                key_max = value if key_max is None else max(key_max, value)
        if (key_min, key_max) != (record.get("key_min"), record.get("key_max")):
            raise ValidationFailedError(f"snapshot part key range mismatch: {path}")
        if relation == "accessions":
            for batch in parquet.iter_batches(batch_size=4096, columns=["filing_date"]):
                if any(
                    value is None or value[:4] != relative.parts[2][5:]
                    for value in batch.column(0).to_pylist()
                ):
                    raise ValidationFailedError(
                        f"accession year partition mismatch: {path}"
                    )
        if Path(record["path"]).parts[0] == snapshot_id:
            local_files.add(path)
        result.append(path)
    return result


def _create_view(con, name: str, files: list[Path], schema: pa.Schema) -> None:
    if files:
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS SELECT * FROM "
            f"read_parquet({sql_path_list([str(p) for p in files])}, hive_partitioning=false)"
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


def _validate_sorted(path: Path, columns: list[str]) -> None:
    parquet = pq.ParquetFile(path)
    previous = None
    for batch in parquet.iter_batches(batch_size=4096, columns=columns):
        for values in zip(
            *(batch.column(index).to_pylist() for index in range(len(columns)))
        ):
            key = tuple(values)
            if previous is not None and key <= previous:
                raise ValidationFailedError(f"snapshot rows are not sorted: {path}")
            previous = key


def _validate_relations(
    relation_files: dict[str, list[Path]],
    lookup_files: dict[str, list[Path]],
    profile: RuntimeResourceProfile | None,
) -> None:
    con = connect(profile)
    try:
        for name, schema in _RELATIONS.items():
            _create_view(con, name, relation_files[name], schema)
        for name in _LOOKUPS:
            _create_view(
                con, f"{name}_lookup", lookup_files[name], SNAPSHOT_LOOKUP_SCHEMA
            )
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
            _validate_sorted(path, ["form", "filing_date", "accession"])
        for path in relation_files["accession_sources"]:
            _validate_sorted(path, ["source_cik", "accession"])
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
        parity = (
            (
                "accession",
                "SELECT accession AS lookup_value, accession, substr(filing_date, 1, 4) AS filing_year FROM accessions",
            ),
            (
                "filing_cik",
                "SELECT filing_cik AS lookup_value, accession, substr(filing_date, 1, 4) AS filing_year FROM accessions",
            ),
            (
                "source_cik",
                "SELECT s.source_cik AS lookup_value, s.accession, substr(a.filing_date, 1, 4) AS filing_year FROM accession_sources s JOIN accessions a USING(accession)",
            ),
        )
        for name, expected_query in parity:
            actual = f"{name}_lookup"
            actual_query = f"SELECT lookup_value, accession, filing_year FROM {sql_identifier(actual)}"
            if _count(
                con,
                f"SELECT count(*) FROM (({expected_query}) EXCEPT ALL ({actual_query}))",
            ) or _count(
                con,
                f"SELECT count(*) FROM (({actual_query}) EXCEPT ALL ({expected_query}))",
            ):
                raise ValidationFailedError(f"{name} lookup parity failed")
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
    """Validate every declared part, lookup, digest, and relation invariant."""
    path = manifest_path or paths.snapshot_manifest_path(snapshot_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailedError("snapshot manifest is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("snapshot_id") != snapshot_id:
        raise ValidationFailedError("snapshot manifest identity mismatch")
    if payload.get("schema_version") != SNAPSHOT_RELATION_VERSION:
        raise ValidationFailedError("snapshot relation version mismatch")
    if payload.get("entry_schema_version") != ENTRY_SCHEMA_VERSION:
        raise ValidationFailedError("snapshot entry schema version mismatch")
    if payload.get("lookup_layout_version") != LOOKUP_LAYOUT_VERSION:
        raise ValidationFailedError("snapshot lookup version mismatch")

    local_files: set[Path] = set()
    relation_files = {
        name: _part_files(
            paths,
            snapshot_id,
            payload.get(name),
            name,
            schema,
            staged_root=staged_root,
            local_files=local_files,
        )
        for name, schema in _RELATIONS.items()
    }
    lookups_payload = payload.get("lookups")
    if not isinstance(lookups_payload, dict):
        raise ValidationFailedError("snapshot lookup descriptors are missing")
    lookup_files: dict[str, list[Path]] = {}
    for name in _LOOKUPS:
        records = lookups_payload.get(name)
        if not isinstance(records, list) or len(records) != len(_SHARDS):
            raise ValidationFailedError(f"{name} lookup shard set is incomplete")
        by_key = {
            record.get("shard_key"): record
            for record in records
            if isinstance(record, dict)
        }
        if set(by_key) != set(_SHARDS):
            raise ValidationFailedError(f"{name} lookup shard keys are invalid")
        lookup_files[name] = []
        for key in _SHARDS:
            record = by_key[key]
            path = _artifact_path(
                paths, snapshot_id, record.get("part_path"), staged_root=staged_root
            )
            if not path.is_file():
                raise ValidationFailedError(f"lookup part is missing: {path}")
            relative = Path(record.get("part_path", ""))
            expected_suffix = ("lookups", name, f"shard={key}", "part-00000.parquet")
            if len(relative.parts) != 5 or relative.parts[1:] != expected_suffix:
                raise ValidationFailedError(f"lookup part path is invalid: {relative}")
            if record.get("lookup") != name or record.get("shard_key") != key:
                raise ValidationFailedError(
                    f"lookup descriptor identity is invalid: {relative}"
                )
            parquet = _validate_parquet(
                path,
                SNAPSHOT_LOOKUP_SCHEMA,
                record.get("row_count"),
                record.get("sha256"),
                None,
            )
            if (
                not isinstance(record.get("byte_size"), int)
                or isinstance(record.get("byte_size"), bool)
                or path.stat().st_size != record.get("byte_size")
            ):
                raise ValidationFailedError(f"lookup part size mismatch: {path}")
            if record.get("row_count") and parquet.metadata.num_row_groups < 1:
                raise ValidationFailedError(f"lookup part has no row groups: {path}")
            key_min = key_max = None
            previous = None
            for batch in parquet.iter_batches(batch_size=4096):
                for row in batch.to_pylist():
                    value = row["lookup_value"]
                    pair = (value, row["accession"])
                    if (
                        value is None
                        or row["accession"] is None
                        or row["filing_year"] is None
                    ):
                        raise ValidationFailedError(f"lookup row is incomplete: {path}")
                    if previous is not None and pair < previous:
                        raise ValidationFailedError(
                            f"lookup rows are not sorted: {path}"
                        )
                    previous = pair
                    if hashlib.sha256(value.encode("utf-8")).hexdigest()[0] != key:
                        raise ValidationFailedError(
                            f"lookup row is in the wrong shard: {path}"
                        )
                    key_min = value if key_min is None else min(key_min, value)
                    key_max = value if key_max is None else max(key_max, value)
            if (key_min, key_max) != (record.get("key_min"), record.get("key_max")):
                raise ValidationFailedError(f"lookup key range mismatch: {path}")
            if Path(record["part_path"]).parts[0] == snapshot_id:
                local_files.add(path)
            lookup_files[name].append(path)
    local_root = staged_root or paths.snapshot_root(snapshot_id)
    observed = {p.resolve() for p in local_root.rglob("*.parquet")}
    if observed != local_files:
        raise ValidationFailedError(
            "snapshot contains undeclared or missing Parquet artifacts"
        )
    _validate_relations(relation_files, lookup_files, profile)
    return SnapshotMetadata.from_manifest(payload)


__all__ = ["validate_snapshot"]
