"""Unit tests for Form 4 ownership review analysis."""

from __future__ import annotations

from edgar_sec.engine.forms.ownership.analysis import (
    analyze_ownership_xml,
    summarize_ownership_cases,
)

SAMPLE_CLEAN_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<ownershipDocument>
    <schemaVersion>X0206</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>03/01/2003</periodOfReport>
    <issuer>
        <issuerName>ACME INC</issuerName>
        <issuerTradingSymbol>ACM</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerName>Smith, Jane</rptOwnerName>
        </reportingOwnerId>
    </reportingOwner>
    <derivativeTable>
        <derivativeHolding>
            <securityTitle><value>Common Stock Option</value></securityTitle>
            <conversionOrExercisePrice><value>10.0</value></conversionOrExercisePrice>
            <exerciseDateAndExpirationDate>
                <exerciseDate><value>03/01/2004</value></exerciseDate>
                <expirationDate><value>03/01/2013</value></expirationDate>
            </exerciseDateAndExpirationDate>
            <underlyingSecurity>
                <underlyingSecurityTitle><value>Common Stock</value></underlyingSecurityTitle>
                <underlyingSecurityShares><value>1000</value></underlyingSecurityShares>
            </underlyingSecurity>
        </derivativeHolding>
    </derivativeTable>
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


def test_summarize_ownership_cases_aggregates_metrics() -> None:
    rep1 = analyze_ownership_xml(SAMPLE_CLEAN_XML, accession="0001-01-000001")
    rep2 = analyze_ownership_xml(SAMPLE_ANOMALOUS_XML, accession="0001-01-000002")
    summary = summarize_ownership_cases([rep1, rep2])
    assert summary["case_count"] == 2
    assert summary["anomaly_count"] == 3
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
    <periodOfReport>03/01/2003</periodOfReport>
    <issuer><issuerName>ACME INC</issuerName></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId></reportingOwner>
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
    assert summary["field_scorecard"]["issuerTradingSymbol"]["cases_without_value"] == 1


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
    <periodOfReport>04/02/2003</periodOfReport>
    <issuer><issuerName>ACME INC</issuerName></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId></reportingOwner>
    <derivativeTable><derivativeTransaction>
      <securityTitle><value>BOD 4/1/03 Stock Options (Rights to Buy)</value></securityTitle>
    </derivativeTransaction></derivativeTable>
    </ownershipDocument>"""

    report = analyze_ownership_xml(xml, accession="0001-01-000006")
    summary = summarize_ownership_cases([report])

    assert not report["anomalies"]
    assert report["review_signals"][0]["kind"] == "date_in_option_security_title"
    assert summary["review_signal_count"] == 1
    assert summary["review_signal_samples"][0]["accession"] == "0001-01-000006"
