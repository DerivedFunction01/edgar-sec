"""Bounded merge and pointer-last publication of validated S4 attempts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.schemas import (
    ENTRY_SCHEMA,
    ENTRY_SCHEMA_VERSION,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import _fsync_dir, atomic_write_json
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_identifier,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_inventory.checkpoint import (
    OUTCOME_SCHEMA,
    AttemptValidationError,
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    InventoryRunPaths,
    snapshot_id_for,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    InventoryRunManifest,
    iter_work_order_chunks,
    read_run_manifest,
    validate_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.errors import (
    StaleParentError,
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.anti_join import (
    StagingRelations,
    anti_join,
)
from edgar_sec.pipelines.document_inventory.snapshot.models import SnapshotPublication
from edgar_sec.pipelines.document_inventory.snapshot.publication_lock import (
    PublicationLock,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    LOOKUP_LAYOUT_VERSION,
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.document_inventory.snapshot.validation import validate_snapshot

__all__ = ["publish_committed_chunks"]

_BATCH_ROWS = 4096
_COHORT_ACCESSIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("index_url", pa.string()),
    ]
)
_RELATION_SCHEMAS = {
    "accessions": SNAPSHOT_ACCESSIONS_SCHEMA,
    "entries": ENTRY_SCHEMA,
    "accession_sources": SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
}
_RELATION_KEYS = {
    "accessions": "accession",
    "entries": "accession",
    "accession_sources": "source_cik",
}


def _validate_input(path: Path, schema: pa.Schema, label: str) -> int:
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException, pq.ParquetException) as exc:
        raise ValidationFailedError(f"{label} is unreadable Parquet") from exc
    actual = parquet.schema_arrow
    if actual.names != schema.names or any(
        actual.field(name).type != field.type
        for name, field in zip(schema.names, schema, strict=True)
    ):
        raise ValidationFailedError(f"{label} schema mismatch")
    return int(parquet.metadata.num_rows)


def _copy_committed_attempts(
    run_paths: InventoryRunPaths,
    run: InventoryRunManifest,
    publication_dir: Path,
) -> tuple[Path, Path, int, int]:
    identity = validate_work_order(run_paths.work_order_path())
    if (
        identity.digest != run.work_order_digest
        or identity.row_count != run.work_order_rows
    ):
        raise ValidationFailedError(
            "work order does not match the pinned S4 run manifest"
        )
    outcomes_path = publication_dir / "committed_outcomes.parquet"
    entries_path = publication_dir / "committed_entries.parquet"
    outcome_writer = StagedParquetWriter(outcomes_path, OUTCOME_SCHEMA)
    entry_writer = StagedParquetWriter(entries_path, ENTRY_SCHEMA)
    outcome_count = entry_count = chunk_count = 0
    try:
        for chunk, _members in iter_work_order_chunks(
            run_paths.work_order_path(),
            chunk_size=run.chunk_size,
            work_order_version=run.work_order_version,
        ):
            checked = validate_committed_chunk(
                run_paths, chunk.chunk_id, run=run, chunk=chunk
            )
            if not checked.valid or checked.attempt_id is None:
                raise AttemptValidationError(
                    f"committed chunk {chunk.chunk_id} is invalid: {checked.reason}"
                )
            attempt_dir = run_paths.attempt_dir(chunk.chunk_id, checked.attempt_id)
            for source, writer in (
                (attempt_dir / "outcomes.parquet", outcome_writer),
                (attempt_dir / "entries.parquet", entry_writer),
            ):
                parquet = pq.ParquetFile(source)
                for batch in parquet.iter_batches(batch_size=_BATCH_ROWS):
                    writer.write_batch(batch)
            outcome_count += checked.manifest.outcomes_rows
            entry_count += checked.manifest.entries_rows
            chunk_count += 1
            if chunk_count % 16 == 0:
                reclaim()
        outcome_writer.commit(expected_count=outcome_count)
        entry_writer.commit(expected_count=entry_count)
        final_identity = validate_work_order(run_paths.work_order_path())
        if final_identity != identity:
            raise ValidationFailedError(
                "work order changed while reading committed chunks"
            )
    except BaseException:
        outcome_writer.reset()
        entry_writer.reset()
        raise
    return outcomes_path, entries_path, outcome_count, entry_count


def _write_part_descriptor(
    path: Path,
    relative_path: str,
    schema: pa.Schema,
    key_column: str,
) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    key_min = key_max = None
    for batch in parquet.iter_batches(batch_size=_BATCH_ROWS, columns=[key_column]):
        for value in batch.column(0).to_pylist():
            if value is None:
                continue
            value = str(value)
            key_min = value if key_min is None else min(key_min, value)
            key_max = value if key_max is None else max(key_max, value)
    if key_min is None or key_max is None:
        raise ValidationFailedError(f"snapshot part has no key values: {path}")
    if pq.ParquetFile(path).schema_arrow.names != schema.names:
        raise ValidationFailedError(f"snapshot part schema mismatch: {path}")
    return {
        "path": relative_path,
        "row_count": parquet.metadata.num_rows,
        "key_min": key_min,
        "key_max": key_max,
        "byte_size": path.stat().st_size,
        "sha256": file_sha256(path),
        "row_group_count": parquet.metadata.num_row_groups,
    }


def _key_range(path: Path, key_column: str) -> tuple[str | None, str | None]:
    key_min = key_max = None
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=_BATCH_ROWS, columns=[key_column]):
        for value in batch.column(0).to_pylist():
            if value is None:
                continue
            text = str(value)
            key_min = text if key_min is None else min(key_min, text)
            key_max = text if key_max is None else max(key_max, text)
    return key_min, key_max


def _relation_files(paths: InventoryPaths, records: list[dict[str, Any]]) -> list[Path]:
    result = []
    for record in records:
        relative = Path(record["path"])
        owner = relative.parts[0]
        resolved = (paths.snapshots_root / relative).resolve()
        resolved.relative_to(paths.snapshot_root(owner).resolve())
        result.append(resolved)
    return result


def _view(con, name: str, files: list[Path], schema: pa.Schema) -> None:
    if files:
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS SELECT * FROM "
            f"read_parquet({sql_path_list([str(path) for path in files])}, hive_partitioning=false)"
        )
    else:
        empty_name = f"empty_{name}"
        con.register(empty_name, pa.Table.from_batches([], schema=schema))
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS "
            f"SELECT * FROM {sql_identifier(empty_name)}"
        )


def _create_merge_relations(
    con,
    parent_manifest: dict[str, Any] | None,
    paths: InventoryPaths,
    cohort_accessions: Path,
    cohort_sources: Path,
    staged_outcomes: Path,
    staged_entries: Path,
    eligible_outcomes: list[Path],
    candidate_entries: Path,
    new_sources: Path,
    source_identity: str,
    refresh: bool,
) -> None:
    for name, schema in _RELATION_SCHEMAS.items():
        records = parent_manifest.get(name, []) if parent_manifest else []
        files = _relation_files(paths, records)
        _view(con, f"parent_{name}", files, schema)
    _view(
        con,
        "cohort_accessions",
        [cohort_accessions],
        _COHORT_ACCESSIONS_SCHEMA,
    )
    _view(
        con,
        "cohort_sources",
        [cohort_sources],
        SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    )
    _view(con, "staged_outcomes", [staged_outcomes], OUTCOME_SCHEMA)
    _view(con, "staged_entries", [staged_entries], ENTRY_SCHEMA)
    _view(con, "eligible_outcomes", eligible_outcomes, OUTCOME_SCHEMA)
    _view(con, "candidate_entries", [candidate_entries], ENTRY_SCHEMA)
    _view(
        con,
        "new_sources",
        [new_sources],
        SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    )

    con.execute(
        "CREATE TEMP TABLE invalid_outcomes AS SELECT accession, status FROM staged_outcomes "
        "WHERE status IS NULL OR status NOT IN (?, ?)",
        ["parsed", "parsed_empty"],
    )
    if con.execute("SELECT count(*) FROM invalid_outcomes").fetchone()[0]:
        status = con.execute("SELECT status FROM invalid_outcomes LIMIT 1").fetchone()[
            0
        ]
        raise ValidationFailedError(
            f"S4 refusal outcome blocks publication: {status!r}"
        )
    if con.execute(
        "SELECT count(*) FROM staged_outcomes o ANTI JOIN cohort_accessions c USING(accession)"
    ).fetchone()[0]:
        raise ValidationFailedError(
            "an S4 outcome is absent from the cohort projection"
        )
    if con.execute(
        "SELECT count(*) FROM staged_outcomes o JOIN cohort_accessions c USING(accession) "
        "WHERE o.index_url IS DISTINCT FROM c.index_url"
    ).fetchone()[0]:
        raise ValidationFailedError(
            "S4 outcome URL differs from its projected accession"
        )
    if con.execute(
        "SELECT count(*) FROM (SELECT accession FROM cohort_accessions GROUP BY accession "
        "HAVING count(*) > 1)"
    ).fetchone()[0]:
        raise ValidationFailedError(
            "cohort accession projection contains duplicate accessions"
        )
    if con.execute(
        "SELECT count(*) FROM (SELECT accession, source_cik FROM cohort_sources "
        "GROUP BY accession, source_cik HAVING count(*) > 1)"
    ).fetchone()[0]:
        raise ValidationFailedError("cohort source projection contains duplicate edges")
    if con.execute(
        "SELECT count(*) FROM (SELECT o.accession FROM staged_outcomes o "
        "LEFT JOIN staged_entries e USING(accession) GROUP BY o.accession, o.entry_count "
        "HAVING o.entry_count IS NULL OR o.entry_count != count(e.entry_id))"
    ).fetchone()[0]:
        raise ValidationFailedError(
            "S4 outcome entry count differs from its entry rows"
        )

    metadata_conflicts = con.execute(
        "SELECT count(*) FROM cohort_accessions c JOIN parent_accessions p USING(accession) "
        "WHERE c.form IS DISTINCT FROM p.form OR c.filing_date IS DISTINCT FROM p.filing_date "
        "OR c.report_date IS DISTINCT FROM p.report_date"
    ).fetchone()[0]
    if metadata_conflicts:
        raise ValidationFailedError(
            "cohort metadata conflicts with the current snapshot"
        )
    if con.execute(
        "SELECT count(*) FROM cohort_sources s LEFT JOIN parent_accessions p USING(accession) "
        "LEFT JOIN staged_outcomes o USING(accession) WHERE p.accession IS NULL AND o.accession IS NULL"
    ).fetchone()[0]:
        raise ValidationFailedError("cohort source edge has no accession facts")

    if refresh:
        con.execute(
            "CREATE TEMP TABLE delta_accessions AS SELECT c.accession, c.filing_cik, c.form, "
            "c.filing_date, c.report_date, o.bundle_url, o.bundle_size, c.index_url, "
            "o.page_sha256 AS index_sha256, coalesce(p.first_indexed_by, ?) AS first_indexed_by "
            "FROM cohort_accessions c JOIN eligible_outcomes o USING(accession) "
            "LEFT JOIN parent_accessions p USING(accession) WHERE o.status IN (?, ?) "
            "AND (p.accession IS NULL OR p.index_sha256 IS DISTINCT FROM o.page_sha256)",
            [source_identity, "parsed", "parsed_empty"],
        )
    else:
        con.execute(
            "CREATE TEMP TABLE delta_accessions AS SELECT c.accession, c.filing_cik, c.form, "
            "c.filing_date, c.report_date, o.bundle_url, o.bundle_size, c.index_url, "
            "o.page_sha256 AS index_sha256, coalesce(p.first_indexed_by, ?) AS first_indexed_by "
            "FROM cohort_accessions c JOIN eligible_outcomes o USING(accession) "
            "LEFT JOIN parent_accessions p USING(accession) WHERE o.status IN (?, ?)",
            [source_identity, "parsed", "parsed_empty"],
        )
    con.execute(
        "CREATE TEMP TABLE delta_entries AS SELECT e.* FROM candidate_entries e "
        "JOIN delta_accessions d USING(accession)"
    )
    con.execute(
        "CREATE TEMP TABLE delta_sources AS SELECT accession, source_cik, first_seen_by "
        "FROM new_sources"
    )
    con.execute(
        "CREATE TEMP VIEW all_accessions AS SELECT accession, filing_cik, form, filing_date, "
        "report_date, bundle_url, bundle_size, index_url, index_sha256, first_indexed_by "
        "FROM parent_accessions p "
        "WHERE NOT EXISTS (SELECT 1 FROM delta_accessions d WHERE d.accession=p.accession) "
        "UNION ALL SELECT accession, filing_cik, form, filing_date, report_date, bundle_url, "
        "bundle_size, index_url, index_sha256, first_indexed_by FROM delta_accessions"
    )
    if refresh:
        con.execute(
            "CREATE TEMP VIEW all_entries AS SELECT entry_id, accession, table_kind, row_ordinal, "
            "sequence, document_type, document_label, description, filename, href, archive_url, byte_size "
            "FROM parent_entries p WHERE NOT EXISTS (SELECT 1 FROM delta_accessions d "
            "WHERE d.accession=p.accession) UNION ALL SELECT * FROM delta_entries"
        )
    else:
        con.execute(
            "CREATE TEMP VIEW all_entries AS SELECT entry_id, accession, table_kind, row_ordinal, "
            "sequence, document_type, document_label, description, filename, href, archive_url, byte_size "
            "FROM parent_entries UNION ALL SELECT * FROM delta_entries"
        )
    con.execute(
        "CREATE TEMP VIEW all_accession_sources AS SELECT accession, source_cik, first_seen_by "
        "FROM parent_accession_sources UNION ALL SELECT accession, source_cik, first_seen_by "
        "FROM delta_sources"
    )
    con.execute(
        "CREATE TEMP VIEW accessions_by_year AS SELECT *, substr(filing_date, 1, 4) AS _year "
        "FROM all_accessions"
    )
    con.execute(
        "CREATE TEMP VIEW entries_by_year AS SELECT e.*, a.form, a.filing_date, "
        "substr(a.filing_date, 1, 4) AS _year FROM all_entries e JOIN all_accessions a USING(accession)"
    )
    con.execute(
        "CREATE TEMP VIEW sources_by_year AS SELECT s.*, substr(a.filing_date, 1, 4) AS _year "
        "FROM all_accession_sources s JOIN all_accessions a USING(accession)"
    )
    con.execute(
        "CREATE TEMP VIEW lookup_accession_all AS SELECT accession AS lookup_value, accession, _year AS filing_year "
        "FROM accessions_by_year"
    )
    con.execute(
        "CREATE TEMP VIEW lookup_filing_cik_all AS SELECT filing_cik AS lookup_value, accession, _year AS filing_year "
        "FROM accessions_by_year"
    )
    con.execute(
        "CREATE TEMP VIEW lookup_source_cik_all AS SELECT source_cik AS lookup_value, accession, _year AS filing_year "
        "FROM sources_by_year"
    )


def _years(con, query: str) -> set[str]:
    return {str(row[0]) for row in con.execute(query).fetchall()}


def _part_year(record: dict[str, Any]) -> str:
    for component in Path(record["path"]).parts:
        if component.startswith("year="):
            return component[5:]
    raise ValidationFailedError("snapshot partition path has no year")


def _write_annual_parts(
    con,
    paths: InventoryPaths,
    snapshot_id: str,
    stage_root: Path,
    relation: str,
    query: str,
    changed_years: set[str],
    inherited: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retained = [
        record for record in inherited if _part_year(record) not in changed_years
    ]
    schema = _RELATION_SCHEMAS[relation]
    result = list(retained)
    for year in sorted(changed_years):
        final = paths.snapshot_part_path(snapshot_id, relation, year)
        staged = stage_root / relation / f"year={year}" / final.name
        copy_query_to_parquet(con, query, staged, params=[year])
        if pq.ParquetFile(staged).metadata.num_rows == 0:
            staged.unlink()
            continue
        relative = f"{snapshot_id}/{relation}/year={year}/{final.name}"
        result.append(
            _write_part_descriptor(staged, relative, schema, _RELATION_KEYS[relation])
        )
    return sorted(result, key=lambda record: (_part_year(record), record["path"]))


def _write_lookup_shards(
    con, paths: InventoryPaths, snapshot_id: str, stage_root: Path
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for lookup in ("accession", "filing_cik", "source_cik"):
        records = []
        for shard in range(16):
            key = f"{shard:x}"
            final = paths.snapshot_lookup_path(snapshot_id, lookup, key)
            staged = stage_root / "lookups" / lookup / f"shard={key}" / final.name
            query = (
                f"SELECT lookup_value, accession, filing_year FROM lookup_{lookup}_all "
                "WHERE substr(sha256(lookup_value), 1, 1) = ? ORDER BY lookup_value, accession"
            )
            count = copy_query_to_parquet(con, query, staged, params=[key])
            key_min, key_max = _key_range(staged, "lookup_value")
            relative = f"{snapshot_id}/lookups/{lookup}/shard={key}/{final.name}"
            records.append(
                {
                    "lookup": lookup,
                    "shard_key": key,
                    "part_path": relative,
                    "row_count": count,
                    "sha256": file_sha256(staged),
                    "byte_size": staged.stat().st_size,
                    "key_min": key_min,
                    "key_max": key_max,
                }
            )
        result[lookup] = records
    return result


def _read_pointer(paths: InventoryPaths) -> str | None:
    pointer_path = paths.current_snapshot_pointer()
    if not pointer_path.exists():
        return None
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailedError("current snapshot pointer is unreadable") from exc
    snapshot_id = payload.get("snapshot_id") if isinstance(payload, dict) else None
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValidationFailedError("current snapshot pointer has no snapshot id")
    manifest_digest = payload.get("manifest_sha256")
    manifest = paths.snapshot_manifest_path(snapshot_id)
    if not isinstance(manifest_digest, str) or not manifest.is_file():
        raise ValidationFailedError(
            "current snapshot pointer has no valid manifest digest"
        )
    if file_sha256(manifest) != manifest_digest:
        raise ValidationFailedError(
            "current snapshot manifest digest differs from pointer"
        )
    return snapshot_id


def _make_parent_input_dirs(
    stage_parent: Path,
    inventory_paths: InventoryPaths,
    parent_manifest: dict[str, Any] | None,
) -> tuple[Path | None, Path | None]:
    if parent_manifest is None:
        return None, None
    roots = []
    for relation in ("accessions", "accession_sources"):
        root = stage_parent / "parent-input" / relation
        root.mkdir(parents=True)
        for index, source in enumerate(
            _relation_files(inventory_paths, parent_manifest.get(relation, []))
        ):
            os.symlink(source, root / f"part-{index:05d}.parquet")
        roots.append(root if any(root.iterdir()) else None)
    return roots[0], roots[1]


def _sync_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        _fsync_dir(str(directory))
    _fsync_dir(str(root))


def _install_snapshot(
    paths: InventoryPaths, snapshot_id: str, staged_root: Path, profile
) -> Path:
    destination = paths.snapshot_root(snapshot_id)
    if destination.exists():
        validate_snapshot(paths, snapshot_id, profile=profile)
        return destination
    installation = paths.snapshots_root / f".install-{snapshot_id}-{uuid.uuid4().hex}"
    try:
        shutil.copytree(staged_root, installation)
        _sync_tree(installation)
        os.replace(installation, destination)
        _fsync_dir(str(paths.snapshots_root))
    finally:
        if installation.exists():
            shutil.rmtree(installation)
    return destination


def publish_committed_chunks(
    run_paths: InventoryRunPaths,
    run: InventoryRunManifest,
    *,
    cohort_accessions_path: Path | str,
    cohort_sources_path: Path | str,
    expected_parent_snapshot_id: str | None,
    profile: RuntimeResourceProfile | None = None,
) -> SnapshotPublication:
    """Merge a run's complete validated S4 attempts into an immutable snapshot."""
    if run.run_id != run_paths.run_id:
        raise ValidationFailedError("S4 run manifest identity differs from its paths")
    if read_run_manifest(run_paths) != run:
        raise ValidationFailedError(
            "S4 run manifest differs from its persisted identity"
        )
    if run.parent_snapshot_id != (expected_parent_snapshot_id or ""):
        raise ValidationFailedError("expected parent differs from the pinned S4 run")
    cohort_accessions = Path(cohort_accessions_path).resolve()
    cohort_sources = Path(cohort_sources_path).resolve()
    _validate_input(cohort_accessions, _COHORT_ACCESSIONS_SCHEMA, "cohort accessions")
    _validate_input(cohort_sources, SNAPSHOT_ACCESSION_SOURCES_SCHEMA, "cohort sources")
    inventory_paths = InventoryPaths(run_paths.artifacts_root)
    current_id = _read_pointer(inventory_paths)
    if current_id != expected_parent_snapshot_id:
        raise StaleParentError(
            f"expected parent {expected_parent_snapshot_id!r}, current is {current_id!r}"
        )
    parent_manifest = None
    if current_id is not None:
        parent_metadata = validate_snapshot(
            inventory_paths, current_id, profile=profile
        )
        parent_manifest = json.loads(
            inventory_paths.snapshot_manifest_path(current_id).read_text(
                encoding="utf-8"
            )
        )
        if parent_metadata.snapshot_id != expected_parent_snapshot_id:
            raise ValidationFailedError("current parent snapshot identity mismatch")

    publication_dir = run_paths.publication_dir()
    publication_dir.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix=".stage-", dir=publication_dir))
    try:
        staged_outcomes, staged_entries, outcome_count, entry_count = (
            _copy_committed_attempts(run_paths, run, stage_parent)
        )
        parent_accessions_dir, parent_sources_dir = _make_parent_input_dirs(
            stage_parent, inventory_paths, parent_manifest
        )
        try:
            anti_join_result = anti_join(
                StagingRelations(staged_outcomes, staged_entries, cohort_sources),
                parent_accessions_dir,
                parent_sources_dir,
                stage_parent / "anti-join",
                explicit_refresh=run.refresh_mode == "force",
                profile=profile,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        eligible_outcomes = [anti_join_result.new_accessions_path]
        if run.refresh_mode == "force":
            eligible_outcomes.append(anti_join_result.known_accessions_path)
        content_digest = canonical_hash(
            {
                "parent": expected_parent_snapshot_id,
                "outcomes": file_sha256(staged_outcomes),
                "entries": file_sha256(staged_entries),
                "cohort_accessions": file_sha256(cohort_accessions),
                "cohort_sources": file_sha256(cohort_sources),
                "snapshot_schema": SNAPSHOT_RELATION_VERSION,
                "entry_schema": ENTRY_SCHEMA_VERSION,
                "lookup_layout": LOOKUP_LAYOUT_VERSION,
            }
        )
        snapshot_id = snapshot_id_for(expected_parent_snapshot_id, content_digest)
        staged_snapshot = stage_parent / snapshot_id
        connection = connect(profile)
        try:
            _create_merge_relations(
                connection,
                parent_manifest,
                inventory_paths,
                cohort_accessions,
                cohort_sources,
                staged_outcomes,
                staged_entries,
                eligible_outcomes,
                anti_join_result.candidate_entries_path,
                anti_join_result.new_sources_path,
                run.source_identity,
                run.refresh_mode == "force",
            )
            if (
                current_id is not None
                and not connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM delta_accessions) OR "
                    "EXISTS (SELECT 1 FROM delta_sources)"
                ).fetchone()[0]
            ):
                with PublicationLock(inventory_paths):
                    actual_parent = _read_pointer(inventory_paths)
                    if actual_parent != expected_parent_snapshot_id:
                        raise StaleParentError(
                            f"expected parent {expected_parent_snapshot_id!r}, "
                            f"current is {actual_parent!r}"
                        )
                    return SnapshotPublication.no_op(parent_metadata)
            delta_accession_years = _years(
                connection,
                "SELECT DISTINCT substr(filing_date, 1, 4) FROM delta_accessions",
            )
            delta_source_years = _years(
                connection,
                "SELECT DISTINCT substr(a.filing_date, 1, 4) FROM delta_sources s "
                "JOIN all_accessions a USING(accession)",
            )
            inherited = parent_manifest or {}
            accession_query = (
                "SELECT accession, filing_cik, form, filing_date, report_date, bundle_url, "
                "bundle_size, index_url, index_sha256, first_indexed_by FROM accessions_by_year "
                "WHERE _year = ? ORDER BY form, filing_date, accession"
            )
            entry_query = (
                "SELECT entry_id, accession, table_kind, row_ordinal, sequence, document_type, "
                "document_label, description, filename, href, archive_url, byte_size "
                "FROM entries_by_year WHERE _year = ? "
                "ORDER BY form, filing_date, accession, row_ordinal, table_kind, entry_id"
            )
            source_query = (
                "SELECT accession, source_cik, first_seen_by FROM sources_by_year "
                "WHERE _year = ? ORDER BY source_cik, accession"
            )
            relation_records = {
                "accessions": _write_annual_parts(
                    connection,
                    inventory_paths,
                    snapshot_id,
                    staged_snapshot,
                    "accessions",
                    accession_query,
                    delta_accession_years,
                    inherited.get("accessions", []),
                ),
                "entries": _write_annual_parts(
                    connection,
                    inventory_paths,
                    snapshot_id,
                    staged_snapshot,
                    "entries",
                    entry_query,
                    delta_accession_years,
                    inherited.get("entries", []),
                ),
                "accession_sources": _write_annual_parts(
                    connection,
                    inventory_paths,
                    snapshot_id,
                    staged_snapshot,
                    "accession_sources",
                    source_query,
                    delta_source_years,
                    inherited.get("accession_sources", []),
                ),
            }
            lookup_records = _write_lookup_shards(
                connection, inventory_paths, snapshot_id, staged_snapshot
            )
        finally:
            connection.close()

        accessions_digest = canonical_hash(
            [(part["path"], part["sha256"]) for part in relation_records["accessions"]]
        )
        manifest = {
            "snapshot_id": snapshot_id,
            "parent_snapshot_id": expected_parent_snapshot_id or "",
            "run_intent_id": run.run_id,
            "base_snapshot_id": expected_parent_snapshot_id,
            "schema_version": SNAPSHOT_RELATION_VERSION,
            "entry_schema_version": ENTRY_SCHEMA_VERSION,
            "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **relation_records,
            "lookups": lookup_records,
            "accessions_digest": accessions_digest,
            "input_rows": {"outcomes": outcome_count, "entries": entry_count},
        }
        staged_snapshot.mkdir(parents=True, exist_ok=True)
        manifest_path = staged_snapshot / "manifest.json"
        atomic_write_json(manifest_path, manifest, canonical=True)
        metadata = validate_snapshot(
            inventory_paths,
            snapshot_id,
            manifest_path=manifest_path,
            staged_root=staged_snapshot,
            profile=profile,
        )
        with PublicationLock(inventory_paths):
            actual_parent = _read_pointer(inventory_paths)
            if actual_parent != expected_parent_snapshot_id:
                raise StaleParentError(
                    f"expected parent {expected_parent_snapshot_id!r}, current is {actual_parent!r}"
                )
            installed = _install_snapshot(
                inventory_paths, snapshot_id, staged_snapshot, profile
            )
            validate_snapshot(inventory_paths, snapshot_id, profile=profile)
            atomic_write_json(
                inventory_paths.current_snapshot_pointer(),
                {
                    "snapshot_id": snapshot_id,
                    "manifest_sha256": file_sha256(installed / "manifest.json"),
                },
                canonical=True,
            )
        return SnapshotPublication.published(metadata)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)
