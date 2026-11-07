"""Direct index construction for engine tests, mirroring the build output."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.text_index import (
    CHUNKS_SCHEMA,
    CORPUS_STATS_SCHEMA,
    DOCUMENTS_SCHEMA,
    POSTINGS_SCHEMA,
    TERM_STATS_SCHEMA,
    TextIndexStore,
    chunk_id_for,
    chunk_text,
    tokenize,
)


def build_index(root: Path, documents: list[tuple]) -> TextIndexStore:
    """Write index relations for (accession, cik, form, filename, role, text)."""
    store = TextIndexStore(root)
    doc_rows: list[dict] = []
    chunk_rows: list[dict] = []
    posting_rows: list[dict] = []
    for accession, cik, form, filename, role, text in documents:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc_rows.append(
            {
                "payload_sha256": sha,
                "accession": accession,
                "cik": cik,
                "form": form,
                "filename": filename,
                "logical_document_id": None,
                "document_role": role,
                "source": "document_cache",
                "filing_date": None,
            }
        )
        for ordinal, span in enumerate(chunk_text(text)):
            chunk_id = chunk_id_for(sha, ordinal)
            counts = tokenize(span.text)
            length = int(sum(counts.values()))
            chunk_rows.append(
                {
                    "chunk_id": chunk_id,
                    "payload_sha256": sha,
                    "section_name": span.section_name,
                    "note_label": span.note_label,
                    "start_line": span.start_line,
                    "end_line": span.end_line,
                    "chunk_text": span.text,
                    "chunk_length": length,
                }
            )
            for term, frequency in counts.items():
                posting_rows.append(
                    {
                        "term": term,
                        "chunk_id": chunk_id,
                        "term_frequency": int(frequency),
                        "chunk_length": length,
                    }
                )
    df: dict[str, int] = {}
    totals: dict[str, int] = {}
    for row in posting_rows:
        df[row["term"]] = df.get(row["term"], 0) + 1
        totals[row["term"]] = totals.get(row["term"], 0) + row["term_frequency"]
    total_tokens = sum(r["chunk_length"] for r in chunk_rows)
    store.write_relation(
        "documents.parquet",
        pa.table(
            {n: [r[n] for r in doc_rows] for n in DOCUMENTS_SCHEMA.names},
            schema=DOCUMENTS_SCHEMA,
        ),
    )
    store.write_relation(
        "chunks.parquet",
        pa.table(
            {n: [r[n] for r in chunk_rows] for n in CHUNKS_SCHEMA.names},
            schema=CHUNKS_SCHEMA,
        ),
    )
    store.write_relation(
        "postings.parquet",
        pa.table(
            {n: [r[n] for r in posting_rows] for n in POSTINGS_SCHEMA.names},
            schema=POSTINGS_SCHEMA,
        ),
    )
    terms = sorted(df)
    store.write_relation(
        "term_stats.parquet",
        pa.table(
            {
                "term": terms,
                "chunk_frequency": [df[t] for t in terms],
                "total_frequency": [totals[t] for t in terms],
            },
            schema=TERM_STATS_SCHEMA,
        ),
    )
    store.write_relation(
        "corpus_stats.parquet",
        pa.table(
            {
                "source_snapshot_id": [None],
                "built_at": ["2026-11-07T00:00:00+00:00"],
                "accession_count": [len({r["accession"] for r in doc_rows})],
                "document_count": [len(doc_rows)],
                "payload_count": [len({r["payload_sha256"] for r in doc_rows})],
                "chunk_count": [len(chunk_rows)],
                "posting_count": [len(posting_rows)],
                "term_count": [len(terms)],
                "total_tokens": [total_tokens],
                "avg_chunk_length": [
                    total_tokens / len(chunk_rows) if chunk_rows else 0.0
                ],
                "new_payload_count": [len(doc_rows)],
                "reused_payload_count": [0],
            },
            schema=CORPUS_STATS_SCHEMA,
        ),
    )
    return store
