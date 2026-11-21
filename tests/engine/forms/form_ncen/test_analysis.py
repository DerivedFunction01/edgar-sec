"""Tests for the Form N-CEN review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_ncen.analysis import analyze_case, summarize_cases

_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ncen">
  <headerData><submissionType>N-CEN</submissionType></headerData>
  <formData><registrantInfo>
    <registrantFullName>ACME INCOME FUND</registrantFullName>
    <investmentCompFileNo>811-00000</investmentCompFileNo>
    <registrantCik>0000123456</registrantCik>
    <registrantClassificationType>N-2</registrantClassificationType>
    <directors><director><directorName>JANE DOE</directorName></director>
    </directors>
  </registrantInfo></formData>
</edgarSubmission>
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000123456-25-000001--N-CEN"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_bytes(_XML)
    return case_dir


def test_analyze_case_clean(tmp_path: Path) -> None:
    """A complete case yields no anomalies and full core fields."""
    report = analyze_case(_case(tmp_path))
    assert report is not None
    assert report["anomalies"] == []
    assert report["director_rows"] == 1
    assert all(report["core_fields"].values())


def test_summarize_cases() -> None:
    """The summary aggregates director rows and the scorecard."""
    summary = summarize_cases(
        [
            {
                "core_fields": {"registrant_name": True},
                "anomalies": [],
                "review_signals": [],
                "director_rows": 8,
            }
        ]
    )
    assert summary["family"] == "N-CEN"
    assert summary["director_rows_total"] == 8
