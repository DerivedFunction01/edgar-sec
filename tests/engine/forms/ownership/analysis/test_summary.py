"""Unit tests for ownership review summary aggregation."""

from __future__ import annotations

from edgar_sec.engine.forms.ownership.analysis.summary import (
    summarize_ownership_cases,
)
from edgar_sec.engine.forms.ownership.analysis.xml_audit import analyze_ownership_xml

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
