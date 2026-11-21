"""Tests for the Form N-MFP review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_nmfp.analysis import analyze_case, summarize_cases

_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp3">
  <headerData><submissionType>N-MFP3</submissionType></headerData>
  <formData>
    <generalInfo><reportDate>2025-06-30</reportDate>
    <registrantFullName>ACME TRUST</registrantFullName>
    <nameOfSeries>ACME GOVERNMENT FUND</nameOfSeries>
    <seriesId>S000000001</seriesId></generalInfo>
    <scheduleOfPortfolioSecuritiesInfo>
      <nameOfIssuer>US TREASURY</nameOfIssuer><titleOfIssuer>T-BILL</titleOfIssuer>
      <CUSIPMember>912797PU5</CUSIPMember>
    </scheduleOfPortfolioSecuritiesInfo>
  </formData>
</edgarSubmission>
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000123456-25-000001--N-MFP3"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_bytes(_XML)
    return case_dir


def test_analyze_case_clean(tmp_path: Path) -> None:
    """A complete case yields no anomalies and the generation."""
    report = analyze_case(_case(tmp_path))
    assert report is not None
    assert report["anomalies"] == []
    assert report["security_rows"] == 1
    assert report["generation"] == 3


def test_summarize_cases() -> None:
    """The summary aggregates security rows and the scorecard."""
    summary = summarize_cases(
        [
            {
                "core_fields": {"series_name": True},
                "anomalies": [],
                "review_signals": [],
                "security_rows": 12,
            }
        ]
    )
    assert summary["family"] == "N-MFP"
    assert summary["security_rows_total"] == 12
