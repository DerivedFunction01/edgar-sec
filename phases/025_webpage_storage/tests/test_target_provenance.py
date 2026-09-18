"""Offline tests for Phase 2.5 target-plan provenance and fallback locators."""

from __future__ import annotations

import importlib
import json

import pytest

from defs.storage import pa, write_table_atomic

targets = importlib.import_module("phases.025_webpage_storage.core.targets")


def _write_bundle(
    root,
    locator_extra: dict | None,
    target_extra: dict | None,
) -> None:
    """Write a minimal Phase 02 plan bundle with optional provenance columns."""
    locator_row = {
        "document_locator_key": "loc-1",
        "form": "10-K",
        "representative_cik": "0000000001",
        "representative_accession": "000000000100000001",
        "primary_document": "0000000001-24-000001.txt",
        "document_path": "0000000001-24-000001.txt",
        "archive_url": (
            "https://www.sec.gov/Archives/edgar/data/1/"
            "000000000100000001/0000000001-24-000001.txt"
        ),
    }
    target_row = {
        "occurrence_id": "occ-1",
        "document_locator_key": "loc-1",
        "source_cik": "0000000001",
        "accession": "000000000100000001",
        "form": "10-K",
        "filing_date": "1998-10-21",
        "report_date": "1998-09-30",
        "document_path": "0000000001-24-000001.txt",
    }
    if locator_extra:
        locator_row.update(locator_extra)
    if target_extra:
        target_row.update(target_extra)
    (root / "targets" / "form=10-K").mkdir(parents=True, exist_ok=True)
    write_table_atomic(
        pa.Table.from_pylist([locator_row]), root / "locator_groups.parquet"
    )
    write_table_atomic(
        pa.Table.from_pylist([target_row]),
        root / "targets" / "form=10-K" / "data.parquet",
    )
    (root / "plan.json").write_text(
        json.dumps({"scope": "full", "plan_schema_version": 1}), encoding="utf-8"
    )
    (root / "selection_report.json").write_text(
        json.dumps({"active_targets_count": 1}), encoding="utf-8"
    )


def test_load_targets_accepts_document_path_provenance(tmp_path):
    root = tmp_path / "plan"
    _write_bundle(
        root,
        {"document_path_source": "submission_bundle"},
        {"document_path_source": "submission_bundle"},
    )
    locators, occurrences, _plan = targets.load_targets(root)

    assert locators[0].document_path_source == "submission_bundle"
    assert occurrences[0].document_path == "0000000001-24-000001.txt"


def test_load_targets_rejects_provenance_mismatch(tmp_path):
    root = tmp_path / "plan"
    _write_bundle(
        root,
        {"document_path_source": "submission_bundle"},
        {"document_path_source": "primary_document"},
    )
    with pytest.raises(ValueError, match="provenance disagrees"):
        targets.load_targets(root)


def test_load_targets_rejects_partial_provenance(tmp_path):
    root = tmp_path / "plan"
    _write_bundle(root, {"document_path_source": "submission_bundle"}, None)
    with pytest.raises(ValueError, match="provenance disagrees"):
        targets.load_targets(root)


def test_load_targets_accepts_legacy_bundle_without_provenance(tmp_path):
    root = tmp_path / "plan"
    _write_bundle(root, None, None)
    locators, _occurrences, _plan = targets.load_targets(root)

    assert locators[0].document_path_source is None
