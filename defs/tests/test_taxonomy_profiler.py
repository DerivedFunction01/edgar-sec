"""Unit tests for the empirical table family profiler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from defs.taxonomy.components.schedules.derivatives import DERIVATIVES_HEDGING_SPEC
from defs.taxonomy.probe.profiler import (
    FamilyProfileResult,
    _compute_percentiles,
    _extract_frequent_lines,
    format_profile_report,
    profile_table_family,
)


def test_compute_percentiles_empty() -> None:
    stats = _compute_percentiles([])
    assert stats.min == 0
    assert stats.median == 0
    assert stats.max == 0


def test_compute_percentiles_distribution() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    stats = _compute_percentiles(vals)
    assert stats.min == 1.0
    assert stats.max == 10.0
    assert stats.median == 5.0


def test_extract_frequent_lines() -> None:
    lines = [
        "Interest rate swaps\nForeign exchange forwards",
        "Interest rate swaps\nCommodity contracts",
        "Interest rate swaps\nForeign exchange forwards\nCredit default swaps",
    ]
    extracted = _extract_frequent_lines(lines, top_k=5)
    assert len(extracted) >= 3
    assert extracted[0]["phrase"] == "interest rate swaps"
    assert extracted[0]["count"] == 3
    assert extracted[0]["pct"] == 100.0


def test_format_profile_report() -> None:
    result = FamilyProfileResult(
        family_name="test_family",
        total_corpus_tables=1000,
        matched_tables=50,
        match_pct=5.0,
        form_type_distribution={"10-K": 40, "10-Q": 10},
        raw_rows_stats=_compute_percentiles([10.0, 20.0]),
        healed_rows_stats=_compute_percentiles([8.0, 16.0]),
        raw_cols_stats=_compute_percentiles([12.0, 15.0]),
        healed_cols_stats=_compute_percentiles([4.0, 5.0]),
        numeric_density_stats=_compute_percentiles([0.7, 0.8]),
        jitter_diagnostics=MagicMock(
            jitter_count=10,
            jitter_pct=20.0,
            split_affix_count=25,
            split_affix_pct=50.0,
            col_contraction_count=45,
            col_contraction_pct=90.0,
            row_compression_count=30,
            row_compression_pct=60.0,
        ),
        top_column_headers=[{"phrase": "three months ended", "count": 25, "pct": 50.0}],
        top_row_labels=[{"phrase": "interest rate swap", "count": 20, "pct": 40.0}],
        top_headings=[{"phrase": "note 10 - derivatives", "count": 15, "pct": 30.0}],
        top_item_labels=[{"phrase": "item 8", "count": 35, "pct": 70.0}],
        shape_constraint_violations={"violating_count": 2, "violating_pct": 4.0},
        jittery_samples=[],
    )
    report = format_profile_report(result)
    assert "TEST_FAMILY" in report
    assert "1,000 non-TOC tables" in report
    assert "Raw Rows" in report
    assert "Column Jitter Rate:    10 tables (20.00%)" in report
    assert "three months ended" in report


@patch("defs.taxonomy.probe.profiler.duckdb.connect")
def test_profile_table_family_mocked(
    mock_connect: MagicMock, tmp_path: MagicMock
) -> None:
    dummy_cache = tmp_path / "probe.parquet"
    dummy_cache.touch()

    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn

    # Count query
    mock_conn.execute.return_value.fetchone.return_value = [100]

    # Data query
    mock_df_records = [
        {
            "doc_id": "doc1",
            "form_type": "10-K",
            "table_index": 1,
            "raw_rows": 15,
            "raw_cols": 12,
            "healed_rows": 10,
            "healed_cols": 4,
            "numeric_density": 0.75,
            "has_column_jitter": True,
            "has_split_affixes": True,
            "header_text": "Interest Rate Swaps\nNotional Amount",
            "row_labels_text": "Pay Fixed Receive Floating\nTotal Swaps",
            "heading": "Note 10 - Derivatives",
            "item_label": "Item 8",
            "healed_grid_json": '[["Interest Rate Swaps", "100"]]',
        }
    ]
    mock_conn.execute.return_value.fetch_arrow_table.return_value.to_pylist.return_value = mock_df_records

    res = profile_table_family(
        cache_path=dummy_cache,
        family_name="derivatives_hedging",
        spec=DERIVATIVES_HEDGING_SPEC,
        sample_jittery=1,
    )
    assert res.matched_tables == 1
    assert res.jitter_diagnostics.jitter_count == 1
    assert res.jitter_diagnostics.split_affix_count == 1
    assert len(res.jittery_samples) == 1
