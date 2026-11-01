"""Unit tests for beneficial ownership case analyzer."""

from pathlib import Path

from edgar_sec.engine.forms.beneficial_ownership.analysis.case import analyze_case
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections

SAMPLE_XML = """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
  <schemaVersion>X0202</schemaVersion>
  <headerData><submissionType>SCHEDULE 13D</submissionType></headerData>
  <formData>
    <coverPageHeader>
      <securitiesClassTitle>Common Stock</securitiesClassTitle>
      <dateOfEvent>01-02-2024</dateOfEvent>
      <issuerInfo><issuerName>Example Corp</issuerName>
        <issuerCusips><issuerCusipNumber>123456789</issuerCusipNumber></issuerCusips>
      </issuerInfo>
    </coverPageHeader>
    <reportingPersons><reportingPersonInfo>
      <reportingPersonName>Jane Doe</reportingPersonName>
      <legalProceedings>N</legalProceedings>
      <typeOfReportingPerson>IN</typeOfReportingPerson>
    </reportingPersonInfo></reportingPersons>
    <items1To7><item1><commentText>Source-faithful text</commentText></item1></items1To7>
    <signatureInfo><signaturePerson><signatureDetails><signature>/s/ Jane Doe</signature><title>Director</title><date>01-02-2024</date></signatureDetails></signaturePerson></signatureInfo>
  </formData>
</edgarSubmission>"""


def _write_case(tmp_path: Path, xml: str) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_text(xml, encoding="utf-8")
    return case_dir


def test_analysis_counts_fields_and_evaluates_case(tmp_path: Path) -> None:
    case_dir = _write_case(tmp_path, SAMPLE_XML)
    report = analyze_case(case_dir, {"accession": "0000000001-24-000001"})

    assert report is not None
    assert report["anomalies"] == []
    assert report["field_observations"]["item1"]["populated_occurrences"] == 1


def test_analysis_reports_malformed_xml(tmp_path: Path) -> None:
    case_dir = _write_case(tmp_path, "<not-xml>")
    report = analyze_case(case_dir, {"accession": "0000000001-24-000001"})

    assert report is not None
    assert report["error"] == "malformed_xml"
    assert report["anomalies"][0]["kind"] == "malformed_xml"


def test_analysis_reports_missing_xml_after_text_rendering(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text("rendered body", encoding="utf-8")

    report = analyze_case(case_dir, {"accession": "0000000001-24-000001"})

    assert report is not None
    assert report["error"] == "missing_rendered_xml"
    assert report["anomalies"][0]["kind"] == "missing_rendered_xml"


def test_analysis_loads_unparsed_sidecar_and_flags_unresolved_scalar(
    tmp_path: Path,
) -> None:
    case_dir = _write_case(tmp_path, SAMPLE_XML)
    records = (
        {
            "role": "item5.unparsed",
            "content_type": "text/plain",
            "content": "Unparsed subsection text",
            "start_offset": 12,
            "end_offset": 36,
        },
        {
            "role": "normalization.unresolved:aggregateAmountOwned",
            "content_type": "text/plain",
            "content": "12 shares and more",
        },
    )
    (case_dir / "operations" / "unparsed_sections.json").write_bytes(
        serialize_unparsed_sections(records)
    )

    report = analyze_case(case_dir, {"accession": "a"})

    assert report is not None
    assert [section["role"] for section in report["unparsed_sections"]] == [
        "item5.unparsed",
        "normalization.unresolved:aggregateAmountOwned",
    ]
    assert report["unparsed_sections"][0]["start_offset"] == 12
    assert {item["kind"] for item in report["anomalies"]} == {
        "unresolved_scalar_normalization"
    }
    assert report["review_signals"][0]["kind"] == "unparsed_narrative_content"
