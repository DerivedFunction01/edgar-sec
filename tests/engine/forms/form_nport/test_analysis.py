"""Tests for the Form N-PORT review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_nport.analysis import analyze_case, summarize_cases

_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData><submissionType>NPORT-P</submissionType></headerData>
  <formData>
    <genInfo><regName>ACME FUND TRUST</regName>
    <seriesName>ACME GROWTH FUND</seriesName>
    <repPdEnd>2025-03-31</repPdEnd></genInfo>
    <fundInfo><netAssets>975.00</netAssets></fundInfo>
    <invstOrSecs><invstOrSec><name>ACME CORP</name><title>COM</title>
    <cusip>001000000</cusip><valUSD>500.00</valUSD></invstOrSec></invstOrSecs>
  </formData>
</edgarSubmission>
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000123456-25-000001--NPORT-P"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_bytes(_XML)
    return case_dir


def test_analyze_case_clean(tmp_path: Path) -> None:
    """A complete case yields no anomalies and full core fields."""
    report = analyze_case(_case(tmp_path))
    assert report is not None
    assert report["anomalies"] == []
    assert report["investment_rows"] == 1
    assert all(report["core_fields"].values())


def test_analyze_case_missing_xml(tmp_path: Path) -> None:
    """A case without rendered XML reports the missing-xml anomaly."""
    case_dir = tmp_path / "empty--NPORT-P"
    case_dir.mkdir()
    report = analyze_case(case_dir)
    assert report is not None
    assert report["anomalies"] == ["missing_extracted_xml"]


def test_summarize_cases() -> None:
    """The summary aggregates rows and builds the field scorecard."""
    summary = summarize_cases(
        [
            {
                "core_fields": {"registrant_name": True},
                "anomalies": [],
                "review_signals": [],
                "investment_rows": 3,
            }
        ]
    )
    assert summary["family"] == "N-PORT"
    assert summary["case_count"] == 1
    assert summary["investment_rows_total"] == 3
