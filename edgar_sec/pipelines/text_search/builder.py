"""Out-of-core index build over the acquisition snapshot and document cache.

Chunk text streams in bounded batches; postings aggregation and the
already-indexed anti-join happen in DuckDB, never as Python structures.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_identifier,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import DEFAULT_COMPRESSION, write_parquet_table
from edgar_sec.infra.storage.text_index import (
    CHUNKS_SCHEMA,
    CORPUS_STATS_SCHEMA,
    DOCUMENTS_SCHEMA,
    POSTINGS_SCHEMA,
    TERM_STATS_SCHEMA,
    SectionSpan,
    TextIndexStore,
    chunk_id_for,
    chunk_text,
    tokenize,
)

from .options import BuildOptions

_PAYLOAD_BATCH = 16
_FLUSH_CHUNKS = 64
_SNAPSHOT_RELATIONS = (
    "text_payloads",
    "representations",
    "representation_inputs",
    "logical_documents",
    "document_sections",
    "document_notes",
)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One acquired document's identity; its payload is fetched by SHA-256."""

    payload_sha256: str
    accession: str
    cik: int | None
    form: str | None
    filename: str
    logical_document_id: str | None
    document_role: str | None
    source: str
    filing_date: str | None = None


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Counts and identity of one completed build."""

    index_root: Path
    source_snapshot_id: str | None
    payload_count: int
    new_payload_count: int
    reused_payload_count: int
    document_count: int
    accession_count: int
    chunk_count: int
    posting_count: int
    term_count: int
    wall_seconds: float


class _CacheSource:
    """Streaming read of the facade DocumentCache sqlite store."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._con: sqlite3.Connection | None = None

    @property
    def available(self) -> bool:
        return self._db_path.is_file()

    def _connection(self) -> sqlite3.Connection:
        if self._con is None:
            uri = f"{self._db_path.resolve().as_uri()}?mode=ro"
            self._con = sqlite3.connect(uri, uri=True)
        return self._con

    def documents(self) -> Iterator[SourceDocument]:
        if not self.available:
            return
        cursor = self._connection().execute(
            "SELECT accession, cik, form, filename, sha256 FROM cached_documents "
            "ORDER BY accession, filename"
        )
        for accession, cik, form, filename, sha in cursor:
            yield SourceDocument(
                payload_sha256=str(sha),
                accession=str(accession),
                cik=int(cik) if cik is not None else None,
                form=str(form) if form is not None else None,
                filename=str(filename),
                logical_document_id=None,
                document_role=None,
                source="document_cache",
            )

    def payload_bytes(self, payload_sha256: str) -> bytes | None:
        cursor = self._connection().execute(
            "SELECT content FROM cached_documents WHERE sha256 = ? LIMIT 1",
            (payload_sha256,),
        )
        row = cursor.fetchone()
        return bytes(row[0]) if row is not None else None

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None


