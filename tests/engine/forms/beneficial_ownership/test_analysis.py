from pathlib import Path

from edgar_sec.engine.forms.beneficial_ownership.analysis import (
    analyze_case,
    summarize_cases,
)
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
    assert {item["kind"] for item in report["anomalies"]} == {
        "cover_field_contamination"
    }


def test_analysis_flags_invalid_numeric_fields_and_cusips(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<issuerCusipNumber>123456789</issuerCusipNumber>",
        "<issuerCusipNumber>12ABC</issuerCusipNumber>",
    ).replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<aggregateAmountOwned>12 shares and more</aggregateAmountOwned>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert {item["kind"] for item in report["anomalies"]} == {
        "invalid_cusip",
        "invalid_numeric_cover_value",
    }


def test_analysis_accepts_cover_numbers_with_footnotes_and_zero_dashes(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<soleVotingPower>-0-</soleVotingPower>"
        "<aggregateAmountOwned>12,345 (1)(2)</aggregateAmountOwned>"
        "<percentOfClass>43.9%**</percentOfClass>"
        "<percentOfClass>16.50% (b)</percentOfClass>"
        "<percentOfClass>50%3</percentOfClass>"
        "<sharedVotingPower>None</sharedVotingPower>"
        "<sharedDispositivePower>-</sharedDispositivePower>"
        "<soleDispositivePower>12,345 (Item 5)</soleDispositivePower>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"] == []


def test_analysis_accepts_qualified_cover_numbers_as_review_signals(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<aggregateAmountOwned>13,195,000 shares of common stock</aggregateAmountOwned>"
        "<percentOfClass>30% based on 90 million common stock shares</percentOfClass>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"] == []
    assert {signal["kind"] for signal in report["review_signals"]} == {
        "qualified_numeric_cover_value"
    }


def test_analysis_classifies_unavailable_cusip_separately(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<issuerCusipNumber>123456789</issuerCusipNumber>",
        "<issuerCusipNumber>None.</issuerCusipNumber>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert [item["kind"] for item in report["anomalies"]] == [
        "unavailable_cusip_emitted"
    ]


def test_analysis_classifies_eight_character_cusip_as_source_variation(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<issuerCusipNumber>123456789</issuerCusipNumber>",
        "<issuerCusipNumber>001-33968</issuerCusipNumber>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"] == []
    assert [item["kind"] for item in report["review_signals"]] == ["short_cusip_value"]


