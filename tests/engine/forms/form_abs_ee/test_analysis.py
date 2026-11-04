from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_abs_ee.analysis import analyze_case, summarize_cases
from tests.engine.forms.form_abs_ee.test_stream import _EX102, _EX103


def _write_case(tmp_path: Path, payload: bytes) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_xml.xml").write_bytes(payload)


def test_analyze_ex102_case(tmp_path: Path) -> None:
    _write_case(tmp_path, _EX102)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    assert rep["anomalies"] == []
    assert rep["form_abs_ee"]["exhibit_kind"] == "EX-102"
    assert rep["form_abs_ee"]["record_count"] == 3


def test_analyze_ex103_case(tmp_path: Path) -> None:
    _write_case(tmp_path, _EX103)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000002"})
    assert rep is not None
    assert rep["form_abs_ee"]["exhibit_kind"] == "EX-103"
    assert rep["form_abs_ee"]["comment_count"] == 2


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000003"})
    assert rep is not None
    assert rep["anomalies"] == ["missing_extracted_xml"]


def test_summarize_aggregates_records(tmp_path: Path) -> None:
    _write_case(tmp_path, _EX102)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    summary = summarize_cases([rep])
    scorecard = summary["form_abs_ee_scorecard"]
    assert scorecard["kind_counts"] == {"EX-102": 1}
    assert scorecard["total_asset_records"] == 3
