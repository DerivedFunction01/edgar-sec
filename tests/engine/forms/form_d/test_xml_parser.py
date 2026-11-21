"""Tests for Form D XML parsing."""

from edgar_sec.engine.forms.form_d.xml_parser import parse_form_d_xml

_SAMPLE_FORM_D_XML = b"""<?xml version="1.0"?>
<edgarSubmission>
    <schemaVersion>X0707</schemaVersion>
    <submissionType>D</submissionType>
    <testOrLive>LIVE</testOrLive>
    <primaryIssuer>
        <cik>0001487198</cik>
        <entityName>ASPEN GROUP, INC.</entityName>
        <issuerAddress>
            <street1>1660 SOUTH ALBION STREET</street1>
            <city>DENVER</city>
            <stateOrCountry>CO</stateOrCountry>
            <zipCode>80222</zipCode>
        </issuerAddress>
        <jurisdictionOfInc>DELAWARE</jurisdictionOfInc>
        <entityType>Corporation</entityType>
    </primaryIssuer>
    <relatedPersonsList>
        <relatedPersonInfo>
            <relatedPersonName>
                <firstName>Michael</firstName>
                <lastName>Mathews</lastName>
            </relatedPersonName>
            <relatedPersonRelationshipList>
                <relationship>Executive Officer</relationship>
                <relationship>Director</relationship>
            </relatedPersonRelationshipList>
        </relatedPersonInfo>
    </relatedPersonsList>
    <offeringData>
        <industryGroup>
            <industryGroupType>Other</industryGroupType>
        </industryGroup>
        <federalExemptionsExclusions>
            <item>06b</item>
        </federalExemptionsExclusions>
        <offeringSalesAmounts>
            <totalOfferingAmount>7500000</totalOfferingAmount>
            <totalAmountSold>7500000</totalAmountSold>
            <totalRemaining>0</totalRemaining>
        </offeringSalesAmounts>
        <signatureBlock>
            <signature>
                <issuerName>ASPEN GROUP, INC.</issuerName>
                <signatureName>/s/ Michael Mathews</signatureName>
                <nameOfSigner>Michael Mathews</nameOfSigner>
                <signatureTitle>CEO</signatureTitle>
                <signatureDate>2017-04-20</signatureDate>
            </signature>
        </signatureBlock>
    </offeringData>
</edgarSubmission>
"""


def test_parse_form_d_xml() -> None:
    """Parse Form D XML and check all core fields."""
    doc = parse_form_d_xml(_SAMPLE_FORM_D_XML)
    assert doc.primary_issuer.cik == "0001487198"
    assert doc.primary_issuer.entity_name == "ASPEN GROUP, INC."
    assert len(doc.related_persons) == 1
    assert doc.related_persons[0].last_name == "Mathews"
    assert "Director" in doc.related_persons[0].relationships
    assert doc.offering_amounts.total_offering_amount == 7500000.0
    assert doc.offering_amounts.total_remaining == 0.0
    assert len(doc.signatures) == 1
    assert doc.signatures[0].signature_date == "2017-04-20"