def test_analysis_accepts_descriptive_share_values_with_numeric_evidence(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<aggregateAmountOwned>28,833,831 shares (including 3,794,979 shares "
        "issuable upon exercise of warrants)</aggregateAmountOwned>"
        "<soleVotingPower>578,231 (including 300,000 votes from Series A "
        "preferred stock)</soleVotingPower>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"] == []
    assert len(report["review_signals"]) == 2


def test_analysis_detects_flattened_items_and_missing_signatures(
    tmp_path: Path,
) -> None:
    item2_body = (
        "(a) Filing person.\n(b) Business address.\n(c) Business description.\n" * 5
    )
    item5_body = "(a) Ownership.\n(b) Powers.\n(c) Transactions.\n" * 8
    xml = SAMPLE_XML.replace(
        "<items1To7><item1><commentText>Source-faithful text</commentText></item1></items1To7>",
        "<items1To7>"
        f"<item2><filingPersonName>{item2_body}"
        "</filingPersonName></item2>"
        f"<item5><percentageOfClassSecurities>{item5_body}"
        "</percentageOfClassSecurities></item5>"
        "<item7><filedExhibits>SIGNATURES Dated: January 2, 2024 "
        "/s/ Jane Doe</filedExhibits></item7></items1To7>",
    ).replace(
        "<signatureInfo><signaturePerson><signatureDetails>"
        "<signature>/s/ Jane Doe</signature><title>Director</title>"
        "<date>01-02-2024</date></signatureDetails></signaturePerson>"
        "</signatureInfo>",
        "",
    )
    report = _analyze_case_with_source(
        tmp_path,
        xml,
        "SIGNATURES\nDated: January 2, 2024\n/s/ Jane Doe",
    )

    assert report is not None
    assert {(item["kind"], item.get("field")) for item in report["anomalies"]} == {
        ("flattened_narrative_field", "item2.filingPersonName"),
        ("flattened_narrative_field", "item5.percentageOfClassSecurities"),
        ("signature_contained_in_narrative_item", "item7"),
        ("signature_missing_from_xml", None),
        ("missing_required_schema_field", "signatureInfo"),
    }


def test_analysis_does_not_flag_signature_instructions_as_missing_signatures(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<signatureInfo><signaturePerson><signatureDetails>"
        "<signature>/s/ Jane Doe</signature></signatureDetails></signaturePerson>"
        "</signatureInfo>",
        "",
    )
    report = _analyze_case_with_source(
        tmp_path,
        xml,
        "SIGNATURES\nDated: January 2, 2024\n"
        "The original statement shall be signed by each person or representative.",
    )

    assert report is not None
    assert "signature_missing_from_xml" not in {
        item["kind"] for item in report["anomalies"]
    }


def test_analysis_detects_cover_row_label_leakage(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<soleDispositivePower>9 PERSON 906,245 WITH</soleDispositivePower>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert [(item["kind"], item["field"]) for item in report["anomalies"]] == [
        ("cover_field_contamination", "soleDispositivePower")
    ]


def test_summary_counts_anomaly_occurrences_and_distinct_cases(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<aggregateAmountOwned>not numeric one</aggregateAmountOwned>"
        "<aggregateAmountOwned>not numeric two</aggregateAmountOwned>",
    )
    first = analyze_case(_write_case(tmp_path / "first", xml), {"accession": "a"})
    second = analyze_case(_write_case(tmp_path / "second", xml), {"accession": "b"})
    assert first is not None and second is not None

    summary = summarize_cases([first, second])

    assert summary["anomaly_count"] == 4
    assert summary["anomaly_summary"]["kind_counts"]["invalid_numeric_cover_value"] == 4
    assert (
        summary["anomaly_summary"]["kind_case_counts"]["invalid_numeric_cover_value"]
        == 2
    )
    assert (
        summary["anomaly_summary"]["field_counts"][
            "invalid_numeric_cover_value:aggregateAmountOwned"
        ]
        == 4
    )
    assert (
        summary["anomaly_summary"]["field_case_counts"][
            "invalid_numeric_cover_value:aggregateAmountOwned"
        ]
        == 2
    )


def _analyze_case_with_source(tmp_path: Path, xml: str, source_text: str) -> dict:
    case_dir = _write_case(tmp_path, xml)
    (case_dir / "operations" / "render_to_txt.txt").write_text(
        source_text, encoding="utf-8"
    )
    return analyze_case(case_dir, {"accession": "a"})


def test_analysis_identifies_narrative_item_leakage_in_cover_values(
    tmp_path: Path,
) -> None:
    xml = SAMPLE_XML.replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings>"
        "<aggregateAmountOwned>12,345 Item 4. Purpose of Transaction</aggregateAmountOwned>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert report["anomalies"][0]["kind"] == "boilerplate_in_parsed_field"
    assert report["anomalies"][0]["field"] == "aggregateAmountOwned"
    assert len(report["anomalies"]) == 1


def test_analysis_identifies_common_cover_header_residue(tmp_path: Path) -> None:
    xml = (
        SAMPLE_XML.replace(
            "<dateOfEvent>01-02-2024</dateOfEvent>",
            "<dateOfEvent>________ February 2, 2011________</dateOfEvent>",
        )
        .replace(
            "<issuerCusipNumber>123456789</issuerCusipNumber>",
            "<issuerCusipNumber>_______254546104_________</issuerCusipNumber>",
        )
        .replace(
            "<reportingPersonName>Jane Doe</reportingPersonName>",
            "<reportingPersonName>I.R.S. identification nos. of above persons "
            "(entities only) Gabelli Funds, LLC I.D. No. 13-4044523</reportingPersonName>",
        )
        .replace(
            "<legalProceedings>N</legalProceedings>",
            "<legalProceedings>N</legalProceedings>"
            "<personName>________ February 2, 2011________</personName>"
            "<sharedVotingPower>None Person : With</sharedVotingPower>"
            "<soleDispositivePower>459,600 (Item 5) : : :10</soleDispositivePower>",
        )
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    fields = {
        (item.get("field"), item["kind"])
        for item in report["anomalies"]
        if item["kind"] in {"cover_field_contamination", "boilerplate_in_parsed_field"}
    }
    assert {
        ("dateOfEvent", "cover_field_contamination"),
        ("issuerCusip", "cover_field_contamination"),
        ("noticeContact", "cover_field_contamination"),
        ("sharedVotingPower", "cover_field_contamination"),
        ("reportingPersonName", "boilerplate_in_parsed_field"),
        ("soleDispositivePower", "cover_field_contamination"),
    } <= fields


def test_analysis_recognizes_13g_xml_family(tmp_path: Path) -> None:
    xml = (
        SAMPLE_XML.replace("schedule13D", "schedule13G")
        .replace("SCHEDULE 13D", "SCHEDULE 13G")
        .replace("dateOfEvent", "eventDateRequiresFilingThisStatement")
        .replace(
            "<reportingPersons><reportingPersonInfo>",
            "<coverPageHeaderReportingPersonDetails>",
        )
        .replace(
            "</reportingPersonInfo></reportingPersons>",
            "</coverPageHeaderReportingPersonDetails>",
        )
        .replace("items1To7", "items")
        .replace("<item1>", "<Item1>")
        .replace("</item1>", "</Item1>")
        .replace("signatureInfo", "signatureInformation")
        .replace("<memberOfGroup>", "<memberGroup>")
        .replace("</memberOfGroup>", "</memberGroup>")
    )
    report = analyze_case(
        _write_case(tmp_path, xml), {"accession": "a", "form": "SC 13G/A"}
    )

    assert report is not None
    assert report["family"] == "13G"
    assert report["anomalies"] == []
    mixed = analyze_case(
        _write_case(tmp_path / "second", SAMPLE_XML),
        {"accession": "b", "form": "SC 13D"},
    )
    assert mixed is not None
    assert summarize_cases([report, mixed])["family"] == "mixed"


def test_analysis_flags_invalid_schedule_codes_and_schema_dates(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<typeOfReportingPerson>IN</typeOfReportingPerson>",
        "<typeOfReportingPerson>XX</typeOfReportingPerson>",
    ).replace(
        "<dateOfEvent>01-02-2024</dateOfEvent>", "<dateOfEvent>02-30-2024</dateOfEvent>"
    )

    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert {(item["kind"], item["field"]) for item in report["anomalies"]} == {
        ("invalid_schema_code", "typeOfReportingPerson"),
        ("invalid_schema_date", "dateOfEvent"),
    }


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


def test_analysis_flags_boilerplate_in_non_cover_fields(tmp_path: Path) -> None:
    xml = SAMPLE_XML.replace(
        "<issuerName>Example Corp</issuerName>",
        "<issuerName>SECURITIES AND EXCHANGE COMMISSION Example Corp</issuerName>",
    ).replace(
        "<legalProceedings>N</legalProceedings>",
        "<legalProceedings>N</legalProceedings><personName>Schedule 13D</personName>",
    )
    report = analyze_case(_write_case(tmp_path, xml), {"accession": "a"})

    assert report is not None
    assert {(item["kind"], item["field"]) for item in report["anomalies"]} == {
        ("boilerplate_in_parsed_field", "issuerName"),
        ("boilerplate_in_parsed_field", "noticeContact"),
    }


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
