"""Tests for the text index store, chunking, and tokenizer."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.infra.storage.text_index import (
    CORPUS_STATS_SCHEMA,
    SectionSpan,
    TextIndexStore,
    chunk_id_for,
    chunk_text,
    tokenize,
    tokenize_query,
)


def test_tokenize_counts_terms_of_length_at_least_two() -> None:
    counts = tokenize("Revenue revenue, a 10-K net-income!")
    assert counts["revenue"] == 2
    assert counts["net"] == 1
    assert counts["income"] == 1
    assert "a" not in counts
    assert tokenize_query("Net income net") == ["net", "income"]


def test_chunk_text_line_windows_are_bounded() -> None:
    text = "\n".join(f"line {i} revenue" for i in range(450))
    spans = list(chunk_text(text))
    assert len(spans) == 3
    assert spans[0].start_line == 1
    assert spans[0].end_line == 200
    assert spans[-1].end_line == 450
    assert all(span.section_name is None for span in spans)


def test_chunk_text_uses_section_boundaries() -> None:
    text = "one\ntwo\nthree\nfour"
    spans = list(
        chunk_text(
            text,
            [SectionSpan(name="Item 1", note_label=None, start_line=2, end_line=3)],
        )
    )
    assert len(spans) == 1
    assert spans[0].section_name == "Item 1"
    assert spans[0].text == "two\nthree"
    assert spans[0].start_line == 2


def test_chunk_ids_are_deterministic_and_distinct() -> None:
    sha = "a" * 64
    assert chunk_id_for(sha, 0) == chunk_id_for(sha, 0)
    assert chunk_id_for(sha, 0) != chunk_id_for(sha, 1)


def test_store_roundtrip_corpus_stats(tmp_path) -> None:  # noqa: ANN001
    store = TextIndexStore(tmp_path / "index")
    assert not store.exists()
    assert store.corpus_stats() is None
    table = pa.table(
        {
            "source_snapshot_id": [None],
            "built_at": ["2026-11-07T00:00:00+00:00"],
            "accession_count": [1],
            "document_count": [1],
            "payload_count": [1],
            "chunk_count": [2],
            "posting_count": [3],
            "term_count": [2],
            "total_tokens": [10],
            "avg_chunk_length": [5.0],
            "new_payload_count": [1],
            "reused_payload_count": [0],
        },
        schema=CORPUS_STATS_SCHEMA,
    )
    store.write_relation("corpus_stats.parquet", table)
    stats = store.corpus_stats()
    assert stats is not None
    assert stats["chunk_count"] == 2
