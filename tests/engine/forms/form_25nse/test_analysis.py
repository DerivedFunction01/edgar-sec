from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_25nse.analysis import analyze_case, summarize_cases
from tests.engine.forms.form_25nse.test_xml_parser import _BARE_XML


def _write_case(tmp_path: Path, payload: bytes) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_xml.xml").write_bytes(payload)


def test_analyze_complete_case(tmp_path: Path) -> None:
    _write_case(tmp_path, _BARE_XML)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    assert rep["anomalies"] == []
    assert rep["form_25nse"]["schema_version"] == "X0203"
    assert rep["form_25nse"]["file_number"] == "001-00001"
    assert all(rep["core_fields"].values())


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000002"})
    assert rep is not None
    assert rep["anomalies"] == ["missing_extracted_xml"]


def test_analyze_off_vocabulary_provision(tmp_path: Path) -> None:
    payload = _BARE_XML.replace(b"17 CFR 240.12d2-2(a)(2)", b"17 CFR 240.12d2-2(c)")
    _write_case(tmp_path, payload)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000003"})
    assert rep is not None
    assert any(a.startswith("rule_provision_off_vocabulary") for a in rep["anomalies"])


def test_summarize_aggregates(tmp_path: Path) -> None:
    _write_case(tmp_path, _BARE_XML)
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000001"})
    assert rep is not None
    summary = summarize_cases([rep])
    assert summary["case_count"] == 1
    scorecard = summary["form_25nse_scorecard"]
    assert scorecard["schema_version_counts"] == {"X0203": 1}
    assert scorecard["parsed_count"] == 1
