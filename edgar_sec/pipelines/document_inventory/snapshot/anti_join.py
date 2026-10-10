"""Disk-backed candidate staging and DuckDB accession anti-joins."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
)
from edgar_sec.infra.storage.parquet import (
    StagedParquetWriter,
)
from edgar_sec.pipelines.document_inventory.checkpoint import (
    OUTCOME_SCHEMA,
    STATUS_PARSED,
    STATUS_PARSED_EMPTY,
)
from edgar_sec.pipelines.document_inventory.paths import (
    KNOWN_ACCESSIONS_FILE,
    NEW_ACCESSIONS_FILE,
    CANDIDATE_ENTRIES_FILE,
    NEW_SOURCES_FILE,
    PUBLICATION_ENTRIES_FILE,
    PUBLICATION_OUTCOMES_FILE,
    PUBLICATION_SOURCES_FILE,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
)

__all__ = [
    "ANTI_JOIN_VERSION",
    "AntiJoinResult",
    "StagingRelations",
    "anti_join",
    "build_staging",
]

ANTI_JOIN_VERSION = "2"


@dataclass(frozen=True, slots=True)
class StagingRelations:
    outcomes_path: Path
    entries_path: Path
    sources_path: Path


@dataclass(frozen=True, slots=True)
class AntiJoinResult:
    new_accessions_path: Path
    known_accessions_path: Path
    candidate_entries_path: Path
    new_sources_path: Path
    new_accession_count: int
    known_accession_count: int
    candidate_entry_count: int
    new_source_count: int


def _write_rows(
    path: Path, rows: Iterable[dict], schema: pa.Schema, batch_rows: int
) -> None:
    writer = StagedParquetWriter(path, schema)
    columns = {name: [] for name in schema.names}
    count = 0
    try:
        for row in rows:
            for name in schema.names:
                columns[name].append(row.get(name))
            count += 1
            if len(columns[schema.names[0]]) >= batch_rows:
                writer.write_batch(columns)
                columns = {name: [] for name in schema.names}
        if columns[schema.names[0]]:
            writer.write_batch(columns)
        writer.commit(expected_count=count)
    except BaseException:
        writer.reset()
        raise


def build_staging(
    staging_dir: Path | str,
    *,
    outcome_rows: Iterable[dict],
    entry_rows: Iterable[dict],
    source_rows: Iterable[dict],
    batch_rows: int | None = None,
) -> StagingRelations:
    """Write worker and cohort rows incrementally to temporary Parquet files."""
    batch_rows = resolve_read_batch_size(batch_rows)
    if batch_rows < 1:
        raise ValueError("batch_rows must be positive")
    root = Path(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    outcomes = root / PUBLICATION_OUTCOMES_FILE
    entries = root / PUBLICATION_ENTRIES_FILE
    sources = root / PUBLICATION_SOURCES_FILE
    _write_rows(outcomes, outcome_rows, OUTCOME_SCHEMA, batch_rows)
    _write_rows(entries, entry_rows, ENTRY_SCHEMA, batch_rows)
    _write_rows(sources, source_rows, SNAPSHOT_ACCESSION_SOURCES_SCHEMA, batch_rows)
    return StagingRelations(outcomes, entries, sources)


def _parquet_source(path: Path | str | None) -> str | None:
    if path is None:
        return None
    value = Path(path).resolve()
    if value.is_dir():
        return str(value / "**" / "*.parquet")
    return str(value)


def _register_relation(
    con, name: str, path: Path | str | None, empty_query: str
) -> None:
    source = _parquet_source(path)
    if source is None and not empty_query:
        raise ValueError(f"missing staged relation: {name}")
    relation = con.read_parquet(source) if source else con.sql(empty_query)
    relation.create_view(name, replace=True)


def _copy(con, query: str, path: Path) -> int:
    return copy_query_to_parquet(con, query, path)


def anti_join(
    staged: StagingRelations,
    current_accessions: Path | str | None,
    current_sources: Path | str | None,
    output_dir: Path | str,
    *,
    explicit_refresh: bool = False,
    temp_directory: Path | str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> AntiJoinResult:
    """Classify candidates in DuckDB and persist bounded Parquet result relations."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "new": output / NEW_ACCESSIONS_FILE,
        "known": output / KNOWN_ACCESSIONS_FILE,
        "entries": output / CANDIDATE_ENTRIES_FILE,
        "sources": output / NEW_SOURCES_FILE,
    }
    if temp_directory is None:
        con = connect(profile)
    else:
        con = connect(profile, temp_directory=temp_directory)
    try:
        _register_relation(con, "staged_outcomes", staged.outcomes_path, "")
        _register_relation(con, "staged_entries", staged.entries_path, "")
        _register_relation(con, "staged_sources", staged.sources_path, "")
        _register_relation(
            con,
            "current_accessions",
            current_accessions,
            "SELECT NULL::VARCHAR AS accession WHERE false",
        )
        _register_relation(
            con,
            "current_sources",
            current_sources,
            "SELECT NULL::VARCHAR AS accession, NULL::VARCHAR AS source_cik WHERE false",
        )
        invalid = con.execute(
            "SELECT status FROM staged_outcomes "
            "WHERE status IS NULL OR status NOT IN (?, ?) LIMIT 1",
            [STATUS_PARSED, STATUS_PARSED_EMPTY],
        ).fetchone()
        if invalid is not None:
            raise ValueError(f"refusing snapshot outcome status {invalid[0]!r}")
        duplicate = con.execute(
            "SELECT accession FROM staged_outcomes GROUP BY accession "
            "HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise ValueError(f"duplicate staged outcome for {duplicate[0]}")

        new_query = (
            "SELECT candidate.* FROM staged_outcomes AS candidate "
            "WHERE NOT EXISTS (SELECT 1 FROM current_accessions AS current "
            "WHERE current.accession = candidate.accession)"
        )
        known_query = (
            "SELECT candidate.* FROM staged_outcomes AS candidate "
            "WHERE EXISTS (SELECT 1 FROM current_accessions AS current "
            "WHERE current.accession = candidate.accession)"
        )
        new_count = _copy(con, new_query, output_paths["new"])
        known_count = _copy(con, known_query, output_paths["known"])
        if explicit_refresh:
            entry_query = (
                "SELECT entry.* FROM staged_entries AS entry "
                "JOIN staged_outcomes AS candidates "
                "ON candidates.accession = entry.accession"
            )
        else:
            entry_query = (
                "SELECT entry.* FROM staged_entries AS entry "
                "JOIN staged_outcomes AS candidates "
                "ON candidates.accession = entry.accession "
                "WHERE NOT EXISTS (SELECT 1 FROM current_accessions AS current "
                "WHERE current.accession = candidates.accession)"
            )
        entry_count = _copy(con, entry_query, output_paths["entries"])
        source_query = (
            "SELECT candidate.accession, candidate.source_cik, "
            "min(candidate.first_seen_by) AS first_seen_by "
            "FROM staged_sources AS candidate WHERE NOT EXISTS "
            "(SELECT 1 FROM current_sources AS current "
            "WHERE current.accession = candidate.accession "
            "AND current.source_cik = candidate.source_cik) "
            "GROUP BY candidate.accession, candidate.source_cik"
        )
        source_count = _copy(con, source_query, output_paths["sources"])
    finally:
        con.close()

    return AntiJoinResult(
        new_accessions_path=output_paths["new"],
        known_accessions_path=output_paths["known"],
        candidate_entries_path=output_paths["entries"],
        new_sources_path=output_paths["sources"],
        new_accession_count=new_count,
        known_accession_count=known_count,
        candidate_entry_count=entry_count,
        new_source_count=source_count,
    )
