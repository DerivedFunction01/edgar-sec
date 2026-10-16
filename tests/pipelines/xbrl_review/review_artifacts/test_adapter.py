"""Tests for XbrlReviewAdapter and review artifact generation."""

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.xbrl_review.paths import SOLVED_NODES_FILE
from edgar_sec.pipelines.xbrl_review.review_artifacts.adapter import XbrlReviewAdapter
from edgar_sec.pipelines.xbrl_review.schemas import SOLVED_NODES_SCHEMA


def test_adapter_dataset_name() -> None:
    """Verify adapter identifies as xbrl dataset."""
    adapter = XbrlReviewAdapter()
    assert adapter.dataset_name == "xbrl"


def test_build_review_artifacts_and_compare(tmp_path: Path) -> None:
    """Verify review generation and case diff comparison across runs."""
    adapter = XbrlReviewAdapter()
    run_a = tmp_path / "run-A"
    count_a = adapter.build_review_artifacts(
        fixture_id="seed",
        output_dir=run_a,
        limit=2,
    )
    assert count_a == 2
    assert (run_a / "manifest.jsonl").is_file()
    assert (run_a / "cases").is_dir()

    case_dirs = list((run_a / "cases").iterdir())
    assert len(case_dirs) == 2
    sample_cid = case_dirs[0].name
    assert (case_dirs[0] / SOLVED_NODES_FILE).is_file()

    same_diff = adapter.compare_case(sample_cid, case_dirs[0], case_dirs[0])
    assert same_diff.status == "unchanged"

    add_diff = adapter.compare_case(sample_cid, None, case_dirs[0])
    assert add_diff.status == "added"
    rem_diff = adapter.compare_case(sample_cid, case_dirs[0], None)
    assert rem_diff.status == "removed"

    run_b = tmp_path / "run-B"
    adapter.build_review_artifacts(
        fixture_id="seed",
        output_dir=run_b,
        limit=2,
    )
    mod_case_dir = run_b / "cases" / sample_cid
    tbl = pa.Table.from_pylist(
        [
            {
                "accession": sample_cid,
                "concept_qname": "us-gaap:NovelConcept",
                "period": "FY2024",
                "firm": "TEST",
                "cik": 12345,
                "prime_head": "H_UNKNOWN",
                "modifiers_json": "[]",
                "resolution_tier": "EVIDENCE_KB",
                "reported_value": 999.0,
                "derived_value": 999.0,
                "derivation_path": "H_UNKNOWN",
                "latency_ms": 0.1,
            }
        ],
        schema=SOLVED_NODES_SCHEMA,
    )
    write_parquet_table(tbl, mod_case_dir / SOLVED_NODES_FILE)
    chg_diff = adapter.compare_case(sample_cid, case_dirs[0], mod_case_dir)
    assert chg_diff.status == "changed"
    assert chg_diff.added_count > 0 or chg_diff.removed_count > 0
