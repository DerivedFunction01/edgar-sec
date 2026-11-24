"""Unit tests for ownership XML audit and schema validation."""

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
