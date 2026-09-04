"""Unit and contract tests for pipeline table probe, census, and clustering."""

from __future__ import annotations

from defs.taxonomy.probe.audit import compute_geometry_stats
from defs.taxonomy.probe.census import (
    cluster_unclassified_tables,
    compute_distinctive_ngrams,
    extract_ngrams,
)


def test_extract_ngrams_filtering() -> None:
    """extract_ngrams excludes grammatical stop words and corporate boilerplate."""
    text = "the company will pay total minimum lease payments of 500 in millions"
    bigrams = extract_ngrams(text, n=2)
    assert "minimum lease" in bigrams
    assert "lease payments" in bigrams
    # Boilerplate 'the', 'company', 'of', 'in', 'millions' should not produce raw stop grams
    assert "the company" not in bigrams


def test_compute_distinctive_ngrams() -> None:
    """Distinctive n-grams surface terms enriched in target vs background."""
    target = [
        "total minimum lease payments thereafter imputed interest",
        "present value of lease liabilities total minimum lease",
    ]
    bg = [
        "total revenues cost of goods sold gross profit",
        "operating activities cash provided by operations",
    ]
    distinctive = compute_distinctive_ngrams(
        target, bg, n=2, top_k=5, min_target_freq=1
    )
    terms = [d["term"] for d in distinctive]
    assert "minimum lease" in terms or "lease payments" in terms


def test_cluster_unclassified_tables() -> None:
    """Unclassified tables with common row-stub phrases form candidate clusters."""
    unclass = [
        {
            "row_labels_text": "imputed interest minimum lease payments",
            "heading": "Leases",
        },
        {
            "row_labels_text": "present value minimum lease payments",
            "heading": "Leases Note",
        },
        {
            "row_labels_text": "total minimum lease payments thereafter",
            "heading": "Commitments",
        },
        {"row_labels_text": "other generic random line item", "heading": "Random"},
    ]
    clusters = cluster_unclassified_tables(unclass, min_cluster_size=2, top_k=5)
    assert len(clusters) >= 1
    assert any("lease" in str(c["signature"]) for c in clusters)


def test_compute_geometry_stats() -> None:
    """Geometry stats aggregate post-healing dimensions and jitter percentages."""
    records = [
        {
            "healed_cols": 2,
            "healed_rows": 6,
            "numeric_density": 0.5,
            "header_count": 1,
            "has_column_jitter": False,
            "has_split_affixes": False,
        },
        {
            "healed_cols": 6,
            "healed_rows": 10,
            "numeric_density": 0.8,
            "header_count": 1,
            "has_column_jitter": True,
            "has_split_affixes": True,
        },
    ]
    stats = compute_geometry_stats(records)
    assert stats["count"] == 2
    assert stats["healed_cols"]["min"] == 2
    assert stats["healed_cols"]["max"] == 6
    assert stats["jitter_pct"] == 50.0
    assert stats["split_affixes_pct"] == 50.0
