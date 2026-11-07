"""Tests for BM25, exact, and regex search over a stored index."""

from __future__ import annotations

import pytest

from edgar_sec.engine.text_search.engine import search_index
from edgar_sec.engine.text_search.models import SearchScope

from .support import build_index

_DOCS = [
    (
        "0000000001-26-000001",
        1,
        "10-K",
        "primary.txt",
        "primary",
        "Revenue grew strongly this year.\nLiquidity remains adequate.\n",
    ),
    (
        "0000000001-26-000001",
        1,
        "10-K",
        "exhibit.txt",
        "exhibit",
        "Revenue exhibit table follows.\n",
    ),
    (
        "0000000002-26-000001",
        2,
        "10-Q",
        "quarter.txt",
        "primary",
        "Goodwill impairment was recorded.\nRevenue was flat.\n",
    ),
]


def _root(tmp_path):  # noqa: ANN001, ANN202
    root = tmp_path / "index"
    build_index(root, _DOCS)
    return root


def test_bm25_ranks_and_scores(tmp_path) -> None:  # noqa: ANN001
    result = search_index(_root(tmp_path), "revenue", mode="bm25")
    assert result.hits
    assert all(hit.score is not None and hit.score > 0 for hit in result.hits)
    assert result.coverage.index_present
    assert result.coverage.chunks_searched == 3
    assert result.coverage.accessions_searched == 2
    assert "Revenue" in result.hits[0].excerpt


def test_bm25_every_hit_is_a_true_match(tmp_path) -> None:  # noqa: ANN001
    result = search_index(_root(tmp_path), "goodwill", mode="bm25")
    assert len(result.hits) == 1
    assert result.hits[0].accession == "0000000002-26-000001"


def test_exact_mode_has_no_score_and_matches_phrase(tmp_path) -> None:  # noqa: ANN001
    result = search_index(_root(tmp_path), "net income", mode="exact")
    assert result.hits == ()
    result = search_index(_root(tmp_path), "revenue grew", mode="exact")
    assert len(result.hits) == 1
    assert result.hits[0].score is None
    assert result.hits[0].filename == "primary.txt"


def test_regex_mode(tmp_path) -> None:  # noqa: ANN001
    result = search_index(_root(tmp_path), r"[Ll]iquid\w+", mode="regex")
    assert len(result.hits) == 1
    with pytest.raises(ValueError):
        search_index(_root(tmp_path), r"([", mode="regex")


def test_scope_filters_and_primary_only(tmp_path) -> None:  # noqa: ANN001
    root = _root(tmp_path)
    scoped = search_index(
        root,
        "revenue",
        mode="exact",
        scope=SearchScope(accessions=("0000000002-26-000001",)),
    )
    assert {hit.accession for hit in scoped.hits} == {"0000000002-26-000001"}
    primary = search_index(
        root,
        "revenue",
        mode="exact",
        scope=SearchScope(attachment_scope="primary_only"),
    )
    assert {hit.filename for hit in primary.hits} == {"primary.txt", "quarter.txt"}


def test_absent_target_reports_not_in_corpus(tmp_path) -> None:  # noqa: ANN001
    result = search_index(
        _root(tmp_path),
        "revenue",
        mode="exact",
        scope=SearchScope(accessions=("9999999999-26-000001",)),
    )
    assert result.hits == ()
    assert result.not_in_corpus == ("9999999999-26-000001",)
    assert result.coverage.targets[0].covered is False


def test_missing_index_reports_absence(tmp_path) -> None:  # noqa: ANN001
    result = search_index(
        tmp_path / "nope",
        "revenue",
        scope=SearchScope(accessions=("0000000001-26-000001",)),
    )
    assert result.hits == ()
    assert result.coverage.index_present is False
    assert result.not_in_corpus == ("0000000001-26-000001",)


def test_unknown_mode_refused(tmp_path) -> None:  # noqa: ANN001
    with pytest.raises(ValueError):
        search_index(_root(tmp_path), "revenue", mode="semantic")
