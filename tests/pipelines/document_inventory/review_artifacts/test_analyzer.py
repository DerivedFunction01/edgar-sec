from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_inventory.review_artifacts.analyzer import (
    analyze_review_runs,
)

_FIELDS = (
    "entry_id",
    "accession",
    "table_kind",
    "row_ordinal",
    "sequence",
    "document_type",
    "document_label",
    "description",
    "filename",
    "href",
    "archive_url",
    "byte_size",
)
_ACCESSION = "0000004977-11-000045"
_REQUEST_URL = (
    "https://www.sec.gov/Archives/edgar/data/4977/000000497711000045-index.html"
)
_ROOT = "/Archives/edgar/data/4977/000000497711000045/"
_BUNDLE_URL = "https://www.sec.gov/Archives/edgar/data/4977/000000497711000045.txt"


def _entry(
    ordinal: int,
    sequence: int,
    document_type: str,
    filename: str,
    href: str,
    archive_url: str,
) -> dict[str, str | int]:
    return {
        "entry_id": f"entry-{ordinal}",
        "accession": _ACCESSION,
        "table_kind": "document_format",
        "row_ordinal": ordinal,
        "sequence": sequence,
        "document_type": document_type,
        "document_label": filename,
        "description": "",
        "filename": filename,
        "href": href,
        "archive_url": archive_url,
        "byte_size": 100,
    }


