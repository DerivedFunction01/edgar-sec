"""Tests for the facade text search surface."""

from __future__ import annotations

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.pipelines.text_search.builder import build_index
from edgar_sec.pipelines.text_search.options import BuildOptions

from tests.pipelines.text_search.support import make_cache_db


def _edgar(tmp_path) -> Edgar:  # noqa: ANN001, ANN202
    artifacts = tmp_path / "artifacts"
    cache_db = make_cache_db(
        artifacts / "cache" / "documents.sqlite",
        [
            (
                "0000000001-26-000001",
                1,
                "10-K",
                "filing.txt",
                "Revenue grew strongly.\nLiquidity remains adequate.\n",
            )
        ],
    )
    build_index(BuildOptions(artifacts_root=artifacts, cache_db=cache_db))
    return Edgar(artifacts_root=artifacts)


def test_facade_bm25_search_with_coverage(tmp_path) -> None:  # noqa: ANN001
    result = _edgar(tmp_path).search_documents("revenue")
    assert result.hits
    assert result.hits[0].accession == "0000000001-26-000001"
    assert result.coverage.index_present
    assert result.coverage.documents_searched == 1


def test_facade_exact_search(tmp_path) -> None:  # noqa: ANN001
    result = _edgar(tmp_path).search_documents("liquidity remains", mode="exact")
    assert len(result.hits) == 1
    assert result.hits[0].score is None


def test_facade_scoped_absent_accession(tmp_path) -> None:  # noqa: ANN001
    result = _edgar(tmp_path).search_documents(
        "revenue", accessions=("9999999999-26-000001",)
    )
    assert result.hits == ()
    assert result.not_in_corpus == ("9999999999-26-000001",)
