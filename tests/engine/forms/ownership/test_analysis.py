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
    assert summary["anomaly_count"] == 2
    assert summary["unparsed_section_count"] == 1
    assert len(summary["unparsed_samples"]) == 1
