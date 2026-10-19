from pathlib import Path

from edgar_sec.engine.forms.beneficial_ownership.analysis import (
    analyze_case,
    summarize_cases,
)

SAMPLE_XML = """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
  <schemaVersion>X0202</schemaVersion>
  <headerData><submissionType>SCHEDULE 13D</submissionType></headerData>
  <formData>
    <coverPageHeader>
      <securitiesClassTitle>Common Stock</securitiesClassTitle>
      <dateOfEvent>01/02/2024</dateOfEvent>
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
    <signatureInfo><signaturePerson><signatureDetails><signature>/s/ Jane Doe</signature></signatureDetails></signaturePerson></signatureInfo>
  </formData>
</edgarSubmission>"""


def _write_case(tmp_path: Path, xml: str) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_text(xml, encoding="utf-8")
    return case_dir


def test_analysis_counts_fields_and_summarizes_categories(tmp_path: Path) -> None:
    case_dir = _write_case(tmp_path, SAMPLE_XML)
    report = analyze_case(case_dir, {"accession": "0000000001-24-000001"})

    assert report is not None
    assert report["anomalies"] == []
    assert report["field_observations"]["item1"]["populated_occurrences"] == 1
    summary = summarize_cases([report])

    assert summary["case_count"] == 1
    assert summary["anomaly_count"] == 0
    assert summary["field_scorecard"]["issuerName"]["cases_with_value"] == 1
    assert (
        summary["value_frequencies"]["legalProceedings"]["top_values"][0]["value"]
        == "N"
    )


def test_analysis_flags_duplicate_items_and_invalid_checkboxes(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>unknown</legalProceedings>",
    ).replace(
        "</items1To7>",
        "<item1><commentText>second</commentText></item1></items1To7>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    kinds = {item["kind"] for item in report["anomalies"]}
    assert kinds == {"duplicate_narrative_item", "invalid_checkbox_value"}


def test_analysis_flags_cover_values_with_table_residue(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<soleVotingPower>SHARES -0- ------------</soleVotingPower>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"][0]["kind"] == "cover_field_contamination"
    assert report["anomalies"][0]["field"] == "soleVotingPower"


def test_analysis_reports_malformed_xml(tmp_path: Path) -> None:
    report = analyze_case(_write_case(tmp_path, "<edgarSubmission"), {"accession": "a"})

    assert report is not None
    assert report["error"] == "malformed_xml"
    assert report["anomalies"][0]["kind"] == "malformed_xml"


def test_analysis_reports_missing_xml_after_text_rendering(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text("Parsed source", encoding="utf-8")

    report = analyze_case(case_dir, {"accession": "a"})

    assert report is not None
    assert report["error"] == "missing_rendered_xml"
    assert report["anomalies"][0]["kind"] == "missing_rendered_xml"


def test_summary_filters_statutory_unparsed_sections(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "</formData>",
        "<unparsedSections>"
        '<unparsedSection tableIndex="1" role="header">Potential persons who are to respond to the collection of information</unparsedSection>'
        '<unparsedSection tableIndex="2" role="unparsed">Unmapped disclosure data</unparsedSection>'
        "</unparsedSections></formData>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    summary = summarize_cases([report])

    assert summary["unparsed_section_count"] == 2
    assert summary["boilerplate_unparsed_count"] == 1
    assert summary["substantive_unparsed_count"] == 1
    assert summary["unparsed_samples"][0]["snippet"] == "Unmapped disclosure data"
