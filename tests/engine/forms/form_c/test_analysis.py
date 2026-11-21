from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_c.analysis import analyze_case, summarize_cases
from tests.engine.forms.form_c.test_xml_parser import _OFFERING_XML


def _write_case(tmp_path: Path, payload: bytes) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_xml.xml").write_bytes(payload)


def test_analyze_offering_case(tmp_path: Path) -> None:
    _write_case(tmp_path, _OFFERING_XML)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    assert rep["anomalies"] == []
    assert rep["form_c"]["kind"] == "offering"
    assert rep["form_c"]["submission_type"] == "C"


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000002"})
    assert rep is not None
    assert rep["anomalies"] == ["missing_extracted_xml"]


def test_summarize_counts_kinds(tmp_path: Path) -> None:
    _write_case(tmp_path, _OFFERING_XML)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    summary = summarize_cases([rep])
    assert summary["form_c_scorecard"]["kind_counts"] == {"offering": 1}
    assert summary["form_c_scorecard"]["offering_information_count"] == 1
