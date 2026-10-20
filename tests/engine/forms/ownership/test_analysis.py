"""Unit tests for Form 4 ownership review analysis."""

from __future__ import annotations

from edgar_sec.engine.forms.ownership.analysis import (
    analyze_ownership_xml,
    analyze_ownership_review_case,
    summarize_ownership_cases,
)
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections

SAMPLE_CLEAN_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<ownershipDocument>
    <documentType>4</documentType>
    <periodOfReport>2003-03-01</periodOfReport>
    <issuer>
        <issuerCik>0000000001</issuerCik>
        <issuerName>Acme Inc</issuerName>
        <issuerTradingSymbol>ACM</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0000000002</rptOwnerCik>
            <rptOwnerName>Jane Smith</rptOwnerName>
        </reportingOwnerId>
    </reportingOwner>
    <derivativeTable>
        <derivativeHolding>
            <securityTitle><value>Common Stock Option</value></securityTitle>
            <conversionOrExercisePrice><value>10.0</value></conversionOrExercisePrice>
            <exerciseDateAndExpirationDate>
                <exerciseDate><value>2004-03-01</value></exerciseDate>
                <expirationDate><value>2013-03-01</value></expirationDate>
            </exerciseDateAndExpirationDate>
            <underlyingSecurity>
                <underlyingSecurityTitle><value>Common Stock</value></underlyingSecurityTitle>
                <underlyingSecurityShares><value>1000</value></underlyingSecurityShares>
            </underlyingSecurity>
        </derivativeHolding>
    </derivativeTable>
    <ownerSignature><signatureName>Jane Smith</signatureName>
        <signatureDate>2003-03-01</signatureDate></ownerSignature>
</ownershipDocument>
"""

SAMPLE_ANOMALOUS_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<ownershipDocument>
    <derivativeTable>
        <derivativeHolding>
            <securityTitle><value>1. Title of Derivative (Instr. 3)</value></securityTitle>
            <underlyingSecurity>
                <underlyingSecurityTitle><value>03/07/2003 | 03/07/2012</value></underlyingSecurityTitle>
            </underlyingSecurity>
        </derivativeHolding>
    </derivativeTable>
    <unparsedSections>
        <unparsedSection tableIndex="5" role="unparsed">&lt;table&gt;&lt;tr&gt;&lt;td&gt;Unparsed text&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</unparsedSection>
    </unparsedSections>
</ownershipDocument>
"""


def test_analyze_ownership_xml_clean_reports_elements_without_anomalies() -> None:
    res = analyze_ownership_xml(SAMPLE_CLEAN_XML, accession="0001-01-000001")
    assert res["element_counts"]["documentType"] == 1
    assert res["element_counts"]["underlyingSecurityTitle"] == 1
    assert res["anomalies"] == []
    assert res["unparsed_sections"] == []


def test_analyze_ownership_xml_detects_anomalies_and_unparsed() -> None:
    res = analyze_ownership_xml(SAMPLE_ANOMALOUS_XML, accession="0001-01-000002")
    kinds = [a["kind"] for a in res["anomalies"]]
    assert "date_in_underlying_security_title" in kinds
    assert "boilerplate_in_security_title" in kinds
    assert len(res["unparsed_sections"]) == 1
    assert res["unparsed_sections"][0]["table_index"] == "5"


def test_review_analysis_loads_common_sidecar(tmp_path) -> None:
    operations = tmp_path / "operations"
    operations.mkdir()
    (operations / "render_to_xml.xml").write_bytes(
        b"<ownershipDocument><documentType>4</documentType></ownershipDocument>"
    )
    (operations / "unparsed_sections.json").write_bytes(
        serialize_unparsed_sections(
            [
                {
                    "role": "unparsed",
                    "content_type": "text/html",
                    "content": "<table>review content</table>",
                    "table_index": 2,
                }
            ]
        )
    )

    report = analyze_ownership_review_case(tmp_path, {"accession": "a1"})

    assert report is not None
    assert report["unparsed_sections"][0]["table_index"] == "2"
    assert report["unparsed_sections"][0]["snippet"] == (
        "<table>review content</table>"
    )


