"""Tests for the out-of-core text index build."""

from __future__ import annotations

from edgar_sec.infra.storage.text_index import TextIndexStore
from edgar_sec.pipelines.text_search.builder import build_index
from edgar_sec.pipelines.text_search.options import BuildOptions

from .support import make_cache_db

_DOCS = [
    (
        "0000000001-26-000001",
        1,
        "10-K",
        "filing.txt",
        "Revenue grew strongly.\nLiquidity remains adequate.\n" * 3,
    ),
    (
        "0000000002-26-000001",
        2,
        "10-Q",
        "quarter.txt",
        "Goodwill impairment was recorded.\nRevenue was flat.\n",
    ),
]


def _options(tmp_path):  # noqa: ANN001, ANN202
    artifacts = tmp_path / "artifacts"
    cache_db = make_cache_db(artifacts / "cache" / "documents.sqlite", _DOCS)
    return BuildOptions(artifacts_root=artifacts, cache_db=cache_db)


def test_build_covers_cache_payloads(tmp_path) -> None:  # noqa: ANN001
    options = _options(tmp_path)
    result = build_index(options)
    assert result.payload_count == 2
    assert result.new_payload_count == 2
    assert result.reused_payload_count == 0
    assert result.document_count == 2
    assert result.accession_count == 2
    assert result.chunk_count >= 2
    assert result.posting_count > 0
    store = TextIndexStore(options.resolved_index_root())
    assert store.exists()
    stats = store.corpus_stats()
    assert stats is not None
    assert stats["payload_count"] == 2
    assert stats["chunk_count"] == result.chunk_count


def test_rebuild_over_unchanged_corpus_indexes_zero_new(tmp_path) -> None:  # noqa: ANN001
    options = _options(tmp_path)
    first = build_index(options)
    second = build_index(options)
    assert second.new_payload_count == 0
    assert second.reused_payload_count == 2
    assert second.chunk_count == first.chunk_count
    assert second.posting_count == first.posting_count


def test_build_with_no_corpus_writes_empty_index(tmp_path) -> None:  # noqa: ANN001
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    options = BuildOptions(
        artifacts_root=artifacts, cache_db=artifacts / "cache" / "documents.sqlite"
    )
    result = build_index(options)
    assert result.payload_count == 0
    assert result.chunk_count == 0
    assert TextIndexStore(options.resolved_index_root()).exists()
