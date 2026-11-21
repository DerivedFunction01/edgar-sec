from __future__ import annotations

from edgar_sec.pipelines.document_inventory.review_artifacts.comparison import (
    compare_review_analysis_runs,
)


def test_comparison_keys_rows_and_separates_changed_inputs() -> None:
    key = ("0000004977-11-000045", "https://www.sec.gov/index", "a" * 64)
    base_case = {
        "parser_fingerprint": "parser-old",
        "observations": {"status": "parsed", "bundle_url": "old.txt"},
        "entries": [
            {
                "table_kind": "document_format",
                "row_ordinal": "0",
                "filename": "old.html",
            }
        ],
    }
    new_case = {
        "parser_fingerprint": "parser-new",
        "observations": {"status": "parsed", "bundle_url": "new.txt"},
        "entries": [
            {
                "table_kind": "document_format",
                "row_ordinal": "0",
                "filename": "new.html",
            }
        ],
    }
    result = compare_review_analysis_runs(
        {"run_id": "old", "case_map": {key: base_case}},
        {"run_id": "new", "case_map": {key: new_case}},
    )

    assert result["shared_input_count"] == 1
    assert result["row_change_count"] == 1
    assert result["parser_fingerprint_changes"][0]["base"] == "parser-old"
    assert result["observation_change_count"] == 1
    assert result["input_changed_accessions"] == []