def test_summarize_ownership_cases_aggregates_metrics() -> None:
    rep1 = analyze_ownership_xml(SAMPLE_CLEAN_XML, accession="0001-01-000001")
    rep2 = analyze_ownership_xml(SAMPLE_ANOMALOUS_XML, accession="0001-01-000002")
    summary = summarize_ownership_cases([rep1, rep2])
    assert summary["case_count"] == 2
    assert summary["anomaly_count"] == 5
    assert summary["unparsed_section_count"] == 1
    assert len(summary["unparsed_samples"]) == 1
    assert "field_completeness" in summary
    assert summary["field_completeness"]["issuerName"] == "1/2 (50%)"


def test_mask_normalized_pattern() -> None:
    from edgar_sec.engine.forms.ownership.analysis import mask_normalized_pattern

    assert (
        mask_normalized_pattern("Employee Stock Option 02/06/2002 Grant")
        == "Employee Stock Option DATE_PATTERN Grant"
    )
    assert (
        mask_normalized_pattern("Statement for June 2001") == "Statement for MONTH ###"
    )
    assert mask_normalized_pattern("CIK: 0000123456 filed June 2001") == (
        "CIK_### filed MONTH ###"
    )


def test_detects_header_leaks_and_signature_boilerplate() -> None:
    xml_with_leaks = b"""<?xml version="1.0" encoding="utf-8"?>
<ownershipDocument>
    <derivativeTable>
        <derivativeHolding>
            <underlyingSecurity>
                <underlyingSecurityTitle><value>Deemed Execution Date, if any (Month/Day/Year)</value></underlyingSecurityTitle>
            </underlyingSecurity>
        </derivativeHolding>
    </derivativeTable>
    <ownerSignature>
        <signatureName>m displays a currently valid OMB number</signatureName>
        <signatureDate>07/03/2001</signatureDate>
    </ownerSignature>
</ownershipDocument>
"""
    res = analyze_ownership_xml(xml_with_leaks, accession="0001-01-000003")
    kinds = [a["kind"] for a in res["anomalies"]]
    assert "header_leak_in_underlying_security_title" in kinds
    assert "boilerplate_in_signature_name" in kinds


def test_analysis_reports_blank_canonical_fields_and_invalid_dates() -> None:
    xml = b"""<ownershipDocument>
    <periodOfReport>2003-03-01</periodOfReport>
    <issuer><issuerCik>0000000001</issuerCik><issuerName>Acme Inc</issuerName><issuerTradingSymbol>ACM</issuerTradingSymbol></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerCik>0000000002</rptOwnerCik><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction>
      <securityTitle><value>Common Stock 03/01/2003</value></securityTitle>
      <transactionDate><value>02/30/2003</value></transactionDate>
      <transactionAmounts><transactionShares><value /></transactionShares></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable>
    <ownerSignature><signatureName>Jane Doe</signatureName><signatureDate>not a date</signatureDate></ownerSignature>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000004")
    kinds = [anomaly["kind"] for anomaly in report["anomalies"]]

    assert "date_in_security_title" in kinds
    assert "invalid_transactionDate" in kinds
    assert "invalid_signatureDate" in kinds
    assert report["field_observations"]["transactionShares"] == {
        "occurrences": 1,
        "populated_occurrences": 0,
        "blank_occurrences": 1,
    }
    summary = summarize_ownership_cases([report])
    assert summary["field_scorecard"]["transactionShares"]["blank_occurrences"] == 1
    assert summary["field_scorecard"]["issuerTradingSymbol"]["cases_without_value"] == 0


def test_analysis_checks_confirmed_ownership_choice_lists() -> None:
    xml = b"""<ownershipDocument>
      <documentType>4</documentType>
      <reportingOwner><reportingOwnerAddress>
        <rptOwnerState>ZZ</rptOwnerState>
      </reportingOwnerAddress></reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionCoding><transactionCode>K</transactionCode></transactionCoding>
        <transactionAmounts><transactionAcquiredDisposedCode><value>X</value>
        </transactionAcquiredDisposedCode></transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000007")

    assert {
        "invalid_transaction_code",
        "invalid_transactionAcquiredDisposedCode",
        "invalid_rptOwnerState",
    }.issubset({anomaly["kind"] for anomaly in report["anomalies"]})


