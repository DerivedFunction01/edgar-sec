"""Tests for Form D review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_d.analysis import analyze_case, summarize_cases

_VALID_XML = b"""<?xml version="1.0"?>
<edgarSubmission>
    <schemaVersion>X0707</schemaVersion>
    <submissionType>D</submissionType>
    <primaryIssuer>
        <cik>0001487198</cik>
        <entityName>ASPEN GROUP, INC.</entityName>
    </primaryIssuer>
    <offeringData>
        <offeringSalesAmounts>
            <totalOfferingAmount>1000000</totalOfferingAmount>
            <totalAmountSold>500000</totalAmountSold>
            <totalRemaining>500000</totalRemaining>
        </offeringSalesAmounts>
        <signatureBlock>
            <signature>
                <signatureName>/s/ John Doe</signatureName>
                <signatureDate>2021-01-01</signatureDate>
            </signature>
        </signatureBlock>
    </offeringData>
</edgarSubmission>"""


def test_analyze_case_and_summarize(tmp_path: Path) -> None:
    """Analyze valid Form D case and summarize metrics."""
    case_dir = tmp_path / "0001487198-21-000001--case1"
    case_dir.mkdir()
    xml_path = case_dir / "extracted.xml"
    xml_path.write_bytes(_VALID_XML)

    report = analyze_case(case_dir)
    assert report["accession_number"] == "0001487198-21-000001"
    assert report["anomalies"] == []
    assert report["core_fields"]["cik"] is True

    summary = summarize_cases([report])
    assert summary["case_count"] == 1
    assert summary["anomaly_count"] == 0
    assert summary["field_scorecard"]["cik"]["cases_with_value"] == 1