class _SnapshotSource:
    """DuckDB views over the acquisition snapshot tip's active parts."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root / "document_acquisition" / "snapshots"
        self.snapshot_id: str | None = None
        self._con = None
        self._open()

    def _open(self) -> None:
        catalog_file = self._root / "catalog.sqlite"
        if not catalog_file.is_file():
            return
        catalog = DAGCatalog(self._root, read_only=True)
        pointer = catalog.read_pointer("main")
        if not pointer:
            return
        tip = str(pointer["snapshot_id"])
        parts: dict[str, tuple[Path, ...]] = {}
        for relation in _SNAPSHOT_RELATIONS:
            try:
                parts[relation] = catalog.resolve_active_relation(
                    tip, relation, verify_digests=False
                )
            except ValueError:
                parts[relation] = ()
        if not parts["text_payloads"]:
            return
        self.snapshot_id = tip
        self._con = connect()
        for relation, paths in parts.items():
            view_name = sql_identifier(relation)
            if paths:
                listing = sql_path_list([str(p) for p in paths])
                self._con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet({listing})"
                )
            else:
                self._con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    "SELECT NULL::VARCHAR AS payload_sha256 WHERE FALSE"
                )

    @property
    def available(self) -> bool:
        return self._con is not None

    def documents(self) -> Iterator[SourceDocument]:
        if self._con is None:
            return
        query = """
            SELECT DISTINCT tp.payload_sha256, ld.accession,
                   ld.logical_document_id, ld.target_role
            FROM text_payloads tp
            LEFT JOIN representation_inputs ri
              ON ri.payload_sha256 = tp.payload_sha256
            LEFT JOIN representations r
              ON r.representation_id = ri.representation_id
            LEFT JOIN logical_documents ld
              ON ld.logical_document_id = r.logical_document_id
            ORDER BY tp.payload_sha256
        """
        for sha, accession, logical_id, role in self._con.execute(query).fetchall():
            if accession is None:
                continue
            yield SourceDocument(
                payload_sha256=str(sha),
                accession=str(accession),
                cik=None,
                form=None,
                filename=str(logical_id or sha),
                logical_document_id=str(logical_id) if logical_id else None,
                document_role=str(role) if role else None,
                source="acquisition_snapshot",
            )

    def text_for(self, payload_sha256: str) -> str | None:
        if self._con is None:
            return None
        row = self._con.execute(
            "SELECT text_value, payload_bytes FROM text_payloads "
            "WHERE payload_sha256 = ? LIMIT 1",
            [payload_sha256],
        ).fetchone()
        if row is None:
            return None
        if row[0] is not None:
            return str(row[0])
        if row[1] is not None:
            return bytes(row[1]).decode("utf-8", errors="replace")
        return None

    def sections_for(self, payload_sha256: str) -> list[SectionSpan]:
        if self._con is None:
            return []
        spans: list[SectionSpan] = []
        for query, is_note in (
            (
                "SELECT canonical_name, start_line, end_line FROM document_sections "
                "WHERE payload_sha256 = ? ORDER BY start_line",
                False,
            ),
            (
                "SELECT note_label, start_line, end_line FROM document_notes "
                "WHERE payload_sha256 = ? ORDER BY start_line",
                True,
            ),
        ):
            try:
                rows = self._con.execute(query, [payload_sha256]).fetchall()
            except Exception:  # noqa: BLE001 - an empty view carries no spans
                rows = []
            for label, start, end in rows:
                spans.append(
                    SectionSpan(
                        name=None if is_note else str(label),
                        note_label=str(label) if is_note else None,
                        start_line=int(start),
                        end_line=int(end),
                    )
                )
        return spans

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None


def _normalize_cache_text(raw: bytes, form: str | None, filename: str) -> str:
    """Normalized text through the existing engine seam; raw decode on refusal."""
    from edgar_sec.engine.forms.normalize import normalize_document

    try:
        return normalize_document(raw, form=form, document_path=filename).text
    except Exception:  # noqa: BLE001 - binary/paper payloads carry no prose route
        return raw.decode("utf-8", errors="replace")


def _write_documents(path: Path, documents: Iterator[SourceDocument]) -> int:
    """Stream source-document metadata to Parquet in bounded batches."""
    count = 0
    buffer: list[SourceDocument] = []
    with pq.ParquetWriter(
        str(path), DOCUMENTS_SCHEMA, compression=DEFAULT_COMPRESSION
    ) as writer:

        def flush() -> None:
            nonlocal count
            if not buffer:
                return
            writer.write_table(
                pa.table(
                    {
                        "payload_sha256": [d.payload_sha256 for d in buffer],
                        "accession": [d.accession for d in buffer],
                        "cik": [d.cik for d in buffer],
                        "form": [d.form for d in buffer],
                        "filename": [d.filename for d in buffer],
                        "logical_document_id": [d.logical_document_id for d in buffer],
                        "document_role": [d.document_role for d in buffer],
                        "source": [d.source for d in buffer],
                        "filing_date": [d.filing_date for d in buffer],
                    },
                    schema=DOCUMENTS_SCHEMA,
                )
            )
            count += len(buffer)
            buffer.clear()

        for document in documents:
            buffer.append(document)
            if len(buffer) >= 256:
                flush()
        flush()
    return count


def build_index(options: BuildOptions) -> BuildResult:
    """Build the index at the resolved root, reusing unchanged payloads."""
    started = time.monotonic()
    artifacts_root = options.resolved_artifacts_root()
    index_root = options.resolved_index_root()
    index_root.mkdir(parents=True, exist_ok=True)
    store = TextIndexStore(index_root)
    staging = index_root.parent / f".staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    cache = _CacheSource(options.resolved_cache_db())
    snapshot = _SnapshotSource(artifacts_root)
    con = connect()
    try:
        documents_path = staging / "documents.parquet"
        document_count = _write_documents(
            documents_path,
            _all_documents(cache, snapshot),
        )
        listing = sql_path_list([str(documents_path)])
        con.execute(
            f"CREATE OR REPLACE VIEW src_documents AS "
            f"SELECT * FROM read_parquet({listing})"
        )
        con.execute(
            "CREATE OR REPLACE TEMP TABLE src_payloads AS "
            "SELECT DISTINCT payload_sha256 FROM src_documents"
        )
        payload_count = _scalar(con, "SELECT count(*) FROM src_payloads")
        accession_count = _scalar(
            con, "SELECT count(DISTINCT accession) FROM src_documents"
        )
        if store.exists():
            old_chunks = sql_path_list([str(store.chunks_path)])
            con.execute(
                f"CREATE OR REPLACE TEMP TABLE new_payloads AS "
                f"SELECT payload_sha256 FROM src_payloads WHERE payload_sha256 "
                f"NOT IN (SELECT DISTINCT payload_sha256 FROM "
                f"read_parquet({old_chunks}))"
            )
        else:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE new_payloads AS "
                "SELECT payload_sha256 FROM src_payloads"
            )
        new_count = _scalar(con, "SELECT count(*) FROM new_payloads")
        reused_count = payload_count - new_count
        _index_new_payloads(
            con,
            cache,
            snapshot,
            staging / "new_chunks.parquet",
            staging / "new_postings.parquet",
        )
        chunk_count = _merge_relations(
            con,
            store,
            staging,
        )
        posting_count = _scalar(
            con,
            f"SELECT count(*) FROM read_parquet("
            f"{sql_path_list([str(staging / 'postings.parquet')])})",
        )
        term_count = _write_term_stats(con, staging)
        stats = _corpus_stats(
            con,
            staging,
            source_snapshot_id=snapshot.snapshot_id,
            built_at=datetime.now(UTC).isoformat(timespec="seconds"),
            accession_count=accession_count,
            document_count=document_count,
            payload_count=payload_count,
            chunk_count=chunk_count,
            posting_count=posting_count,
            term_count=term_count,
            new_count=new_count,
            reused_count=reused_count,
        )
        write_parquet_table(stats, staging / "corpus_stats.parquet")
        for name in (
            "chunks.parquet",
            "postings.parquet",
            "term_stats.parquet",
            "documents.parquet",
            "corpus_stats.parquet",
        ):
            os.replace(staging / name, index_root / name)
        return BuildResult(
            index_root=index_root,
            source_snapshot_id=snapshot.snapshot_id,
            payload_count=payload_count,
            new_payload_count=new_count,
            reused_payload_count=reused_count,
            document_count=document_count,
            accession_count=accession_count,
            chunk_count=chunk_count,
            posting_count=posting_count,
            term_count=term_count,
            wall_seconds=time.monotonic() - started,
        )
    finally:
        con.close()
        cache.close()
        snapshot.close()
        if staging.exists():
            shutil.rmtree(staging)


def _all_documents(
    cache: _CacheSource, snapshot: _SnapshotSource
) -> Iterator[SourceDocument]:
    yield from snapshot.documents()
    yield from cache.documents()


def _scalar(con, query: str) -> int:  # noqa: ANN001, ANN202
    row = con.execute(query).fetchone()
    return int(row[0]) if row else 0


def _index_new_payloads(con, cache, snapshot, chunks_path, postings_path) -> None:  # noqa: ANN001, ANN202
    """Chunk and tokenize only the payloads the anti-join marked new."""
    rows = con.execute(
        "SELECT payload_sha256 FROM new_payloads ORDER BY payload_sha256"
    ).fetchall()
    chunk_buffer: list[dict[str, object]] = []
    posting_buffer: list[dict[str, object]] = []
    with (
        pq.ParquetWriter(
            str(chunks_path), CHUNKS_SCHEMA, compression=DEFAULT_COMPRESSION
        ) as chunk_writer,
        pq.ParquetWriter(
            str(postings_path), POSTINGS_SCHEMA, compression=DEFAULT_COMPRESSION
        ) as posting_writer,
    ):

        def flush() -> None:
            if chunk_buffer:
                chunk_writer.write_table(
                    pa.table(
                        {
                            name: [r[name] for r in chunk_buffer]
                            for name in CHUNKS_SCHEMA.names
                        },
                        schema=CHUNKS_SCHEMA,
                    )
                )
                chunk_buffer.clear()
            if posting_buffer:
                posting_writer.write_table(
                    pa.table(
                        {
                            name: [r[name] for r in posting_buffer]
                            for name in POSTINGS_SCHEMA.names
                        },
                        schema=POSTINGS_SCHEMA,
                    )
                )
                posting_buffer.clear()

        processed = 0
        for (sha,) in rows:
            text, sections = _payload_text(con, cache, snapshot, str(sha))
            if text is None:
                continue
            for ordinal, span in enumerate(chunk_text(text, sections)):
                chunk_id = chunk_id_for(str(sha), ordinal)
                counts = tokenize(span.text)
                length = int(sum(counts.values()))
                chunk_buffer.append(
                    {
                        "chunk_id": chunk_id,
                        "payload_sha256": str(sha),
                        "section_name": span.section_name,
                        "note_label": span.note_label,
                        "start_line": span.start_line,
                        "end_line": span.end_line,
                        "chunk_text": span.text,
                        "chunk_length": length,
                    }
                )
                for term, frequency in counts.items():
                    posting_buffer.append(
                        {
                            "term": term,
                            "chunk_id": chunk_id,
                            "term_frequency": int(frequency),
                            "chunk_length": length,
                        }
                    )
                if len(chunk_buffer) >= _FLUSH_CHUNKS:
                    flush()
            processed += 1
            if processed % _PAYLOAD_BATCH == 0:
                reclaim()
        flush()


def _payload_text(con, cache, snapshot, payload_sha256: str):  # noqa: ANN001, ANN202
    """Text and section spans for one payload, snapshot source first."""
    if snapshot.available:
        text = snapshot.text_for(payload_sha256)
        if text is not None:
            return text, snapshot.sections_for(payload_sha256)
    raw = cache.payload_bytes(payload_sha256)
    if raw is None:
        return None, []
    row = con.execute(
        "SELECT form, filename FROM src_documents WHERE payload_sha256 = ? "
        "AND source = 'document_cache' LIMIT 1",
        [payload_sha256],
    ).fetchone()
    form = str(row[0]) if row and row[0] is not None else None
    filename = str(row[1]) if row else payload_sha256
    return _normalize_cache_text(raw, form, filename), []


def _merge_relations(con, store: TextIndexStore, staging: Path) -> int:  # noqa: ANN001, ANN202
    """Union reused relations with the new ones, DuckDB-side, into staging."""
    new_chunks = sql_path_list([str(staging / "new_chunks.parquet")])
    new_postings = sql_path_list([str(staging / "new_postings.parquet")])
    if store.exists():
        old_chunks = sql_path_list([str(store.chunks_path)])
        old_postings = sql_path_list([str(store.postings_path)])
        chunk_count = copy_query_to_parquet(
            con,
            f"SELECT * FROM read_parquet({old_chunks}) "
            f"WHERE payload_sha256 IN (SELECT payload_sha256 FROM src_payloads) "
            f"AND payload_sha256 NOT IN "
            f"(SELECT DISTINCT payload_sha256 FROM read_parquet({new_chunks})) "
            f"UNION ALL SELECT * FROM read_parquet({new_chunks})",
            staging / "chunks.parquet",
            schema=CHUNKS_SCHEMA,
        )
        copy_query_to_parquet(
            con,
            f"SELECT p.* FROM read_parquet({old_postings}) p "
            f"JOIN read_parquet({old_chunks}) c ON c.chunk_id = p.chunk_id "
            f"WHERE c.payload_sha256 IN (SELECT payload_sha256 FROM src_payloads) "
            f"AND c.payload_sha256 NOT IN "
            f"(SELECT DISTINCT payload_sha256 FROM read_parquet({new_chunks})) "
            f"UNION ALL SELECT * FROM read_parquet({new_postings})",
            staging / "postings.parquet",
            schema=POSTINGS_SCHEMA,
        )
    else:
        chunk_count = copy_query_to_parquet(
            con,
            f"SELECT * FROM read_parquet({new_chunks})",
            staging / "chunks.parquet",
            schema=CHUNKS_SCHEMA,
        )
        copy_query_to_parquet(
            con,
            f"SELECT * FROM read_parquet({new_postings})",
            staging / "postings.parquet",
            schema=POSTINGS_SCHEMA,
        )
    return int(chunk_count)


def _write_term_stats(con, staging: Path) -> int:  # noqa: ANN001, ANN202
    """Document frequencies aggregated in DuckDB over the final postings."""
    listing = sql_path_list([str(staging / "postings.parquet")])
    return int(
        copy_query_to_parquet(
            con,
            f"SELECT term, count(*) AS chunk_frequency, "
            f"sum(term_frequency) AS total_frequency "
            f"FROM read_parquet({listing}) GROUP BY term ORDER BY term",
            staging / "term_stats.parquet",
            schema=TERM_STATS_SCHEMA,
        )
    )


def _corpus_stats(con, staging: Path, **values: object) -> pa.Table:  # noqa: ANN001, ANN202
    """The single corpus_stats row, with token totals measured in DuckDB."""
    listing = sql_path_list([str(staging / "chunks.parquet")])
    row = con.execute(
        f"SELECT coalesce(sum(chunk_length), 0), coalesce(avg(chunk_length), 0) "
        f"FROM read_parquet({listing})"
    ).fetchone()
    return pa.table(
        {
            "source_snapshot_id": [values["source_snapshot_id"]],
            "built_at": [values["built_at"]],
            "accession_count": [values["accession_count"]],
            "document_count": [values["document_count"]],
            "payload_count": [values["payload_count"]],
            "chunk_count": [values["chunk_count"]],
            "posting_count": [values["posting_count"]],
            "term_count": [values["term_count"]],
            "total_tokens": [int(row[0]) if row else 0],
            "avg_chunk_length": [float(row[1]) if row else 0.0],
            "new_payload_count": [values["new_count"]],
            "reused_payload_count": [values["reused_count"]],
        },
        schema=CORPUS_STATS_SCHEMA,
    )


__all__ = ["BuildResult", "SourceDocument", "build_index"]
