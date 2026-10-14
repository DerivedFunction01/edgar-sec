"""Unit tests for XbrlReviewAdapter and review artifact generation."""

from pathlib import Path
from edgar_sec.engine.xbrl.storage.review_artifacts.adapter import (
    XbrlReviewAdapter,
)
from edgar_sec.infra.storage.atomic import atomic_write_json


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
    assert (case_dirs[0] / "solved_nodes.json").is_file()

    # Compare identical case
    same_diff = adapter.compare_case(sample_cid, case_dirs[0], case_dirs[0])
    assert same_diff.status == "unchanged"

    # Compare case addition and removal
    add_diff = adapter.compare_case(sample_cid, None, case_dirs[0])
    assert add_diff.status == "added"
    rem_diff = adapter.compare_case(sample_cid, case_dirs[0], None)
    assert rem_diff.status == "removed"

    # Compare modified case
    run_b = tmp_path / "run-B"
    adapter.build_review_artifacts(
        fixture_id="seed",
        output_dir=run_b,
        limit=2,
    )
    mod_case_dir = run_b / "cases" / sample_cid
    atomic_write_json(
        mod_case_dir / "solved_nodes.json",
        [{"concept_qname": "us-gaap:NovelConcept", "value": 999.0}],
    )
    chg_diff = adapter.compare_case(sample_cid, case_dirs[0], mod_case_dir)
    assert chg_diff.status == "changed"
    assert chg_diff.added_count > 0 or chg_diff.removed_count > 0