def _write_run(
    root: Path,
    run_id: str,
    entries: list[dict],
    *,
    accession: str = _ACCESSION,
    response_sha256: str = "a" * 64,
    request_url: str = _REQUEST_URL,
    bundle_url: str | None = _BUNDLE_URL,
) -> Path:
    case = root / run_id / "cases" / f"{accession}--case"
    case.mkdir(parents=True)
    entries_path = case / "entries.csv"
    with entries_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(entries)
    observations_path = case / "observations.json"
    observations_path.write_text(
        json.dumps(
            {
                "accession": accession,
                "response_sha256": response_sha256,
                "status": "parsed",
                "entry_count": len(entries),
                "bundle_url": bundle_url,
                "diagnostics": {"items": [], "suppressed_count": 0},
            }
        ),
        encoding="utf-8",
    )
    record = {
        "review_id": run_id,
        "fixture_id": "fixture-1",
        "accession": accession,
        "request_url": request_url,
        "response_sha256": response_sha256,
        "parser_fingerprint": f"parser-{run_id}",
        "status": "parsed",
        "entry_count": len(entries),
        "outputs": {
            "entries.csv": {
                "path": str(entries_path.relative_to(root / run_id)),
                "sha256": file_sha256(entries_path),
            },
            "observations.json": {
                "path": str(observations_path.relative_to(root / run_id)),
                "sha256": file_sha256(observations_path),
            },
        },
    }
    (root / run_id / "manifest.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    return root / run_id


def _form4_entries() -> list[dict]:
    xsl = f"https://www.sec.gov{_ROOT}xslF345X03/primary_doc.xml"
    flat = f"https://www.sec.gov{_ROOT}primary_doc.xml"
    exhibit = f"https://www.sec.gov{_ROOT}0002.txt"
    return [
        _entry(0, 1, "4", "primary_doc.html", xsl, xsl),
        _entry(1, 1, "4", "primary_doc.xml", flat, flat),
        _entry(2, 2, "EX-99.1", "0002.txt", exhibit, exhibit),
    ]


def test_analyze_reports_form4_paths_sequences_and_route(tmp_path: Path) -> None:
    entries = _form4_entries()
    run = _write_run(tmp_path, "review-a", entries)

    report = analyze_review_runs([run])

    codes = [finding["code"] for finding in report["findings"]]
    assert report["network_requests"] == 0
    assert report["finding_counts"]["form4_alternative_primary_paths"] == 1
    assert report["finding_counts"]["duplicate_sequence"] == 1
    assert report["finding_counts"]["sequence_2_or_3_exhibit"] == 1
    assert report["acquisition_routes"]["direct"] == 3
    assert "form4_alternative_primary_paths" in codes
    assert any(
        finding["code"] == "acquisition_route" and finding["route"] == "direct"
        for finding in report["findings"]
    )


def test_analyze_marks_alternate_cik_href_unresolved(tmp_path: Path) -> None:
    accession = "0000001000-24-000001"
    request_url = (
        "https://www.sec.gov/Archives/edgar/data/1000/000000100024000001-index.html"
    )
    href = (
        "https://www.sec.gov/Archives/edgar/data/9999/"
        "000000100024000001/primary_doc.xml"
    )
    row = _entry(0, 1, "4", "primary_doc.xml", href, "")
    row["accession"] = accession
    run = _write_run(
        tmp_path,
        "review-b",
        [row],
        accession=accession,
        request_url=request_url,
        bundle_url=None,
    )

    report = analyze_review_runs([run])

    assert report["finding_counts"]["archive_cik_differs_from_source"] == 1
    assert report["finding_counts"]["acquisition_route"] == 1
    route = next(
        item for item in report["findings"] if item["code"] == "acquisition_route"
    )
    assert route["route"] == "observed_href_unresolved"


def test_analyze_joins_form_from_fixture_plan_without_replaying_source(
    tmp_path: Path,
) -> None:
    request_url = (
        "https://www.sec.gov/Archives/edgar/data/4977/000000497711000045-index.html"
    )
    rows = [
        _entry(
            0,
            1,
            "EX-99.1",
            "0001.txt",
            "/Archives/edgar/data/4977/000000497711000045/0001.txt",
            "",
        ),
        _entry(
            1,
            2,
            "10-K405",
            "0002.txt",
            "/Archives/edgar/data/4977/000000497711000045/0002.txt",
            "",
        ),
    ]
    run_root = tmp_path / "document_inventory" / "review-runs"
    run = _write_run(run_root, "review-inversion", rows)
    fixture_root = tmp_path / "document_inventory" / "fixtures" / "fixture-1"
    fixture_root.mkdir(parents=True)
    (fixture_root / "manifest.json").write_text(
        json.dumps(
            {
                "details": {
                    "contributions": [{"plan_id": "plan-one"}],
                }
            }
        ),
        encoding="utf-8",
    )
    targets = (
        tmp_path / "filing_catalog" / "plans" / "plan-one" / "targets" / "form=10-K"
    )
    targets.mkdir(parents=True)
    pq.write_table(
        pa.table({"accession": [_ACCESSION], "form": ["10-K"]}),
        targets / "data.parquet",
    )

    report = analyze_review_runs([run], artifacts_root=tmp_path)

    inversion = next(
        item
        for item in report["findings"]
        if item["code"] == "sequence_one_exhibit_inversion"
    )
    assert inversion["filing_forms"] == ["10-K"]
    assert inversion["later_form_rows"][0]["sequence"] == "2"


def test_analyze_uses_bundle_sequence_for_directory_only_href(tmp_path: Path) -> None:
    row = _entry(0, 2, "EX-10", "", "/Archives/edgar/data/4977/", "")
    bundle_url = "https://www.sec.gov/Archives/edgar/data/9999/000000497711000045.txt"
    run = _write_run(tmp_path, "review-directory", [row], bundle_url=bundle_url)

    report = analyze_review_runs([run])

    route = next(
        item for item in report["findings"] if item["code"] == "acquisition_route"
    )
    assert route["route"] == "bundle_sequence"
    assert report["finding_counts"]["directory_only_href"] == 1
    assert report["finding_counts"]["missing_filename"] == 1
    assert report["finding_counts"]["bundle_archive_cik_differs_from_source"] == 1


def test_analyze_compares_rows_only_for_identical_inputs(tmp_path: Path) -> None:
    first = _write_run(tmp_path, "review-base", _form4_entries())
    updated = _form4_entries()
    updated[0]["filename"] = "primary_doc_v2.html"
    newer = _write_run(tmp_path, "review-new", updated)
    changed = _write_run(
        tmp_path,
        "review-input-changed",
        _form4_entries(),
        response_sha256="b" * 64,
    )

    report = analyze_review_runs([first, newer, changed])

    same_input_diff = report["comparisons"][0]
    changed_input_diff = report["comparisons"][1]
    assert same_input_diff["shared_input_count"] == 1
    assert same_input_diff["row_change_count"] == 1
    assert changed_input_diff["shared_input_count"] == 0
    assert changed_input_diff["input_changed_accessions"] == [_ACCESSION]


def test_analyze_rejects_tampered_review_output(tmp_path: Path) -> None:
    run = _write_run(tmp_path, "review-tampered", _form4_entries())
    entries = next((run / "cases").iterdir()) / "entries.csv"
    entries.write_text(entries.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        analyze_review_runs([run])


def test_analyze_rejects_run_path_escape(tmp_path: Path) -> None:
    run = _write_run(tmp_path, "review-escape", _form4_entries())
    manifest = run / "manifest.jsonl"
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["outputs"]["entries.csv"]["path"] = "../outside.csv"
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes its run directory"):
        analyze_review_runs([run])