def test_analysis_reports_missing_ciks_and_not_applicable_fields() -> None:
    xml = b"""<ownershipDocument>
      <schemaVersion>X0206</schemaVersion><documentType>4</documentType>
      <issuer><issuerName>ACME</issuerName></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName>
      </reportingOwnerId></reportingOwner>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000010")

    missing = next(
        anomaly
        for anomaly in report["anomalies"]
        if anomaly["kind"] == "missing_required_fields"
    )
    assert set(missing["value"].split(", ")) == {
        "periodOfReport",
        "issuerTradingSymbol",
        "signatureName",
        "signatureDate",
    }
    unavailable = next(
        anomaly
        for anomaly in report["anomalies"]
        if anomaly["kind"] == "fields_absent_from_document_body"
    )
    assert set(unavailable["value"].split(", ")) == {"issuerCik", "rptOwnerCik"}
    assert "not_applicable_schemaVersion" in {
        anomaly["kind"] for anomaly in report["anomalies"]
    }
    assert "not_applicable_issuerName" not in {
        anomaly["kind"] for anomaly in report["anomalies"]
    }


def test_summary_counts_categorical_and_title_values() -> None:
    xml = b"""<ownershipDocument>
    <reportingOwner><reportingOwnerRelationship>
      <isDirector>1</isDirector><isOfficer>0</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship></reportingOwner>
    <nonDerivativeTable>
      <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding></nonDerivativeTransaction>
      <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionCoding><transactionCode>S</transactionCode></transactionCoding></nonDerivativeTransaction>
      <nonDerivativeHolding><securityTitle><value>Preferred Stock</value></securityTitle></nonDerivativeHolding>
    </nonDerivativeTable>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000005")
    summary = summarize_ownership_cases([report])
    frequencies = summary["value_frequencies"]

    assert frequencies["transactionCode"]["distinct_values"] == 2
    assert frequencies["transactionCode"]["top_values"] == [
        {
            "value": "P",
            "count": 1,
            "case_count": 1,
            "sample_accession": "0001-01-000005",
        },
        {
            "value": "S",
            "count": 1,
            "case_count": 1,
            "sample_accession": "0001-01-000005",
        },
    ]
    assert frequencies["securityTitle"]["distinct_values"] == 2
    assert frequencies["securityTitle"]["top_values"][0] == {
        "value": "Common Stock",
        "count": 2,
        "case_count": 1,
        "sample_accession": "0001-01-000005",
    }
    assert frequencies["officerTitle"]["top_values"][0]["value"] == (
        "Chief Executive Officer"
    )
    assert frequencies["isDirector"]["top_values"][0]["value"] == "1"


def test_option_title_date_is_reported_as_review_signal() -> None:
    xml = b"""<ownershipDocument>
    <periodOfReport>2003-04-02</periodOfReport>
    <issuer><issuerCik>0000000001</issuerCik><issuerName>Acme Inc</issuerName><issuerTradingSymbol>ACM</issuerTradingSymbol></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerCik>0000000002</rptOwnerCik><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId></reportingOwner>
    <derivativeTable><derivativeTransaction>
      <securityTitle><value>BOD 4/1/03 Stock Options (Rights to Buy)</value></securityTitle>
    </derivativeTransaction></derivativeTable>
    <ownerSignature><signatureName>Jane Doe</signatureName>
      <signatureDate>2003-04-02</signatureDate></ownerSignature>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000006")
    summary = summarize_ownership_cases([report])

    assert not report["anomalies"]
    assert report["review_signals"][0]["kind"] == "date_in_option_security_title"
    assert summary["review_signal_count"] == 1
    assert summary["review_signal_samples"][0]["accession"] == "0001-01-000006"
