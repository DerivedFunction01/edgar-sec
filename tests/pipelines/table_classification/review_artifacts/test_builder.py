"""Review runs replay fixtures and verdict stale stamps."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.table_classification.fixture_store.models import ProductStamps
from edgar_sec.pipelines.table_classification.review_artifacts.adapter import (
    ClassificationReviewAdapter,
)
from edgar_sec.pipelines.table_classification.review_artifacts.builder import (
    build_review_artifacts,
    read_case_classifications,
)
from tests.pipelines.table_classification.fixture_store.test_capture_reader import (
    _STAMPS,
    _capture,
)


def test_review_run_classifies_every_case(tmp_path: Path) -> None:
    _capture(tmp_path)
    result = build_review_artifacts(tmp_path, "fx1", expected_stamps=_STAMPS)
    assert result.exit_code == 0
    assert result.summary.total == 1
    assert result.summary.completed == 1
    assert result.summary.tables == 3
    case_dirs = list((result.output_root / "cases").iterdir())
    assert len(case_dirs) == 1
    rows = read_case_classifications(case_dirs[0])
    assert rows is not None and len(rows) == 3
    refused = [row for row in rows if row["tier"] == "genre_refusal"]
    assert len(refused) == 2
    assert all(row["kind"] == "statement" for row in rows)
    assert all(row["accession"] == "0000000000-00-000000" for row in rows)
    assert all("assembled_family" in row and "mechanism" in row for row in rows)
    assert all(isinstance(row["evidence"], str) for row in rows)
    payload = json.loads((case_dirs[0] / "classifications.json").read_text())
    assert len(payload["geometry_inventory"]) == 3
    assert all(
        row["provenance_route"] == "render_to_txt"
        for row in payload["geometry_inventory"]
    )
    manifest = (result.output_root / "manifest.jsonl").read_text(encoding="utf-8")
    assert json.loads(manifest.strip())["status"] == "completed"


def test_review_run_verdicts_a_stale_fixture(tmp_path: Path) -> None:
    _capture(tmp_path)
    stale = ProductStamps(
        normalize_version="normalize-9", renderer_version="r9", page_policy="strip"
    )
    result = build_review_artifacts(tmp_path, "fx1", expected_stamps=stale)
    assert result.exit_code == 1
    assert result.summary.stale_fixture == 1
    assert result.summary.completed == 0


def test_adapter_lists_and_compares(tmp_path: Path) -> None:
    _capture(tmp_path)
    adapter = ClassificationReviewAdapter()
    fixtures = adapter.list_fixtures(tmp_path)
    assert fixtures[0]["fixture_id"] == "fx1"
    first = build_review_artifacts(tmp_path, "fx1")
    second = build_review_artifacts(tmp_path, "fx1")
    case_id = next((first.output_root / "cases").iterdir()).name
    diff = adapter.compare_case(
        case_id,
        first.output_root / "cases" / case_id,
        second.output_root / "cases" / case_id,
    )
    assert diff.status == "unchanged"
