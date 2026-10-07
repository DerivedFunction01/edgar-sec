"""Transactional DuckDB journal for resumable S4 chunk attempts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.models import ParsedIndexPage
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_path_list

from .checkpoint import OUTCOME_SCHEMA, RETRYABLE_STATUSES, outcome_row
from .paths import InventoryRunPaths
from .run_manifest import ChunkIdentity, InventoryRunManifest, PROGRESS_SCHEMA_VERSION

_OUTCOME_INSERT = "INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
_ENTRY_INSERT = "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
_METADATA_INSERT = "INSERT INTO progress_metadata VALUES (?)"


def _entry_values(entry: Any) -> tuple[Any, ...]:
    return (
        entry.entry_id,
        str(entry.accession),
        entry.table_kind,
        entry.row_ordinal,
        entry.sequence,
        entry.document_type,
        entry.document_label,
        entry.description,
        entry.filename,
        entry.href,
        entry.archive_url,
        entry.byte_size,
    )


class ProgressStore:
    def __init__(
        self,
        paths: InventoryRunPaths,
        chunk: ChunkIdentity,
        run: InventoryRunManifest,
        attempt_id: str,
        database: Path,
        *,
        purpose: str,
        source_attempt_id: str | None,
        profile: Any | None,
        create: bool,
    ) -> None:
        self.paths = paths
        self.chunk = chunk
        self.attempt_id = attempt_id
        self.database = database
        self.metadata = {
            "run_id": run.run_id,
            "chunk_id": chunk.chunk_id,
            "attempt_id": attempt_id,
            "work_order_version": run.work_order_version,
            "membership_digest": chunk.membership_digest,
            "membership_count": chunk.membership_count,
            "parser_version": run.parser_version,
            "outcome_schema_version": run.outcome_schema_version,
            "entry_schema_version": run.entry_schema_version,
            "progress_version": PROGRESS_SCHEMA_VERSION,
            "purpose": purpose,
            "source_attempt_id": source_attempt_id,
        }
        self._con = connect(profile=profile, database=database)
        try:
            if create:
                self._create()
            else:
                self._validate()
        except BaseException:
            self._con.close()
            raise

    def _create(self) -> None:
        self._con.execute("CREATE TABLE progress_metadata (payload VARCHAR NOT NULL)")
        self._con.execute(
            "CREATE TABLE outcomes (accession VARCHAR PRIMARY KEY, status VARCHAR, "
            "index_url VARCHAR, page_sha256 VARCHAR, response_size BIGINT, "
            "entry_count INTEGER, xbrl_candidate_url VARCHAR, bundle_url VARCHAR, "
            "bundle_size BIGINT, diagnostics_json VARCHAR, error_code VARCHAR, "
            "error_detail VARCHAR)"
        )
        self._con.execute(
            "CREATE TABLE entries (entry_id VARCHAR, accession VARCHAR, "
            "table_kind VARCHAR, row_ordinal INTEGER, sequence INTEGER, "
            "document_type VARCHAR, document_label VARCHAR, description VARCHAR, "
            "filename VARCHAR, href VARCHAR, archive_url VARCHAR, byte_size BIGINT)"
        )
        self._con.execute("CREATE TABLE completed (accession VARCHAR PRIMARY KEY)")
        self._con.execute(_METADATA_INSERT, [canonical_json(self.metadata)])
        self._con.execute("CHECKPOINT")

    def _validate(self) -> None:
        rows = self._con.execute("SELECT payload FROM progress_metadata").fetchmany(2)
        if len(rows) != 1 or json.loads(rows[0][0]) != self.metadata:
            raise ValueError("progress metadata mismatch")
        counts = self._con.execute(
            "SELECT (SELECT count(*) FROM completed), "
            "(SELECT count(*) FROM outcomes), "
            "(SELECT count(*) FROM outcomes o LEFT JOIN completed c USING(accession) "
            "WHERE c.accession IS NULL), "
            "(SELECT count(*) FROM completed c LEFT JOIN outcomes o USING(accession) "
            "WHERE o.accession IS NULL), "
            "(SELECT count(*) FROM entries e LEFT JOIN completed c USING(accession) "
            "WHERE c.accession IS NULL)"
        ).fetchone()
        if counts is None or counts[0] != counts[1] or any(counts[2:]):
            raise ValueError("progress relations are inconsistent")

    def completed_accessions(self, members: Sequence[Any]) -> tuple[str, ...]:
        self._con.execute("CREATE OR REPLACE TEMP TABLE expected (accession VARCHAR)")
        self._con.execute(
            "INSERT INTO expected SELECT unnest(?)",
            [[str(i.accession) for i in members]],
        )
        invalid = self._con.execute(
            "SELECT count(*) FROM outcomes o ANTI JOIN expected e USING(accession)"
        ).fetchone()[0]
        invalid += self._con.execute(
            "SELECT count(*) FROM entries x ANTI JOIN expected e USING(accession)"
        ).fetchone()[0]
        if invalid:
            raise ValueError("progress rows fall outside chunk membership")
        reader = self._con.execute(
            "SELECT accession FROM expected ANTI JOIN completed USING(accession) "
            "ORDER BY accession"
        ).to_arrow_reader(batch_size=1024)
        missing: list[str] = []
        for batch in reader:
            missing.extend(
                batch.column(0)[index].as_py() for index in range(batch.num_rows)
            )
        return tuple(missing)

    def has_completed(self, accession: str) -> bool:
        return self._con.execute(
            "SELECT EXISTS (SELECT 1 FROM completed WHERE accession = ?)",
            [accession],
        ).fetchone()[0]

    def counts(self) -> tuple[int, int, int]:
        return self._con.execute(
            "SELECT count(*), count(*) FILTER (WHERE status IN "
            "('unrecognized', 'parse_failure', 'fetch_failed', 'worker_error')), "
            "(SELECT count(*) FROM entries) FROM outcomes"
        ).fetchone()

    def record(self, result: Any, *, index_url: str) -> None:
        outcome = outcome_row(result, index_url=index_url)
        values = tuple(outcome.get(field.name) for field in OUTCOME_SCHEMA)
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(_OUTCOME_INSERT, values)
            if isinstance(result, ParsedIndexPage):
                for entry in result.entries:
                    self._con.execute(_ENTRY_INSERT, _entry_values(entry))
            self._con.execute(
                "INSERT INTO completed VALUES (?)", [str(result.accession)]
            )
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise

    def import_accession(
        self,
        outcome: Mapping[str, Any],
        entry_rows: Iterable[Sequence[Any]],
    ) -> None:
        values = tuple(outcome.get(field.name) for field in OUTCOME_SCHEMA)
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(_OUTCOME_INSERT, values)
            for row in entry_rows:
                self._con.execute(_ENTRY_INSERT, list(row))
            self._con.execute(
                "INSERT INTO completed VALUES (?)", [outcome["accession"]]
            )
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise

    def export(self, writers: Any) -> None:
        for query, writer in (
            ("SELECT * FROM outcomes ORDER BY accession", writers.write_outcome_batch),
            (
                "SELECT * FROM entries ORDER BY accession, entry_id",
                writers.write_entry_batch,
            ),
        ):
            reader = self._con.execute(query).to_arrow_reader(batch_size=128_000)
            for batch in reader:
                writer(batch)

    def seed_carry(self, outcomes_path: Path, entries_path: Path, profile: Any) -> None:
        source = connect(profile=profile)
        entry_source = connect(profile=profile)
        outcome_files = sql_path_list([str(outcomes_path)])
        entry_files = sql_path_list([str(entries_path)])
        try:
            reader = source.execute(
                f"SELECT * FROM read_parquet({outcome_files}) ORDER BY accession"
            ).to_arrow_reader(batch_size=256)
            for batch in reader:
                for index in range(batch.num_rows):
                    outcome = {
                        name: batch.column(column)[index].as_py()
                        for column, name in enumerate(OUTCOME_SCHEMA.names)
                    }
                    if outcome["status"] in RETRYABLE_STATUSES:
                        continue
                    accession = outcome["accession"]
                    if self.has_completed(accession):
                        continue
                    entries = entry_source.execute(
                        f"SELECT * FROM read_parquet({entry_files}) "
                        "WHERE accession = ? ORDER BY entry_id",
                        [accession],
                    ).to_arrow_reader(batch_size=256)

                    def values():
                        for entry_batch in entries:
                            for row_index in range(entry_batch.num_rows):
                                yield tuple(
                                    entry_batch.column(column)[row_index].as_py()
                                    for column in range(entry_batch.num_columns)
                                )

                    self.import_accession(outcome, values())
        finally:
            source.close()
            entry_source.close()

    def close(self) -> None:
        self._con.close()


def open_progress(
    paths: InventoryRunPaths,
    chunk: ChunkIdentity,
    run: InventoryRunManifest,
    *,
    purpose: str = "fresh",
    source_attempt_id: str | None = None,
    profile: Any | None = None,
    force_new: bool = False,
) -> ProgressStore:
    pointer = paths.progress_pointer_path(chunk.chunk_id)
    if pointer.is_file() and not force_new:
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            attempt_id = str(data["attempt_id"])
            database = paths.progress_database_path(chunk.chunk_id, attempt_id)
            if data.get("chunk_id") != chunk.chunk_id or not database.is_file():
                raise ValueError("progress pointer is invalid")
            return ProgressStore(
                paths,
                chunk,
                run,
                attempt_id,
                database,
                purpose=purpose,
                source_attempt_id=source_attempt_id,
                profile=profile,
                create=False,
            )
        except Exception:
            pass
    from .checkpoint import new_attempt_id

    attempt_id = new_attempt_id()
    database = paths.progress_database_path(chunk.chunk_id, attempt_id)
    database.parent.mkdir(parents=True, exist_ok=True)
    store = ProgressStore(
        paths,
        chunk,
        run,
        attempt_id,
        database,
        purpose=purpose,
        source_attempt_id=source_attempt_id,
        profile=profile,
        create=True,
    )
    atomic_write_json(
        pointer,
        {"chunk_id": chunk.chunk_id, "attempt_id": attempt_id},
        canonical=True,
    )
    return store
