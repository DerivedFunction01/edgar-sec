"""Unit and contract tests for the taxonomy family dataset exporter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from defs.taxonomy.probe.exporter import (
    _build_search_terms,
    _detect_template_applied,
    _extract_table_html,
    _generate_rendered_output,
    _reconstruct_html_from_grid,
    export_family_dataset,
)
from defs.taxonomy.tables.families import FAMILY_SPECS


def test_build_search_terms() -> None:
    """_build_search_terms extracts terms from the evidence pack."""
    spec = FAMILY_SPECS["shares_purchased"]
    terms = _build_search_terms(spec)
    assert len(terms) > 0
    assert any("shares" in t for t in terms)


def test_build_search_terms_unknown_family() -> None:
    """_build_search_terms returns empty list for None spec."""
    terms = _build_search_terms(None)
    assert terms == []


def test_detect_template_applied() -> None:
    """_detect_template_applied returns standard_html_converter for non-matching grid."""
    grid = [["a", "b"], ["1", "2"]]
    result = _detect_template_applied(grid)
    assert result == "standard_html_converter"


def test_reconstruct_html_from_grid() -> None:
    """_reconstruct_html_from_grid produces valid HTML table."""
    grid = [["Header1", "Header2"], ["val1", "val2"]]
    html = _reconstruct_html_from_grid(grid)
    assert "<table>" in html
    assert "<tr>" in html
    assert "<td>" in html
    assert "</table>" in html


def test_extract_table_html() -> None:
    """_extract_table_html extracts the correct table snippet."""
    html = "<html><body><table><tr><td>test</td></tr></table></body></html>"
    result = _extract_table_html(html, 0)
    assert "<table>" in result
    assert "<td>test</td>" in result


def test_extract_table_html_out_of_range() -> None:
    """_extract_table_html returns empty string for out-of-range index."""
    html = "<html><body><table><tr><td>test</td></tr></table></body></html>"
    result = _extract_table_html(html, 99)
    assert result == ""


def test_extract_table_html_empty() -> None:
    """_extract_table_html returns empty string for empty input."""
    result = _extract_table_html("", 0)
    assert result == ""


def test_generate_rendered_output() -> None:
    """_generate_rendered_output produces non-empty ASCII output."""
    grid = [["Header1", "Header2"], ["val1", "val2"]]
    result = _generate_rendered_output(grid, header_row_count=1)
    assert len(result) > 0
    assert "<TABLE>" in result


def _make_mock_records(count: int = 1) -> list[dict]:
    """Create mock probe records for testing."""
    return [
        {
            "doc_id": f"doc{i}",
            "document_path": "test.htm",
            "form_type": "10-K",
            "table_index": 0,
            "identity_sha256": f"abc{i}",
            "is_toc": False,
            "raw_rows": 5,
            "raw_cols": 4,
            "healed_rows": 5,
            "healed_cols": 4,
            "header_count": 1,
            "numeric_density": 0.75,
            "has_column_jitter": True,
            "has_split_affixes": False,
            "row_labels_text": "test row",
            "header_text": "test header",
            "full_normalized_text": "test",
            "item_label": "Item 5",
            "heading": "Test Heading",
            "prev_context": "",
            "next_context": "",
            "healed_grid_json": '[["H1", "H2"], ["v1", "v2"]]',
        }
        for i in range(count)
    ]


def _run_export_test(
    family: str = "shares_purchased",
    limit: int = 1,
    record_count: int = 1,
    output_path: Path | None = None,
    db_path: Path | None = None,
) -> Path:
    """Helper to run export with mocked dependencies."""
    import tempfile

    tmpdir = tempfile.mkdtemp()
    output_path = output_path or Path(tmpdir) / "export.parquet"
    db_path = db_path or Path(tmpdir) / "fixture.sqlite"
    db_path.touch()

    # Create a mock cache file so exists() check passes
    cache_path = Path(tmpdir) / "probe.parquet"
    pq.write_table(pa.Table.from_pylist([]), cache_path)

    mock_records = _make_mock_records(record_count)

    with (
        patch("defs.taxonomy.probe.exporter._query_family_records") as mock_query,
        patch("defs.taxonomy.probe.exporter.stream_document_blobs") as mock_blobs,
        patch(
            "defs.taxonomy.probe.exporter.default_fixture_db_path"
        ) as mock_db_path_fn,
        patch(
            "defs.taxonomy.probe.exporter.default_probe_cache_path"
        ) as mock_cache_path_fn,
    ):
        mock_db_path_fn.return_value = db_path
        mock_cache_path_fn.return_value = cache_path
        mock_query.return_value = mock_records

        mock_blob = MagicMock()
        mock_blob.doc_id = "doc0"
        mock_blob.raw_payload = b"<html><body></body></html>"
        mock_blobs.return_value = [mock_blob]

        return export_family_dataset(
            family,
            output_path=output_path,
            limit=limit,
            db_path=db_path,
        )


def test_export_schema_matches_spec() -> None:
    """Exported parquet has all required fields with correct types."""
    expected_fields = {
        "family": pa.string(),
        "table_id": pa.string(),
        "doc_id": pa.string(),
        "table_index": pa.int64(),
        "document_path": pa.string(),
        "form_type": pa.string(),
        "item_label": pa.string(),
        "heading": pa.string(),
        "raw_rows": pa.int64(),
        "raw_cols": pa.int64(),
        "healed_rows": pa.int64(),
        "healed_cols": pa.int64(),
        "numeric_density": pa.float64(),
        "has_column_jitter": pa.bool_(),
        "has_split_affixes": pa.bool_(),
        "html": pa.string(),
        "healed_grid_json": pa.string(),
        "rendered_output": pa.string(),
        "template_applied": pa.string(),
        "repair_policy": pa.string(),
    }

    result = _run_export_test()
    out_table = pq.read_table(result)
    assert out_table.num_rows == 1

    for field_name, expected_type in expected_fields.items():
        actual_type = out_table.schema.field(field_name).type
        assert actual_type == expected_type, (
            f"Field {field_name}: expected {expected_type}, got {actual_type}"
        )


def test_export_record_values() -> None:
    """Exported records have correct values for key fields."""
    result = _run_export_test()
    out_table = pq.read_table(result)
    row = out_table.to_pylist()[0]

    assert row["family"] == "shares_purchased"
    assert row["table_id"] == "doc0_t0"
    assert row["doc_id"] == "doc0"
    assert row["table_index"] == 0
    assert row["form_type"] == "10-K"
    assert row["item_label"] == "Item 5"
    assert row["heading"] == "Test Heading"
    assert row["raw_rows"] == 5
    assert row["raw_cols"] == 4
    assert row["healed_rows"] == 5
    assert row["healed_cols"] == 4
    assert row["numeric_density"] == 0.75
    assert row["has_column_jitter"] is True
    assert row["has_split_affixes"] is False
    assert len(row["html"]) > 0
    assert len(row["healed_grid_json"]) > 0
    assert len(row["rendered_output"]) > 0
    assert len(row["template_applied"]) > 0
    assert row["repair_policy"] == "family_template"


def test_export_unknown_family_raises() -> None:
    """export_family_dataset raises ValueError for unknown family."""
    try:
        _run_export_test(family="unknown_family")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown table family" in str(e)


def test_export_no_cache_raises() -> None:
    """export_family_dataset raises FileNotFoundError when cache is missing."""
    with (
        patch(
            "defs.taxonomy.probe.exporter.default_probe_cache_path"
        ) as mock_cache_path,
        patch("defs.taxonomy.probe.exporter._query_family_records") as mock_query,
    ):
        mock_cache_path.return_value = Path("/nonexistent/cache.parquet")
        mock_query.return_value = []
        try:
            export_family_dataset("shares_purchased", limit=1)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


def test_export_no_records_raises() -> None:
    """export_family_dataset raises ValueError when no records match."""
    import tempfile

    tmpdir = tempfile.mkdtemp()
    cache_path = Path(tmpdir) / "probe.parquet"
    pq.write_table(pa.Table.from_pylist([]), cache_path)
    db_path = Path(tmpdir) / "fixture.sqlite"
    db_path.touch()

    with (
        patch("defs.taxonomy.probe.exporter._query_family_records") as mock_query,
        patch(
            "defs.taxonomy.probe.exporter.default_fixture_db_path"
        ) as mock_db_path_fn,
        patch(
            "defs.taxonomy.probe.exporter.default_probe_cache_path"
        ) as mock_cache_path_fn,
    ):
        mock_db_path_fn.return_value = db_path
        mock_cache_path_fn.return_value = cache_path
        mock_query.return_value = []
        try:
            export_family_dataset("shares_purchased", limit=1, db_path=db_path)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No tables found" in str(e)


def test_export_creates_output_file() -> None:
    """export_family_dataset creates the output parquet file."""
    import tempfile

    tmpdir = tempfile.mkdtemp()
    output_path = Path(tmpdir) / "datasets" / "shares_purchased.parquet"
    result = _run_export_test(output_path=output_path)
    assert output_path.exists()
    assert result == output_path


def test_export_atomic_write() -> None:
    """Exported parquet file is valid and can be read back."""
    import tempfile

    tmpdir = tempfile.mkdtemp()
    output_path = Path(tmpdir) / "export.parquet"
    result = _run_export_test(output_path=output_path)
    out_table = pq.read_table(result)
    assert out_table.num_rows == 1
    assert out_table.num_columns == 20


def test_export_multiple_records() -> None:
    """Export with multiple records produces correct number of rows."""
    result = _run_export_test(record_count=3, limit=3)
    out_table = pq.read_table(result)
    assert out_table.num_rows == 3


def test_export_default_output_path() -> None:
    """export_family_dataset uses default output path when not specified."""
    import tempfile
    from unittest.mock import patch as mock_patch

    tmpdir = tempfile.mkdtemp()
    default_out = Path(tmpdir) / "datasets" / "shares_purchased.parquet"
    with (
        mock_patch("defs.taxonomy.probe.exporter.resolve_paths") as mock_resolve,
        mock_patch(
            "defs.taxonomy.probe.exporter.default_probe_cache_path"
        ) as mock_cache_path_fn,
        mock_patch("defs.taxonomy.probe.exporter._query_family_records") as mock_query,
        mock_patch("defs.taxonomy.probe.exporter.stream_document_blobs") as mock_blobs,
    ):
        mock_project = MagicMock()
        mock_artifacts = MagicMock()
        mock_artifacts.joinpath.return_value = default_out
        mock_project.artifacts_root = mock_artifacts
        mock_resolve.return_value = mock_project
        mock_cache_path_fn.return_value = Path(tmpdir) / "probe.parquet"
        mock_query.return_value = _make_mock_records(1)
        mock_blob = MagicMock()
        mock_blob.doc_id = "doc0"
        mock_blob.raw_payload = b"<html><body></body></html>"
        mock_blobs.return_value = [mock_blob]

        cache_path = Path(tmpdir) / "probe.parquet"
        pq.write_table(pa.Table.from_pylist([]), cache_path)
        db_path = Path(tmpdir) / "fixture.sqlite"
        db_path.touch()

        result = export_family_dataset(
            "shares_purchased",
            limit=1,
            db_path=db_path,
        )

    assert result.name == "shares_purchased.parquet"


def test_export_repair_policy_from_spec() -> None:
    """Exported repair_policy matches the TableFamilySpec."""
    result = _run_export_test(family="derivatives_hedging")
    out_table = pq.read_table(result)
    row = out_table.to_pylist()[0]
    spec = FAMILY_SPECS["derivatives_hedging"]
    assert row["repair_policy"] == spec.repair_policy.value


def test_export_reconstructs_html_when_no_blob() -> None:
    """Exported HTML is reconstructed from grid when blob has no matching doc."""
    import tempfile

    tmpdir = tempfile.mkdtemp()
    output_path = Path(tmpdir) / "export.parquet"
    db_path = Path(tmpdir) / "fixture.sqlite"
    db_path.touch()

    cache_path = Path(tmpdir) / "probe.parquet"
    pq.write_table(pa.Table.from_pylist([]), cache_path)

    mock_records = _make_mock_records(1)

    with (
        patch("defs.taxonomy.probe.exporter._query_family_records") as mock_query,
        patch("defs.taxonomy.probe.exporter.stream_document_blobs") as mock_blobs,
        patch(
            "defs.taxonomy.probe.exporter.default_fixture_db_path"
        ) as mock_db_path_fn,
        patch(
            "defs.taxonomy.probe.exporter.default_probe_cache_path"
        ) as mock_cache_path_fn,
    ):
        mock_db_path_fn.return_value = db_path
        mock_cache_path_fn.return_value = cache_path
        mock_query.return_value = mock_records

        mock_blob = MagicMock()
        mock_blob.doc_id = "non_matching_doc"
        mock_blob.raw_payload = b"<html><body></body></html>"
        mock_blobs.return_value = [mock_blob]

        result = export_family_dataset(
            "shares_purchased",
            output_path=output_path,
            limit=1,
            db_path=db_path,
        )

    out_table = pq.read_table(result)
    row = out_table.to_pylist()[0]
    assert len(row["html"]) > 0
    assert "<table>" in row["html"]
