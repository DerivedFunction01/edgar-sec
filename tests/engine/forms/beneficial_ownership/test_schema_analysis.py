import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.beneficial_ownership.schema_analysis import (
    analyze_schema_xml,
)


def test_schedule13d_schema_codes_and_dates_are_validated() -> None:
    root = ET.fromstring(
        """<edgarSubmission><headerData><submissionType>SCHEDULE 13D</submissionType></headerData>
        <formData><coverPageHeader><dateOfEvent>02-29-2024</dateOfEvent></coverPageHeader>
        <reportingPersons/><items1To7/><signatureInfo><signatureDetails>
        <signature>/s/ Jane Doe</signature><title>Director</title><date>02-29-2024</date>
        </signatureDetails></signatureInfo></formData></edgarSubmission>"""
    )

    assert analyze_schema_xml(root, "a", "13D") == []


def test_schedule13g_reports_invalid_codes_dates_and_missing_sections() -> None:
    root = ET.fromstring(
        """<edgarSubmission><headerData><submissionType>13G</submissionType></headerData>
        <formData><coverPageHeader><eventDateRequiresFilingThisStatement>02-30-2024</eventDateRequiresFilingThisStatement>
        <coverPageHeaderReportingPersonDetails><memberGroup>z</memberGroup>
        <typeOfReportingPerson>XX</typeOfReportingPerson></coverPageHeaderReportingPersonDetails>
        </coverPageHeader></formData></edgarSubmission>"""
    )

    anomalies = analyze_schema_xml(root, "a", "13G")

    assert {(item["kind"], item["field"]) for item in anomalies} == {
        ("invalid_schema_code", "submissionType"),
        ("invalid_schema_code", "memberGroup"),
        ("invalid_schema_code", "typeOfReportingPerson"),
        ("invalid_schema_date", "eventDateRequiresFilingThisStatement"),
        ("missing_required_schema_field", "coverPageHeaderReportingPersonDetails"),
        ("missing_required_schema_field", "items"),
        ("missing_required_schema_field", "signatureInformation"),
    }
